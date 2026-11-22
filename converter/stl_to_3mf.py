#!/usr/bin/env python3
"""Convert an STL into a Creality Print project (.3mf) for the Ender-3 V3 SE.

The output is a full slicer project: the mesh centred on the bed plus printer,
process and filament settings (0.4 mm nozzle, PLA or PETG). Settings are the
stock Creality Print presets (converter/template/stock_settings_<material>.json) with a
profile from converter/profiles/*.json layered on top. Output goes to 3mf/ in the repository root
by default.

    python converter/stl_to_3mf.py model.stl                    # PLA, quality profile
    python converter/stl_to_3mf.py model.stl -p hf_fast         # high-flow nozzle, fastest
    python converter/stl_to_3mf.py model.stl -m petg -p fast    # PETG
    python converter/stl_to_3mf.py model.stl --nozzle-temp-first 220 --nozzle-temp 210
    python converter/stl_to_3mf.py model.stl -p fast -o out.3mf
    python converter/stl_to_3mf.py --list-profiles
"""
import argparse
import os

from src.config import GENERIC_DIRS, MATERIALS, OUTPUT_DIR
from src.package import convert
from src.settings import list_profiles, load_profile


def expand_inputs(inputs):
    """Files stay as given; a directory becomes every .stl in it, sorted by name."""
    out = []
    for item in inputs:
        if os.path.isdir(item):
            found = sorted((f for f in os.listdir(item) if f.lower().endswith(".stl")), key=str.lower)
            if not found:
                raise SystemExit(f"no .stl files in {item}")
            out += [os.path.join(item, f) for f in found]
        elif os.path.isfile(item):
            out.append(item)
        else:
            raise SystemExit(f"file not found: {item}")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stl", nargs="*", help="input STL file (binary or ASCII). Several files, or a folder of "
                                           "STL files, give one project with one plate per file")
    ap.add_argument("-o", "--output", help="output .3mf (default: 3mf/<stl or folder name>_claude_ender3"
                                           "[_<material>]<profile suffix>.3mf next to this script)")
    ap.add_argument("-p", "--profile", default="quality", help="profile name in profiles/ or path to a profile JSON")
    ap.add_argument("-m", "--material", default="pla", choices=sorted(MATERIALS), help="filament type (default: pla)")
    ap.add_argument("--nozzle-temp-first", type=int, metavar="C", help="nozzle temperature for the first layer")
    ap.add_argument("--nozzle-temp", type=int, metavar="C", help="nozzle temperature for the other layers")
    ap.add_argument("--bed-temp", type=int, metavar="C", help="bed temperature for all layers")
    ap.add_argument("--layer-height", type=float, metavar="MM", help="layer height, overrides the profile")
    ap.add_argument("--support", action="store_true", help="enable supports (the slicer's automatic normal supports)")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", dest="extra",
                    help="set any slicer setting of the stock presets, e.g. --set brim_type=outer_only "
                         "(repeatable, applied last)")
    ap.add_argument("--list-profiles", action="store_true", help="show the available profiles and exit")
    a = ap.parse_args()
    if a.list_profiles:
        for p in list_profiles():
            print(f"{p:10s} {load_profile(p).get('description', '')}")
        return
    if not a.stl:
        ap.error("an STL file is required")
    paths = expand_inputs(a.stl)
    if any("=" not in item for item in a.extra):
        ap.error("--set needs KEY=VALUE")
    extra = dict(item.split("=", 1) for item in a.extra)
    profile = load_profile(a.profile)
    first = os.path.abspath(a.stl[0]).rstrip(os.sep)
    if os.path.isdir(first):
        # "files" or "stl" says nothing and would collide between downloads: use the parent's name
        stem = os.path.basename(os.path.dirname(first) if os.path.basename(first).lower() in GENERIC_DIRS
                                else first)
    else:
        stem = os.path.splitext(os.path.basename(first))[0]
    if len(paths) > 1 and not os.path.isdir(first):
        stem += f"_and_{len(paths) - 1}_more"
    material = "" if a.material == "pla" else f"_{a.material}"
    out = a.output or os.path.join(
        OUTPUT_DIR, f"{stem}_claude_ender3{material}{profile.get('suffix', '_' + a.profile)}.3mf")
    convert(paths, out, a.profile, a.material, a.nozzle_temp_first, a.nozzle_temp, a.bed_temp,
            a.layer_height, a.support, extra)


if __name__ == "__main__":
    main()
