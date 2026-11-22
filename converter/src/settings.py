"""Stock presets, profiles and custom temperatures -> project settings."""
import copy
import json
import os

from .config import BED_MAX_C, HOTEND_MAX_C, PROFILE_DIR, TEMPLATE_DIR


def load_profile(name):
    path = name if os.path.isfile(name) else os.path.join(PROFILE_DIR, name + ".json")
    if not os.path.isfile(path):
        raise SystemExit(f"unknown profile '{name}' (available: {', '.join(list_profiles())})")
    return json.load(open(path))


def list_profiles():
    return sorted(f[:-5] for f in os.listdir(PROFILE_DIR) if f.endswith(".json"))


def stock_path(material):
    return os.path.join(TEMPLATE_DIR, f"stock_settings_{material}.json")


def profile_deltas(profile, material):
    """Profile changes per settings group; filament changes are per material."""
    return {"process": profile.get("process", {}),
            "filament": dict(profile.get("filament", {}).get(material, {})),
            "machine": profile.get("machine", {})}


def build_settings(stock, deltas, colour):
    """Apply setting deltas to the stock config; record them as preset edits."""
    cfg = copy.deepcopy(stock["settings"])
    changed = {"process": [], "filament": [], "machine": []}
    for group in changed:
        for key, value in deltas.get(group, {}).items():
            if key not in stock["groups"][group]:
                raise SystemExit(f"profile key '{key}' is not a {group} setting of the stock preset")
            new = [str(value)] if isinstance(cfg[key], list) else str(value)
            if new != cfg[key]:
                cfg[key] = new
                changed[group].append(key)
    cfg["different_settings_to_system"] = [";".join(sorted(changed[g])) for g in ("process", "filament", "machine")]
    cfg["filament_colour"] = [colour]
    return cfg


def temperature_overrides(stock, nozzle_first, nozzle_other, bed):
    """Validate custom temperatures -> (filament deltas, warnings)."""
    s, out, warnings = stock["settings"], {}, []
    lo, hi = int(s["nozzle_temperature_range_low"][0]), int(s["nozzle_temperature_range_high"][0])
    for label, key, value in (("first-layer nozzle", "nozzle_temperature_initial_layer", nozzle_first),
                              ("nozzle", "nozzle_temperature", nozzle_other)):
        if value is None:
            continue
        if not 150 <= value <= HOTEND_MAX_C:
            raise SystemExit(f"{label} temperature {value} C is outside what the hotend supports "
                             f"(150-{HOTEND_MAX_C} C)")
        if not lo <= value <= hi:
            warnings.append(f"{label} temperature {value} C is outside the filament preset's "
                            f"recommended {lo}-{hi} C")
        out[key] = str(value)
    if bed is not None:
        if not 0 <= bed <= BED_MAX_C:
            raise SystemExit(f"bed temperature {bed} C is outside what the bed supports (0-{BED_MAX_C} C)")
        out["hot_plate_temp"] = out["hot_plate_temp_initial_layer"] = str(bed)
    return out, warnings


def process_overrides(stock, layer_height, support):
    """Validate a custom layer height / support switch -> (process deltas, warnings)."""
    s, out, warnings = stock["settings"], {}, []
    if layer_height is not None:
        lo, hi = float(s["min_layer_height"][0]), float(s["max_layer_height"][0])
        if not lo <= layer_height <= hi:
            raise SystemExit(f"layer height {layer_height:g} mm is outside what the nozzle preset allows "
                             f"({lo:g}-{hi:g} mm)")
        out["layer_height"] = f"{layer_height:g}"
    if support:
        out["enable_support"] = "1"
    return out, warnings
