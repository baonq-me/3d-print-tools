# Using the converter

[← README](../README.md)

`converter/stl_to_3mf.py` turns STL files into a ready-to-slice Creality Print
project (`.3mf`) for the Creality Ender-3 V3 SE with a 0.4 mm nozzle.

## Setup

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Python 3.12 or newer (required by the pinned numpy). The only dependency is numpy.

## Commands

```sh
.venv/bin/python converter/stl_to_3mf.py model.stl                 # PLA, quality profile
.venv/bin/python converter/stl_to_3mf.py model.stl -p fast
.venv/bin/python converter/stl_to_3mf.py model.stl -p hf_fast      # high-flow nozzle
.venv/bin/python converter/stl_to_3mf.py model.stl -m petg -p fast
.venv/bin/python converter/stl_to_3mf.py model.stl --nozzle-temp-first 220 --nozzle-temp 210
.venv/bin/python converter/stl_to_3mf.py model.stl -p fast -o out.3mf
.venv/bin/python converter/stl_to_3mf.py folder_of_stls/ -p hf_fast   # one project, one plate per STL
.venv/bin/python converter/stl_to_3mf.py a.stl b.stl c.stl -o 3mf/set.3mf
.venv/bin/python converter/stl_to_3mf.py --list-profiles
```

| Option | Meaning |
|---|---|
| `-p`, `--profile` | `quality` (default), `fast`, `hf_fast`, or a path to a profile JSON |
| `-m`, `--material` | `pla` (default) or `petg` |
| `--nozzle-temp-first C` | nozzle temperature for the first layer |
| `--nozzle-temp C` | nozzle temperature for the other layers |
| `--bed-temp C` | bed temperature for all layers |
| `-o`, `--output` | output path; overrides the default location and name |
| `--list-profiles` | show the available profiles and exit |

## Output files

Files go to `3mf/` in the repository root, named
`<name>_claude_ender3[_<material>]<profile suffix>.3mf`, for example
`3mf/3DBenchy_claude_ender3.3mf`, `3mf/3DBenchy_claude_ender3_hf_fast.3mf` and
`3mf/3DBenchy_claude_ender3_petg_fast.3mf`. PLA has no material suffix.

`<name>` is the STL name. For a folder it is the folder name (or its parent
when the folder is just called `files` or `stl`); for several files it is
`<first stl>_and_<n>_more`.

## Custom temperatures

Custom temperatures override the profile. The converter refuses values the
printer cannot reach (nozzle 150-260 °C, bed 0-100 °C) and warns when a nozzle
temperature is outside the range the filament preset recommends.

## What the converter does

1. Reads a binary or ASCII STL and welds identical vertices.
2. Centres the model on the 220 x 220 mm bed with its lowest point at Z = 0.
   It never scales or rotates.
3. Starts from the stock Creality Print presets and applies one profile
   ([profiles.md](profiles.md)).
4. Renders the plate thumbnails and writes the `.3mf`
   ([project-format.md](project-format.md)).

It warns if the mesh is not watertight or does not fit the 220 x 220 x 250 mm
build volume.

## Several STL files in one project

Give several STL files, or a folder (every `.stl` in it, sorted by name), to
get one project with **one plate per file**. Each part is centred on its own
plate and the plate is named after the file. All plates share the same
profile and filament. Creality Print allows at most 36 plates per project, so
more than 36 files must be split over several runs. Parts are never packed
together on a plate; use the slicer's arrange if you want that.

## After converting

Open the file in Creality Print and check, before slicing:

- the three preset names (printer, process, filament) loaded; process and
  filament show as "modified", which is expected;
- the part lies the way you want to print it. The converter keeps the
  orientation stored in the STL; use "Lay on face" if the part is tilted;
- for a multi-plate project, the plate count and that each part sits on its
  own plate.

## Limitations

- Creality Print has no headless mode, so the generated projects are not
  loaded in the slicer by any script here. Opening the file is the final check.
- Print times are unknown until you slice.
- No automatic orientation, no packing of several parts on one plate, no
  supports.
