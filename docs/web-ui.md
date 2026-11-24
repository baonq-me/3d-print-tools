# Web UI

[← README](../README.md)

A local web page for the converter: add STL files, choose material, profile,
temperatures, layer height, supports and brim, convert to a Creality Print
project, and optionally slice it to G-code with the real print time and a
layer preview. Design and decisions: `plans/plan_web_ui_stl_to_3mf.html`.

## Run

```sh
.venv/bin/pip install -r requirements.txt     # once: adds FastAPI, Uvicorn, python-multipart
.venv/bin/python web/app.py                   # http://127.0.0.1:8000
.venv/bin/python web/app.py --port 8100 --open
```

The server listens on `127.0.0.1` only and refuses requests whose `Host` is
not `127.0.0.1` / `localhost`, and cross-site form posts. Stop it with Ctrl+C.

## Where files are saved

The page follows the same folder rules as the command line:

| File | Saved to | Name |
|---|---|---|
| Uploaded STL | `stl/` | original name; a folder upload keeps its folder, e.g. `stl/ecs_4970054/40_08_1x.stl` |
| Project | `3mf/` | the converter's default name, including the variant part (see [usage.md](usage.md#output-files)) |
| G-code | `gcode/` | the project name with `.gcode`; `_plate<n>` per plate for several plates |

- An existing file with **different** contents is never replaced silently: the
  page asks to replace it, keep both (`name (2).ext`), or use the saved one.
- An existing file with the **same** contents is reused without asking
  (projects and G-code count as the same when only their date stamps differ).
- Only `stl/`, `3mf/` and `gcode/` are written. File names are cleaned so an
  upload cannot write outside them. Slicer work files go to the system temp
  folder and are deleted afterwards.
- The left column lists what is already in `stl/`; click a file to add it
  without uploading again.

## Using it

1. **Add files.** Drop STL files or a folder anywhere on the page, or use
   "browse". Each file is checked at once: size, volume, watertight, fits the
   220 x 220 x 250 mm bed, and whether its largest flat face is tilted (the
   cause of the failed foot-nap prints). Several files make one project with
   one plate each; reorder with the arrows or by dragging.
2. **Settings.** Material and profile fill in the temperatures and layer
   height; a changed field shows a dot and a "reset" link. Supports (tree or
   normal, overhang angle) and brim (width) are switches. "Advanced settings"
   takes any slicer key, like the command line's `--set`.
3. **Convert** writes the project. **Convert & slice** also runs the Creality
   Print command line (the app's window must be closed) and shows print time,
   filament, layer count, a check that the G-code uses the settings the
   project asked for, and the layer preview.
4. **Layer preview.** "Layer" shows one layer from above with the layers
   below it dimmed. "3D" shows every toolpath up to the slider's layer, with
   the top layer in full colour and earlier layers darker: drag to rotate,
   scroll to zoom, right-drag or Shift-drag to pan. Click a legend entry to
   hide a path type (supports, for example) in both views.

The page and the command line produce identical projects (apart from date
stamps) with identical names for the same options.

| Shortcut | Action |
|---|---|
| `Ctrl/⌘ O` | add STL files |
| `Ctrl/⌘ Enter` | convert |
| `Ctrl/⌘ Shift Enter` | convert & slice |
| `Ctrl/⌘ S` | download the G-code (or the 3MF if not sliced) |
| `Delete` | remove the selected file (undo for 5 s) |
| `?` | list of shortcuts |

## How it is built

- `web/app.py` — FastAPI server. Imports `converter/src` directly and calls the
  same `convert()` as the command line. One slicing job at a time, in a worker
  thread; slicing runs plate by plate so the page can show progress.
- `web/static/index.html`, `app.css`, `app.js` — the page: plain HTML, CSS and
  an ES module, no build step. Dark theme by default, light theme from the top
  bar (remembered in the browser).
- `web/static/vendor/three-0.160.0/` — three.js 0.160.0 (MIT) with its orbit
  controls and STL loader, copied in so the page works offline. Used for the
  model view and the 3D toolpath view; the rest of the page works without
  WebGL.

| Endpoint | Purpose |
|---|---|
| `GET /api/options` | profiles with their defaults per material, limits, setting keys, slicer status |
| `GET /api/slicer` | is Creality Print installed / is its window open |
| `GET /api/library` | files in `stl/`, `3mf/`, `gcode/` with sizes and dates |
| `POST /api/files` | upload one STL (`file`, optional `relpath`, `on_conflict`); returns the mesh checks, or 409 with the conflict |
| `POST /api/inspect` | mesh checks for a file already in `stl/` |
| `POST /api/sample` | copy `samples/3DBenchy.stl` into `stl/` |
| `POST /api/convert` | files + options → project in `3mf/`; 409 with a token on a name conflict |
| `POST /api/convert/resolve` | answer a conversion conflict: `replace`, `keep_both`, `use_saved` |
| `POST /api/slice` | start slicing a project; returns a job |
| `GET /api/jobs/{id}` | job progress and results; `POST …/cancel`, `POST …/resolve` |
| `GET /api/gcode/meta`, `GET /api/gcode/layer` | layer count, bounding box, and one layer's toolpaths |
| `GET /api/gcode/toolpaths` | every extrusion segment per path type with per-layer counts, for the 3D view (gzip-compressed; about 1.7 MB for a 318 000-segment print) |
| `GET /api/file`, `GET /api/thumb` | send a saved file or a plate thumbnail |
| `POST /api/open` | open `stl/`, `3mf/` or `gcode/` in the file manager |

## Limitations

- Slicing needs Creality Print installed and its window closed. It was tested
  on macOS with 7.3.1; on Windows the "window open" check cannot tell the app
  from a command-line run.
- The 3D view shows the part as placed on its plate; it does not rotate or
  arrange parts, by the project's rules.
- Nothing is deleted automatically; `stl/`, `3mf/` and `gcode/` grow until you
  clean them. The page shows their sizes.
