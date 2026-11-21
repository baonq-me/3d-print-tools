# Presets and profiles

[← README](../README.md)

Base presets (stock Creality Print 7.3):

| Kind | Preset |
|---|---|
| Printer | `Creality Ender-3 V3 SE 0.4 nozzle` |
| Process | `0.20mm Standard @Creality Ender-3 V3 SE 0.4 nozzle` |
| Filament (PLA) | `Soleyin Ultra PLA @Creality Ender-3 V3 SE 0.4 nozzle` |
| Filament (PETG) | `Generic PETG @Creality Ender-3 V3 SE 0.4 nozzle` |

Each profile in `converter/profiles/` is a small JSON file of changes on top of those
presets: one set of process changes, and one set of filament changes per
material. In Creality Print the process and filament show as "modified",
which is expected.

## Process and PLA settings

| Setting | stock | `quality` | `fast` | `hf_fast` |
|---|---|---|---|---|
| Layer height (mm) | 0.20 | 0.20 | 0.24 | 0.28 |
| Wall loops | 2 | 3 | 2 | 2 |
| Top / bottom shell layers | 4 / 4 | 4 / 4 | 4 / 4 | 3 / 3 |
| Outer / inner wall speed (mm/s) | 60 / 90 | 45 / 80 | 80 / 140 | 80 / 160 |
| Sparse / solid infill speed (mm/s) | 180 / 180 | 120 / 120 | 150 / 150 | 200 / 180 |
| Top surface speed (mm/s) | 50 | 50 | 80 | 80 |
| Bridge speed (mm/s) | 50 | 30 | 40 | 40 |
| First layer speed / infill (mm/s) | 30 / 80 | 30 / 50 | 40 / 80 | 40 / 80 |
| Travel speed (mm/s) | 150 | 150 | 220 | 250 |
| Outer / inner wall acceleration (mm/s²) | 1000 / 2000 | 800 / 2000 | 2000 / 2500 | 2000 / 2500 |
| Top surface acceleration (mm/s²) | 2500 | 1000 | 2500 | 2500 |
| First layer acceleration (mm/s²) | 500 | 500 | 1000 | 1000 |
| Infill | zig-zag 15% | gyroid 15% | zig-zag 10% | zig-zag 10% |
| Small-perimeter slowdown | off | below 6.5 mm radius | off | off |
| Avoid crossing walls | off | off | off | on |
| Nozzle temp, first layer / rest (°C) | 220 / 220 | 215 / 205 | 215 / 215 | 215 / 210 |
| Bed temp (°C) | 50 | 60 | 60 | 60 |
| Max volumetric flow (mm³/s) | 16 | 16 | 16 | 24 |
| Retraction length (mm) | 0.8 | 1.0 | 1.0 | 1.2 |
| Retraction / deretraction speed (mm/s) | 15 / 15 | 15 / 15 | 15 / 15 | 40 / 30 |
| Z-hop (mm) | 0.4 | 0.4 | 0.4 | 0.2 |
| Minimum layer time (s) | 12 | 12 | 8 | 5 |

All profiles stay within the printer's rated 250 mm/s and 2500 mm/s². No
supports, no brim, aligned seam, stock start and end G-code.

- **quality** — best surface; use for display pieces.
- **fast** — standard nozzle, noticeably quicker, more visible layer lines.
- **hf_fast** — needs a high-flow 0.4 nozzle. Thick layers, raised flow limit,
  and retraction tuned against stringing. The 24 mm³/s limit is a cautious
  default; raise it in the profile if your nozzle handles more.

## PETG settings

With `-m petg` the process settings above still apply, and the filament side
becomes:

| Setting | stock PETG | `quality` | `fast` | `hf_fast` |
|---|---|---|---|---|
| Nozzle temp, first layer / rest (°C) | 220 / 220 | 240 / 235 | 240 / 240 | 245 / 245 |
| Bed temp (°C) | 70 | 70 | 70 | 70 |
| Max volumetric flow (mm³/s) | 10 | 10 | 12 | 16 |
| Minimum layer time (s) | 8 | 8 | 8 | 6 |
| Retraction length (mm) | 1.2 | 1.2 | 1.2 | 1.2 |
| Z-hop (mm) | 0.2 | 0.2 | 0.2 | 0.2 |
| Part fan (%) | 40–80, off for 3 layers | same | same | same |

- PETG melts more slowly than PLA, so the flow limit caps real speed well
  below the profile's speed values: at 10 mm³/s and 0.2 mm layers that is
  about 110 mm/s. The fast profiles save less time in PETG than in PLA.
- The stock preset's 220 °C is the bottom of its own 220–270 °C range; the
  profiles print hotter for layer bonding. Check the range on your spool and
  use `--nozzle-temp-first` / `--nozzle-temp` to match it.
- PETG absorbs moisture and strings when damp; dry it if stringing persists.

## Adding a profile

Copy a file in `converter/profiles/`, change the values, and pass its name with `-p`.
Keys under `process` and `filament.<material>` must be settings of the stock
presets (see `converter/template/stock_settings_<material>.json`); the converter
rejects unknown keys. `suffix` sets the output file name suffix.
