#!/usr/bin/env python3
"""Regenerate converter/template/stock_settings_<material>.json from an installed Creality Print.

The snapshot is the flat project config that Creality Print itself would write
for the stock printer / process / filament presets. stl_to_3mf.py layers the
profile deltas (converter/profiles/*.json) on top of it, so it never needs the slicer.

Inputs:
  * the system presets shipped with Creality Print (values). They are found in
    the standard locations on macOS, Windows and Linux; use --presets-dir for
    any other install, and
  * a project .3mf saved by the same Creality Print version (key set, value
    shapes and serialisation format; its own values are overwritten).
"""
import argparse
import copy
import glob
import json
import os
import re
import sys
import zipfile

def _version_key(path):
    """Sort key that puts the newest Creality Print version first."""
    return [int(n) for n in re.findall(r"\d+", path)]


def default_preset_dirs():
    """Folders that hold Creality Print's system presets, on any OS.

    Each folder contains machine/, process/ and filament/. The per-user copy
    comes first (it is what the running slicer uses and gets updated online),
    then the copy shipped inside the application. The newest version wins.
    """
    home = os.path.expanduser("~")
    if sys.platform == "darwin":
        user = [os.path.join(home, "Library", "Application Support", "Creality", "Creality Print", "*")]
        app = [os.path.join(root, "Creality Print*.app", "Contents", "Resources", "profiles")
               for root in ("/Applications", os.path.join(home, "Applications"))]
    elif sys.platform == "win32":
        appdata = os.environ.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
        user = [os.path.join(appdata, "Creality", "Creality Print", "*")]
        app = [os.path.join(root, "Creality", "Creality Print*", "resources", "profiles")
               for root in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"),
                            os.environ.get("LOCALAPPDATA")) if root]
    else:  # Linux and other Unix
        config = os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
        user = [os.path.join(config, "Creality", "Creality Print", "*"),
                os.path.join(home, ".var", "app", "*", "config", "Creality", "Creality Print", "*")]
        app = [os.path.join(root, "resources", "profiles")
               for root in ("/usr/share/CrealityPrint", "/usr/share/Creality Print",
                            "/opt/CrealityPrint", "/opt/Creality Print")]
    found = []
    for patterns, tail in ((user, os.path.join("system", "Creality")), (app, "Creality")):
        hits = [d for pattern in patterns for d in glob.glob(os.path.join(pattern, tail))]
        found += sorted((d for d in hits if os.path.isdir(d)), key=_version_key, reverse=True)
    return found


PRESET_DIRS = []   # filled in main(): --presets-dir first, then default_preset_dirs()
SKIP = {"type", "from", "name", "inherits", "instantiation", "setting_id", "filament_id",
        "compatible_printers", "compatible_printers_condition", "version"}
# Keys whose slicer-serialised form differs from the preset JSON; keep the slicer's.
KEEP_SERIALIZED = {"thumbnails", "support_interface_speed"}


def flat(kind, name):
    """Resolve a system preset and its whole `inherits` chain into one dict."""
    for root in PRESET_DIRS:
        path = os.path.join(root, kind, name + ".json")
        if os.path.exists(path):
            break
    else:
        searched = "\n  ".join(PRESET_DIRS) or "(no Creality Print preset folder found)"
        raise SystemExit(f"{kind} preset not found: {name}\nsearched:\n  {searched}\n"
                         f"pass --presets-dir with the folder that holds machine/, process/ and filament/")
    d = json.load(open(path))
    if d.get("inherits"):
        base = flat(kind, d["inherits"])
        base.update(d)
        return base
    return d


def norm(v):
    """Compare values semantically ("25%" == "25", ["500","500"] == "500,500")."""
    if isinstance(v, list):
        v = ",".join(str(x) for x in v)
    v = str(v)
    for junk in ('"', "%", " ", "\\n", "\n"):
        v = v.replace(junk, "")
    out = []
    for part in v.replace(";", ",").split(","):
        try:
            out.append(repr(float(part)))
        except ValueError:
            out.append(part)
    return ",".join(out)


def shaped(like, val):
    """Give `val` the same container shape (list vs string) as `like`."""
    if isinstance(like, list):
        if isinstance(val, list):
            return [str(x) for x in val]
        parts = val.split(",")
        return parts if len(like) > 1 and len(parts) == len(like) else [val]
    if isinstance(val, list):
        return val[0] if len(val) == 1 else ",".join(val)
    return val


def project_settings(path):
    return json.loads(zipfile.ZipFile(path).read("Metadata/project_settings.config"))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reference", required=True, help="project .3mf saved by Creality Print (schema source)")
    ap.add_argument("--filament-reference", help="optional project .3mf saved with the same filament preset")
    ap.add_argument("--machine", default="Creality Ender-3 V3 SE 0.4 nozzle")
    ap.add_argument("--process", default="0.20mm Standard @Creality Ender-3 V3 SE 0.4 nozzle")
    ap.add_argument("--filament", default="Soleyin Ultra PLA @Creality Ender-3 V3 SE 0.4 nozzle")
    ap.add_argument("--presets-dir", action="append", default=[], metavar="DIR",
                    help="folder with Creality Print's machine/, process/ and filament/ presets; "
                         "searched before the standard install locations (repeatable)")
    ap.add_argument("-o", "--output", default=os.path.join(os.path.dirname(__file__), "..", "converter", "template", "stock_settings_pla.json"))
    a = ap.parse_args()
    PRESET_DIRS[:] = [os.path.expanduser(d) for d in a.presets_dir] + default_preset_dirs()

    base = project_settings(a.reference)
    fil_ref = project_settings(a.filament_reference) if a.filament_reference else {}
    cfg, groups, presets = copy.deepcopy(base), {}, {}
    for kind, name in (("machine", a.machine), ("process", a.process), ("filament", a.filament)):
        preset = flat(kind, name)
        presets[kind] = name
        groups[kind] = sorted(k for k in preset if k not in SKIP and k in base)
        for k in groups[kind]:
            v = preset[k]
            candidates = [base[k]]
            if kind == "filament" and k in fil_ref and type(fil_ref[k]) == type(base[k]):
                candidates.insert(0, fil_ref[k])
            ser = next((c for c in candidates if norm(c) == norm(v)), None)
            if k in KEEP_SERIALIZED:
                ser = base[k]
            if ser is not None:
                cfg[k] = copy.deepcopy(ser)
            else:
                cfg[k] = shaped(base[k], v)
                print(f"[{kind}] {k}: reference {json.dumps(base[k])[:40]} -> preset {json.dumps(cfg[k])[:60]}")
        if kind == "filament":
            presets["filament_id"] = preset.get("filament_id", "")
    cfg.update({
        "printer_settings_id": a.machine, "print_settings_id": a.process,
        "filament_settings_id": [a.filament], "print_compatible_printers": [a.machine],
        "default_print_profile": a.process, "filament_ids": [presets["filament_id"]],
        "inherits_group": ["", "", ""], "flush_volumes_changed": "0",
        "different_settings_to_system": ["", "", ""], "from": "project", "name": "project_settings",
    })
    out = {"creality_print_version": base["version"], "presets": presets, "groups": groups, "settings": cfg}
    with open(a.output, "w") as f:
        json.dump(out, f, indent=1, sort_keys=True)
        f.write("\n")
    print(f"wrote {os.path.normpath(a.output)}: {len(cfg)} keys, Creality Print {base['version']}")


if __name__ == "__main__":
    main()
