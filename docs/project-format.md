# Project format and stock snapshots

[← README](../README.md)

Creality Print 7.3 is a fork of Orca Slicer / Bambu Studio. Its project file is
a zip (`.3mf`) and the slicer is strict about what is inside: a file that is a
valid zip can still open with its settings silently dropped.

## What the converter writes

| Entry | Holds |
|---|---|
| `3D/3dmodel.model` | one wrapper object and one build item per part; the item transform places the part on its plate |
| `3D/Objects/object_<n>.model` | the mesh of part `n`, centred on its own origin |
| `3D/_rels/3dmodel.model.rels`, `_rels/.rels`, `[Content_Types].xml` | package relationships and content types |
| `Metadata/project_settings.config` | flat JSON with every printer, process and filament setting |
| `Metadata/model_settings.config` | object names, source file, one `<plate>` block per plate |
| `Metadata/plate_<n>.json` | bounding boxes of the objects on plate `n`, in plate coordinates |
| `Metadata/plate_<n>.png`, `plate_<n>_small.png`, `plate_no_light_<n>.png`, `top_<n>.png`, `pick_<n>.png` | thumbnails, 300 x 300 px (small: 96 x 96) |
| `Metadata/creality.config`, `slice_info.config`, `custom_gcode_per_layer.xml` | slicer version stamps and an empty custom G-code list |

## Settings rules

- `project_settings.config` must have exactly the key set the slicer writes
  and each value in the slicer's shape (string or list of strings).
- Every setting that differs from the stock preset must be named in
  `different_settings_to_system`, a list of three `;`-joined strings: process,
  filament, machine. `build_settings()` in `converter/src/settings.py` fills it.
- Preset JSON values are **not** in project format. The slicer writes `25%`
  where the preset says `25`, lists where presets have comma strings, and so
  on. Never copy a preset value straight into a project.

## Plates

Several parts give one plate per part. Plate `i` (0-based) of `count` plates
sits at

```
cols   = ceil(sqrt(count))
origin = ((i % cols) * 1.2 * bed_x, -(i // cols) * 1.2 * bed_y)
```

This is the slicer's own layout (`compute_shape_position` and
`LOGICAL_PART_PLATE_GAP` in its `PartPlate.cpp`). The slicer assigns objects to
plates by position, so a part must sit inside its plate's area. A project holds
at most 36 plates (`MAX_PLATE_COUNT`).

## Stock snapshots

`converter/template/stock_settings_pla.json` and `stock_settings_petg.json`
are snapshots of the stock presets in the format Creality Print writes into a
project, with `groups` listing which keys belong to machine, process and
filament. They are generated; do not edit them by hand.

Regenerate them after a Creality Print update, or to target another printer,
nozzle or filament preset:

```sh
.venv/bin/python tools/snapshot_stock_settings.py \
    --reference path/to/project_saved_by_creality_print.3mf \
    --machine  "Creality Ender-3 V3 SE 0.4 nozzle" \
    --process  "0.20mm Standard @Creality Ender-3 V3 SE 0.4 nozzle" \
    --filament "Soleyin Ultra PLA @Creality Ender-3 V3 SE 0.4 nozzle" \
    -o converter/template/stock_settings_pla.json
```

For PETG, pass `--filament "Generic PETG @Creality Ender-3 V3 SE 0.4 nozzle"`
and `-o converter/template/stock_settings_petg.json`.

This step needs Creality Print installed (macOS paths) and any project file
saved by that version. The preset files supply the values; the saved project
supplies the key set and the value format.

## Adding a material

1. Create a snapshot for its stock filament preset in `converter/template/`.
2. Add it to `MATERIALS` in `converter/src/config.py`.
3. Add a `filament.<material>` block to every profile in `converter/profiles/`.

Filament values of one material must never be reused for another.

## Checking a generated file without the slicer

1. `unzip -tq file.3mf`.
2. Parse every `.model`, `.config`, `.xml` and `.rels` entry as XML
   (`project_settings.config` is JSON).
3. Compare the keys and value types of `project_settings.config` with the
   snapshot for that material.
4. Look at `Metadata/plate_1.png`.

Do not start the Creality Print binary from a script to test: any invocation,
even `--help`, opens the GUI. Bambu Studio's command line can slice the mesh
but ignores the embedded settings, so it only proves the geometry loads.
