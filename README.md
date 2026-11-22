# 3d-print-tools

Command-line tools for preparing 3D prints. The first tool turns STL files
into ready-to-slice **Creality Print projects** (`.3mf`) for a Creality
Ender-3 V3 SE: the model placed on the bed, with printer, process and filament
settings already filled in.

## At a glance

- **Printer**: Creality Ender-3 V3 SE, 0.4 mm nozzle, 220 x 220 x 250 mm
- **Slicer**: Creality Print 7.3 (an Orca Slicer fork); the output opens as a
  normal project
- **Materials**: PLA and PETG, each on its stock filament preset
- **Profiles**:
  - `quality` — 0.20 mm layers, 3 walls, slow outer walls and bridges
  - `fast` — 0.24 mm layers, 2 walls, 10% infill, higher speeds
  - `hf_fast` — for a high-flow 0.4 nozzle: 0.28 mm layers, raised flow limit,
    retraction tuned against stringing
- **Temperatures**: first layer, other layers and bed can be set per run
- **Batch**: several STL files or a folder give one project with one plate per
  file (up to 36)
- **Checks**: warns about meshes that are not watertight or do not fit the bed
- **Needs**: Python 3.12+ and numpy; the slicer is not needed to convert

## Quick start

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

.venv/bin/python converter/stl_to_3mf.py model.stl                  # PLA, quality
.venv/bin/python converter/stl_to_3mf.py model.stl -p hf_fast       # fastest, high-flow nozzle
.venv/bin/python converter/stl_to_3mf.py model.stl -m petg -p fast  # PETG
.venv/bin/python converter/stl_to_3mf.py model.stl --nozzle-temp-first 220 --nozzle-temp 210 --bed-temp 65
.venv/bin/python converter/stl_to_3mf.py folder_of_stls/ -p hf_fast # one plate per STL
```

The result lands in `3mf/`, for example `3mf/model_claude_ender3_hf_fast.3mf`.
Open it in Creality Print, check that the three preset names loaded and that
the part lies the way you want, then slice.

## Sample

`samples/3DBenchy.stl` and `samples/3DBenchy_claude_ender3.3mf` show an input
and the project made from it with the default `quality` profile:

```sh
.venv/bin/python converter/stl_to_3mf.py samples/3DBenchy.stl -o samples/3DBenchy_claude_ender3.3mf
```

The 3DBenchy model is by Creative Tools / NTI Group and is released under
CC0 1.0 (public domain).

## Good to know

- The converter keeps the orientation stored in the STL. It never rotates or
  scales a model.
- The converter does not slice; print time is known after slicing. Generated
  projects have been sliced with Creality Print 7.3.1 and its settings were
  applied.
- All profiles stay within the printer's rated 250 mm/s and 2500 mm/s².
- `stl/` (input models) and `3mf/` (generated projects) are local folders and
  are not part of the repository.

## Documentation

- [docs/usage.md](docs/usage.md) — options, output names, multi-plate projects,
  what to check after converting
- [docs/profiles.md](docs/profiles.md) — stock presets and every setting each
  profile changes, for PLA and PETG; how to add a profile
- [docs/project-format.md](docs/project-format.md) — what is inside the `.3mf`,
  the plate layout, regenerating the stock snapshots, adding a material
- [docs/repository.md](docs/repository.md) — folder layout
- [docs/repo-rules.md](docs/repo-rules.md) — rules for changes, git and
  documentation
- [changelog/](changelog/) — change history, one file per day

## License

Apache License 2.0, see [LICENSE](LICENSE). The sample model in `samples/` is
CC0 1.0.
