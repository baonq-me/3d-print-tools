#!/usr/bin/env python3
"""Regenerate converter/template/stock_settings_<material>.json from an installed Creality Print.

The snapshot is the flat project config that Creality Print itself would write
for the stock printer / process / filament presets. stl_to_3mf.py layers the
profile deltas (converter/profiles/*.json) on top of it, so it never needs the slicer.

Inputs:
  * the system presets shipped with Creality Print (values), and
  * a project .3mf saved by the same Creality Print version (key set, value
    shapes and serialisation format; its own values are overwritten).
"""
import argparse, copy, json, os, zipfile

SYS_DIRS = [
    os.path.expanduser("~/Library/Application Support/Creality/Creality Print/7.3/system/Creality"),
    "/Applications/Creality Print.app/Contents/Resources/profiles/Creality",
]
SKIP = {"type", "from", "name", "inherits", "instantiation", "setting_id", "filament_id",
        "compatible_printers", "compatible_printers_condition", "version"}
# Keys whose slicer-serialised form differs from the preset JSON; keep the slicer's.
KEEP_SERIALIZED = {"thumbnails", "support_interface_speed"}


def flat(kind, name):
    """Resolve a system preset and its whole `inherits` chain into one dict."""
    for root in SYS_DIRS:
        path = os.path.join(root, kind, name + ".json")
        if os.path.exists(path):
            break
    else:
        raise FileNotFoundError(f"{kind} preset not found: {name}")
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
    ap.add_argument("-o", "--output", default=os.path.join(os.path.dirname(__file__), "..", "converter", "template", "stock_settings_pla.json"))
    a = ap.parse_args()

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
