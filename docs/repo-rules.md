# Repository rules

[← README](../README.md)

These rules apply to people and AI agents alike. Where things live today:
[repository.md](repository.md).

## 1. Setup

| Step | Command / rule |
|---|---|
| Clone | `git clone https://github.com/baonq-me/3d-print-tools.git` |
| Python | `python3 -m venv .venv` then `.venv/bin/pip install -r requirements.txt`; packages go into the venv, never into the system Python |
| Run | always through `.venv/bin/python` |
| Slicer | Creality Print 7.3 is needed only to open the results and to regenerate the stock snapshots |

## 2. Structure: where each kind of file goes

| Kind of file | Goes in | Rule |
|---|---|---|
| Converter code | `converter/src/<area>.py` | `converter/stl_to_3mf.py` holds only the command line |
| Print profiles | `converter/profiles/<name>.json` | changes on top of the stock presets; every profile has a block for every material |
| Stock snapshots | `converter/template/` | generated, never edited by hand |
| Maintenance scripts | `tools/` | standard library where possible |
| Knowledge | `docs/<topic>.md` | one topic per file, linked from the README |
| Change history | `changelog/YYYY-MM-DD.md` | one file per day; create today's file or append to it |
| Input models | `stl/` | local only |
| Generated projects | `3mf/` | local only; every generated `.3mf` goes here |
| Throwaway scripts and test output | outside the repository | |

New top-level folders need a row in this table and in
[repository.md](repository.md).

## 3. Converter rules

- Keep `project_settings.config` exactly as the snapshot has it: same keys,
  same value shapes ([project-format.md](project-format.md)).
- Every changed setting is listed in `different_settings_to_system`.
- Profiles stay inside the printer's rated limits: 250 mm/s, 2500 mm/s²,
  nozzle 260 °C, bed 100 °C. The firmware caps in the machine preset
  (500 mm/s, 5000 mm/s²) are looser than what the printer is rated for.
- Never scale or rotate a model. Only translate it to the centre of its plate
  with its lowest point at Z = 0.
- Convert numpy scalars with `float()` before formatting them into XML.
- A single input must keep producing the same package, byte for byte apart
  from the dates, unless the change is meant to alter it.

## 4. Git

- Remote `https://github.com/baonq-me/3d-print-tools.git`, branch `main`.
- One commit per change; the message says what changed.
- No co-author or tool attribution lines in commit messages.
- `stl/`, `3mf/`, `.venv/` and archives are never committed. Models from other
  authors carry their own licences and stay out of the repository.
- No access tokens, machine paths or account names in files or messages.

## 5. Documentation duties

| When you change… | also update |
|---|---|
| command-line options or output names | [usage.md](usage.md), the README quick start |
| a profile or a stock snapshot | [profiles.md](profiles.md) |
| what goes into the `.3mf` | [project-format.md](project-format.md) |
| folders or these rules | this file and [repository.md](repository.md) |
| anything | today's `changelog/YYYY-MM-DD.md` |

## 6. Verifying before "done"

1. Convert a known model with every profile and both materials; the script
   must print no warning for a watertight model that fits the bed.
2. Run the checks in [project-format.md](project-format.md#checking-a-generated-file-without-the-slicer).
3. For a change that should not alter the output, compare the new package
   with one made before the change.
4. The final proof is manual: open the file in Creality Print, confirm the
   preset names, slice.
