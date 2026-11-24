#!/usr/bin/env python3
"""Local web UI for the STL to 3MF converter.

    .venv/bin/python web/app.py            # http://127.0.0.1:8000
    .venv/bin/python web/app.py --port 8100 --open

Listens on 127.0.0.1 only. Files are saved in the repository folders, as the
command line does: uploaded STL in stl/, projects in 3mf/, G-code in gcode/.
An existing file with different contents is never replaced without asking.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import webbrowser
import zipfile
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "converter"))

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from starlette.middleware.gzip import GZipMiddleware  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from src import slicer  # noqa: E402
from src.config import (BED_MAX_C, GCODE_DIR, GENERIC_DIRS, HOTEND_MAX_C, MATERIALS, MAX_PLATES,  # noqa: E402
                        OUTPUT_DIR, STL_DIR)
from src.gcode import check_settings, parse_layers, read_header  # noqa: E402
from src.inspect import inspect  # noqa: E402
from src.mesh import read_stl  # noqa: E402
from src.naming import output_name, stem_for_inputs  # noqa: E402
from src.package import convert  # noqa: E402
from src.settings import list_profiles, load_profile, profile_deltas, stock_path  # noqa: E402

FOLDERS = {"stl": STL_DIR, "3mf": OUTPUT_DIR, "gcode": GCODE_DIR}
EXTENSIONS = {"stl": ".stl", "3mf": ".3mf", "gcode": ".gcode"}
MAX_UPLOAD_MB = 200
ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
PENDING_TTL_S = 3600
SAMPLE = os.path.join(ROOT, "samples", "3DBenchy.stl")

app = FastAPI(title="3d-print-tools", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(GZipMiddleware, minimum_size=2000)   # toolpath JSON compresses well
worker = ThreadPoolExecutor(max_workers=1)   # one slicer run at a time
lock = threading.Lock()
jobs: Dict[str, dict] = {}
pending: Dict[str, dict] = {}                # converted projects waiting for a name-conflict answer
layer_cache: "OrderedDict[tuple, dict]" = OrderedDict()
inspect_cache: Dict[tuple, dict] = {}


# ------------------------------------------------------------------ helpers --
def fail(status, message, **extra):
    raise HTTPException(status_code=status, detail={"message": message, **extra})


@app.middleware("http")
async def local_only(request: Request, call_next):
    """Refuse requests that do not come from this machine's browser (DNS rebinding, other sites)."""
    host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]")
    if host not in ALLOWED_HOSTS:
        return JSONResponse({"detail": {"message": "only local requests are served"}}, status_code=403)
    if request.method not in ("GET", "HEAD"):
        origin = request.headers.get("origin")
        if origin and urlparse(origin).hostname not in ALLOWED_HOSTS:
            return JSONResponse({"detail": {"message": "cross-site request refused"}}, status_code=403)
    return await call_next(request)


_BAD = re.compile(r'[\x00-\x1f<>:"/\\|?*]')


def clean_part(part):
    part = _BAD.sub("_", part).strip().strip(".")
    if not part or part in (".", ".."):
        return None
    return part[:150]


def resolve(rel, folder=None):
    """'stl/a/b.stl' -> absolute path inside that folder; refuses anything outside it."""
    parts = [p for p in re.split(r"[\\/]+", rel or "") if p]
    if not parts or parts[0] not in FOLDERS or (folder and parts[0] != folder):
        fail(400, f"not a file in {folder or 'stl/, 3mf/ or gcode/'}: {rel}")
    if any(p in (".", "..") for p in parts[1:]) or len(parts) < 2:
        fail(400, f"invalid path: {rel}")
    base = os.path.realpath(FOLDERS[parts[0]])
    path = os.path.realpath(os.path.join(base, *parts[1:]))
    if os.path.commonpath([base, path]) != base:
        fail(400, f"invalid path: {rel}")
    return parts[0], path


def rel_of(path):
    path = os.path.realpath(path)
    for key, base in FOLDERS.items():
        base = os.path.realpath(base)
        if os.path.commonpath([base, path]) == base:
            return key + "/" + os.path.relpath(path, base).replace(os.sep, "/")
    raise ValueError(path)


def file_item(path):
    st = os.stat(path)
    return {"path": rel_of(path), "name": os.path.basename(path), "size": st.st_size, "mtime": st.st_mtime}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def keep_both_name(path):
    stem, ext = os.path.splitext(path)
    n = 2
    while os.path.exists(f"{stem} ({n}){ext}"):
        n += 1
    return f"{stem} ({n}){ext}"


_DATE = re.compile(rb"20\d\d-\d\d-\d\d")


def same_project(a, b):
    """Two .3mf files that differ only in their date stamps count as the same."""
    try:
        with zipfile.ZipFile(a) as za, zipfile.ZipFile(b) as zb:
            if za.namelist() != zb.namelist():
                return False
            return all(_DATE.sub(b"D", za.read(n)) == _DATE.sub(b"D", zb.read(n)) for n in za.namelist())
    except (OSError, zipfile.BadZipFile):
        return False


_GCODE_STAMP = (b"; generated by", b"; creality_uuid")
_OBJECT_ID = re.compile(rb" id:\d+")


def same_gcode(a, b):
    """Two G-code files that differ only in the slicer's time stamp, UUID and random
    object ids count as the same."""
    def norm(line):
        if line.startswith(_GCODE_STAMP):
            return line[:16]
        if line.startswith((b"; printing object", b"; stop printing object")):
            return _OBJECT_ID.sub(b"", line)
        return line
    try:
        with open(a, "rb") as fa, open(b, "rb") as fb:
            for la, lb in zip(fa, fb):
                if la != lb and norm(la) != norm(lb):
                    return False
            return fa.read(1) == b"" and fb.read(1) == b""
    except OSError:
        return False


def conflict_info(dest, new_path):
    st = os.stat(dest)
    return {"path": rel_of(dest), "existing": {"size": st.st_size, "mtime": st.st_mtime},
            "new": {"size": os.path.getsize(new_path)}}


def place(tmp, dest, action, same):
    """Move tmp to dest following the conflict action; return the final path."""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if not os.path.exists(dest) or same or action == "replace":
        os.replace(tmp, dest)
        return dest
    if action == "keep_both":
        final = keep_both_name(dest)
        os.replace(tmp, final)
        return final
    if action == "use_saved":
        os.remove(tmp)
        return dest
    raise ValueError(action)


def check_mesh(path):
    st = os.stat(path)
    key = (path, st.st_mtime, st.st_size)
    if key not in inspect_cache:
        inspect_cache[key] = inspect(path)
    return inspect_cache[key]


def stl_entry(path, reused=False):
    item = file_item(path)
    try:
        item["check"] = check_mesh(path)
    except Exception as e:   # noqa: BLE001 - shown to the user as a file problem
        item["check"] = None
        item["error"] = f"cannot read this STL: {e}"
    item["reused"] = reused
    return item


def cleanup_pending():
    now = time.time()
    for token in [t for t, p in pending.items() if now - p["created"] > PENDING_TTL_S]:
        shutil.rmtree(pending.pop(token)["tmpdir"], ignore_errors=True)
    for job in jobs.values():   # slicing jobs left waiting for a conflict answer
        if job["state"] == "conflict" and now - job["started"] > PENDING_TTL_S:
            shutil.rmtree(job["tmpdir"], ignore_errors=True)
            job.update(state="cancelled", error="the question about the G-code name expired")


def first_value(v):
    return v[0] if isinstance(v, list) else v


# ----------------------------------------------------------------- options --
@app.get("/api/options")
def options():
    profiles = []
    keys = set()
    limits = {}
    printer = None
    for material in MATERIALS:
        stock = json.load(open(stock_path(material)))
        s = stock["settings"]
        printer = stock["presets"]["machine"]
        keys.update(k for g in stock["groups"].values() for k in g)
        limits[material] = {
            "nozzle_range": [int(first_value(s["nozzle_temperature_range_low"])),
                             int(first_value(s["nozzle_temperature_range_high"]))],
            "layer_height": [float(first_value(s["min_layer_height"])), float(first_value(s["max_layer_height"]))],
            "filament": stock["presets"]["filament"],
        }
    order = {"quality": 0, "fast": 1, "hf_fast": 2}
    for name in sorted(list_profiles(), key=lambda n: (order.get(n, 9), n)):
        p = load_profile(name)
        defaults = {}
        for material in MATERIALS:
            s = json.load(open(stock_path(material)))["settings"]
            d = profile_deltas(p, material)

            def pick(key, group):
                return float(first_value(d[group].get(key, s[key])))

            defaults[material] = {
                "layer_height": pick("layer_height", "process"),
                "nozzle_first": pick("nozzle_temperature_initial_layer", "filament"),
                "nozzle_other": pick("nozzle_temperature", "filament"),
                "bed": pick("hot_plate_temp", "filament"),
                "support_threshold_angle": pick("support_threshold_angle", "process"),
                "brim_width": pick("brim_width", "process"),
            }
        profiles.append({"name": name, "description": p.get("description", ""), "defaults": defaults})
    exe = slicer.find_executable()
    return {
        "printer": printer,
        "bed_mm": [220, 220, 250],
        "materials": [{"name": m, "colour": c} for m, c in MATERIALS.items()],
        "profiles": profiles,
        "limits": {"hotend_max": HOTEND_MAX_C, "bed_max": BED_MAX_C, "nozzle_min": 150, "max_plates": MAX_PLATES,
                   "max_upload_mb": MAX_UPLOAD_MB, "per_material": limits},
        "setting_keys": sorted(keys),
        "slicer": {"available": bool(exe), "version": slicer.app_version(exe),
                   "gui_running": bool(exe) and slicer.gui_running(exe)},
    }


@app.get("/api/slicer")
def slicer_status():
    exe = slicer.find_executable()
    return {"available": bool(exe), "gui_running": bool(exe) and slicer.gui_running(exe)}


# ----------------------------------------------------------------- library --
@app.get("/api/library")
def library():
    out = {}
    for key, base in FOLDERS.items():
        items = []
        if os.path.isdir(base):
            for dirpath, dirnames, filenames in os.walk(base):
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                for f in filenames:
                    if f.lower().endswith(EXTENSIONS[key]) and not f.startswith("."):
                        items.append(file_item(os.path.join(dirpath, f)))
        items.sort(key=lambda i: -i["mtime"])
        out[key] = {"files": items, "total_bytes": sum(i["size"] for i in items)}
    return out


@app.get("/api/file")
def get_file(path: str, download: int = 0):
    key, p = resolve(path)
    if not os.path.isfile(p):
        fail(404, f"not found: {path}")
    media = {"stl": "model/stl", "3mf": "model/3mf", "gcode": "text/x.gcode"}[key]
    if download:
        return FileResponse(p, media_type=media, filename=os.path.basename(p))
    return FileResponse(p, media_type=media)


@app.get("/api/thumb")
def thumb(path: str, plate: int = 1):
    _, p = resolve(path, "3mf")
    try:
        with zipfile.ZipFile(p) as z:
            data = z.read(f"Metadata/plate_{int(plate)}.png")
    except (OSError, KeyError, zipfile.BadZipFile):
        fail(404, "no thumbnail")
    return Response(data, media_type="image/png")


class OpenReq(BaseModel):
    folder: str


@app.post("/api/open")
def open_folder(req: OpenReq):
    if req.folder not in FOLDERS:
        fail(400, "unknown folder")
    path = FOLDERS[req.folder]
    os.makedirs(path, exist_ok=True)
    cmd = {"darwin": ["open"], "win32": ["explorer"]}.get(sys.platform, ["xdg-open"])
    try:
        subprocess.Popen(cmd + [path])
    except OSError as e:
        fail(500, f"cannot open the folder: {e}")
    return {"ok": True}


# ------------------------------------------------------------------- files --
def save_stl(tmp, parts, action):
    """Place an uploaded STL (already validated) at stl/<parts>; returns (path, reused) or a conflict."""
    dest = os.path.join(STL_DIR, *parts)
    if os.path.exists(dest):
        if sha256(dest) == sha256(tmp):
            os.remove(tmp)
            return dest, True, None
        if action == "ask":
            info = conflict_info(dest, tmp)
            os.remove(tmp)
            return None, False, info
    final = place(tmp, dest, action, same=False)
    return final, action == "use_saved", None


@app.post("/api/files")
def upload(file: UploadFile = File(...), relpath: Optional[str] = Form(None), on_conflict: str = Form("ask")):
    if on_conflict not in ("ask", "replace", "keep_both", "use_saved"):
        fail(400, "on_conflict must be ask, replace, keep_both or use_saved")
    name = relpath or file.filename or ""
    parts = [clean_part(p) for p in re.split(r"[\\/]+", name) if p.strip()]
    if not parts or None in parts or len(parts) > 4:
        fail(400, f"invalid file name: {name}")
    if not parts[-1].lower().endswith(".stl"):
        fail(400, "Not an STL file", code="not_stl", name=parts[-1])
    os.makedirs(STL_DIR, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".upload-", suffix=".part", dir=STL_DIR)
    size = 0
    try:
        with os.fdopen(fd, "wb") as out:
            while True:
                chunk = file.file.read(1 << 20)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_UPLOAD_MB << 20:
                    fail(413, f"larger than {MAX_UPLOAD_MB} MB", code="too_large", name=parts[-1])
                out.write(chunk)
        try:
            read_stl(tmp)
        except Exception:   # noqa: BLE001
            fail(400, "Not a valid STL file", code="not_stl", name=parts[-1])
        path, reused, conflict = save_stl(tmp, parts, on_conflict)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    if conflict:
        return JSONResponse({"conflict": conflict}, status_code=409)
    return stl_entry(path, reused)


class PathReq(BaseModel):
    path: str


@app.post("/api/inspect")
def inspect_file(req: PathReq):
    _, p = resolve(req.path, "stl")
    if not os.path.isfile(p):
        fail(404, f"not found: {req.path}")
    return stl_entry(p, reused=True)


@app.post("/api/sample")
def add_sample():
    os.makedirs(STL_DIR, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".upload-", suffix=".part", dir=STL_DIR)
    os.close(fd)
    shutil.copyfile(SAMPLE, tmp)
    path, reused, _ = save_stl(tmp, ["3DBenchy.stl"], "keep_both")
    return stl_entry(path, reused)


# ----------------------------------------------------------------- convert --
class ConvertReq(BaseModel):
    files: List[str]
    material: str = "pla"
    profile: str = "quality"
    nozzle_first: Optional[int] = None
    nozzle_other: Optional[int] = None
    bed: Optional[int] = None
    layer_height: Optional[float] = None
    support: bool = False
    extra: Dict[str, str] = {}
    on_conflict: str = "ask"


def project_stem(paths):
    """Same rule as the command line (naming.stem_for_inputs): the folder name only when the
    selection is every STL in one folder, else '<stl name>' or '<first>_and_<n>_more'."""
    if len(paths) > 1:
        folder = os.path.dirname(paths[0])
        if all(os.path.dirname(p) == folder for p in paths) and os.path.realpath(folder) != os.path.realpath(STL_DIR):
            in_folder = {f for f in os.listdir(folder) if f.lower().endswith(".stl")}
            if {os.path.basename(p) for p in paths} == in_folder:
                return stem_for_inputs([folder], len(paths))
    return stem_for_inputs(paths, len(paths))


def project_response(path, result=None, reused=False):
    item = file_item(path)
    with zipfile.ZipFile(path) as z:
        plates = sum(1 for n in z.namelist() if re.fullmatch(r"Metadata/plate_\d+\.json", n))
    item.update({"plates": plates, "reused_existing": reused,
                 "thumbs": [f"/api/thumb?path={item['path']}&plate={n}" for n in range(1, plates + 1)]})
    if result:
        item.update({"plate_info": result["plates"], "warnings": result["warnings"], "settings": result["settings"]})
    return item


@app.post("/api/convert")
def convert_files(req: ConvertReq):
    cleanup_pending()
    if not req.files:
        fail(400, "add at least one STL file")
    if len(req.files) > MAX_PLATES:
        fail(400, f"{len(req.files)} files, but a project holds at most {MAX_PLATES} plates")
    if req.material not in MATERIALS:
        fail(400, f"unknown material {req.material}")
    if req.profile not in list_profiles():
        fail(400, f"unknown profile {req.profile}")
    if req.on_conflict not in ("ask", "replace", "keep_both", "use_saved"):
        fail(400, "on_conflict must be ask, replace, keep_both or use_saved")
    paths = []
    for rel in req.files:
        _, p = resolve(rel, "stl")
        if not os.path.isfile(p):
            fail(404, f"not found: {rel}")
        paths.append(p)
    extra = {k.strip(): str(v).strip() for k, v in req.extra.items() if k.strip()}
    profile = load_profile(req.profile)
    name = output_name(project_stem(paths), req.material, req.profile, profile, req.layer_height, req.support, extra)
    dest = os.path.join(OUTPUT_DIR, name)
    tmpdir = tempfile.mkdtemp(prefix="3dpt_convert_")
    tmp = os.path.join(tmpdir, name)
    try:
        result = convert(paths, tmp, req.profile, req.material, req.nozzle_first, req.nozzle_other, req.bed,
                         req.layer_height, req.support, extra, verbose=False)
    except SystemExit as e:
        shutil.rmtree(tmpdir, ignore_errors=True)
        fail(400, str(e))
    except Exception as e:   # noqa: BLE001
        shutil.rmtree(tmpdir, ignore_errors=True)
        fail(500, f"conversion failed: {e}")
    same = os.path.exists(dest) and same_project(tmp, dest)
    if os.path.exists(dest) and not same and req.on_conflict == "ask":
        token = uuid.uuid4().hex
        pending[token] = {"tmpdir": tmpdir, "tmp": tmp, "dest": dest, "result": result, "created": time.time()}
        return JSONResponse({"conflict": conflict_info(dest, tmp), "token": token}, status_code=409)
    final = place(tmp, dest, req.on_conflict if req.on_conflict != "ask" else "replace", same)
    shutil.rmtree(tmpdir, ignore_errors=True)
    return project_response(final, result, reused=same or req.on_conflict == "use_saved")


class ResolveReq(BaseModel):
    token: str = ""
    action: str


@app.post("/api/convert/resolve")
def resolve_convert(req: ResolveReq):
    p = pending.pop(req.token, None)
    if not p:
        fail(404, "this question has expired; convert again")
    if req.action not in ("replace", "keep_both", "use_saved"):
        pending[req.token] = p
        fail(400, "action must be replace, keep_both or use_saved")
    final = place(p["tmp"], p["dest"], req.action, same=False)
    shutil.rmtree(p["tmpdir"], ignore_errors=True)
    return project_response(final, p["result"], reused=req.action == "use_saved")


# ------------------------------------------------------------------- slice --
class SliceReq(BaseModel):
    project: str
    on_conflict: str = "ask"


def expected_settings(project):
    with zipfile.ZipFile(project) as z:
        cfg = json.loads(z.read("Metadata/project_settings.config"))
    f = lambda k: float(first_value(cfg[k]))   # noqa: E731
    return {"layer_height": f("layer_height"), "first_layer_height": f("initial_layer_print_height"),
            "nozzle_first_c": f("nozzle_temperature_initial_layer"), "nozzle_other_c": f("nozzle_temperature"),
            "bed_c": f("hot_plate_temp"), "support": first_value(cfg["enable_support"]) == "1"}


def public(job):
    return {k: v for k, v in job.items() if k not in ("proc", "tmpdir", "pending_files", "project_abs")}


def finish_job(job, action):
    results = []
    for n, tmp, dest in job["pending_files"]:
        same = os.path.exists(dest) and same_gcode(tmp, dest)
        final = place(tmp, dest, action, same)
        h = read_header(final)
        results.append({"plate": n, "gcode": rel_of(final), "size": os.path.getsize(final),
                        "time_s": h["time_s"], "filament_m": h["filament_m"], "layers": h["layers"],
                        "max_z_mm": h["max_z_mm"], "generator": h["generator"],
                        "checks": check_settings(h, job["expected"])})
    shutil.rmtree(job["tmpdir"], ignore_errors=True)
    job.update(state="done", results=results, finished=time.time())
    job.pop("pending_files", None)


def run_job(job):
    try:
        job["state"] = "running"
        exe = slicer.find_executable()
        names = slicer.gcode_names(job["project_abs"], job["plates"])
        files = []
        for n in range(1, job["plates"] + 1):
            if job.get("cancel"):
                raise slicer.SlicerError("slicing was cancelled")
            job["plate"] = n
            gcode = slicer.slice_plate(job["project_abs"], os.path.join(job["tmpdir"], f"p{n}"), n, exe,
                                       on_start=lambda proc: job.__setitem__("proc", proc))
            job.pop("proc", None)
            files.append((n, gcode, os.path.join(GCODE_DIR, names[n])))
        if job.get("cancel"):
            raise slicer.SlicerError("slicing was cancelled")
        job["pending_files"] = files
        conflicts = [conflict_info(dest, tmp) for _, tmp, dest in files
                     if os.path.exists(dest) and not same_gcode(tmp, dest)]
        if conflicts and job["on_conflict"] == "ask":
            job.update(state="conflict", conflicts=conflicts)
            return
        finish_job(job, job["on_conflict"] if job["on_conflict"] != "ask" else "replace")
    except slicer.SlicerError as e:
        job.update(state="cancelled" if job.get("cancel") else "error", error=str(e), finished=time.time())
        shutil.rmtree(job["tmpdir"], ignore_errors=True)
    except Exception as e:   # noqa: BLE001
        job.update(state="error", error=f"slicing failed: {e}", finished=time.time())
        shutil.rmtree(job["tmpdir"], ignore_errors=True)


@app.post("/api/slice")
def start_slice(req: SliceReq):
    cleanup_pending()
    _, p = resolve(req.project, "3mf")
    if not os.path.isfile(p):
        fail(404, f"not found: {req.project}")
    exe = slicer.find_executable()
    if not exe:
        fail(409, "Creality Print was not found", code="slicer_missing")
    if slicer.gui_running(exe):
        fail(409, "Creality Print is open. Its command line shares the app's settings, so close the window "
                  "and try again.", code="slicer_open")
    with lock:
        if any(j["state"] in ("queued", "running") for j in jobs.values()):
            fail(409, "another slicing job is running", code="busy")
        with zipfile.ZipFile(p) as z:
            plates = sum(1 for n in z.namelist() if re.fullmatch(r"Metadata/plate_\d+\.json", n))
        job = {"id": uuid.uuid4().hex[:12], "state": "queued", "project": rel_of(p), "project_abs": p,
               "plates": plates, "plate": 0, "started": time.time(), "on_conflict": req.on_conflict,
               "expected": expected_settings(p), "tmpdir": tempfile.mkdtemp(prefix="3dpt_slice_")}
        jobs[job["id"]] = job
    worker.submit(run_job, job)
    return public(job)


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job = jobs.get(job_id) or fail(404, "unknown job")
    return public(job)


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    job = jobs.get(job_id) or fail(404, "unknown job")
    job["cancel"] = True
    proc = job.get("proc")
    if proc and proc.poll() is None:
        proc.kill()
    if job["state"] == "conflict":
        shutil.rmtree(job["tmpdir"], ignore_errors=True)
        job.update(state="cancelled", error="slicing was cancelled")
    return public(job)


@app.post("/api/jobs/{job_id}/resolve")
def resolve_job(job_id: str, req: ResolveReq):
    job = jobs.get(job_id) or fail(404, "unknown job")
    if job["state"] != "conflict":
        fail(400, "nothing to resolve")
    if req.action not in ("replace", "keep_both", "use_saved"):
        fail(400, "action must be replace, keep_both or use_saved")
    finish_job(job, req.action)
    return public(job)


# ------------------------------------------------------------------ layers --
def layers_of(path):
    st = os.stat(path)
    key = (path, st.st_mtime, st.st_size)
    if key in layer_cache:
        layer_cache.move_to_end(key)
        return layer_cache[key]
    layers = parse_layers(path)
    xs, ys = [], []
    for layer in layers:
        layer["paths"].pop("Custom", None)   # start G-code purge line, outside the bed
        for polys in layer["paths"].values():
            for poly in polys:
                xs += poly[0::2]
                ys += poly[1::2]
    data = {"layers": layers, "bbox": [min(xs), min(ys), max(xs), max(ys)] if xs else [0, 0, 220, 220]}
    layer_cache[key] = data
    while len(layer_cache) > 3:
        layer_cache.popitem(last=False)
    return data


@app.get("/api/gcode/meta")
def gcode_meta(path: str):
    _, p = resolve(path, "gcode")
    if not os.path.isfile(p):
        fail(404, f"not found: {path}")
    data = layers_of(p)
    types = sorted({t for layer in data["layers"] for t in layer["paths"]})
    return {"count": len(data["layers"]), "z": [layer["z"] for layer in data["layers"]], "bbox": data["bbox"],
            "types": types}


def toolpaths_of(data):
    """All extrusion segments per path type, for the 3D toolpath view.

    {type: {"pos": [x0,y0,z0, x1,y1,z1, ...] (pairs of points), "ends": [vertex count after layer i]}}
    """
    if "toolpaths" in data:
        return data["toolpaths"]
    layers = data["layers"]
    out = {}
    for i, layer in enumerate(layers):
        z = round(layer["z"] or 0.0, 3)
        for t, polys in layer["paths"].items():
            entry = out.setdefault(t, {"pos": [], "ends": [0] * len(layers)})
            pos = entry["pos"]
            for poly in polys:
                for k in range(0, len(poly) - 2, 2):
                    pos.extend((poly[k], poly[k + 1], z, poly[k + 2], poly[k + 3], z))
        for entry in out.values():
            entry["ends"][i] = len(entry["pos"]) // 3
    data["toolpaths"] = out
    return out


@app.get("/api/gcode/toolpaths")
def gcode_toolpaths(path: str):
    _, p = resolve(path, "gcode")
    if not os.path.isfile(p):
        fail(404, f"not found: {path}")
    data = layers_of(p)
    zs = [layer["z"] or 0.0 for layer in data["layers"]]
    return {"types": toolpaths_of(data), "z": zs, "bbox": data["bbox"], "max_z": max(zs) if zs else 0}


@app.get("/api/gcode/layer")
def gcode_layer(path: str, i: int):
    _, p = resolve(path, "gcode")
    data = layers_of(p)
    if not 0 <= i < len(data["layers"]):
        fail(404, "no such layer")
    return data["layers"][i]


# ------------------------------------------------------------------- pages --
app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")


FAVICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect width="24" height="24" rx="6" fill="#2563EB"/>'
           '<path d="M12 5 6 8.5v7l6 3.5 6-3.5v-7z M6 8.5l6 3.5 6-3.5M12 12v7" fill="none" stroke="#fff" stroke-width="1.6" '
           'stroke-linejoin="round"/></svg>')


@app.get("/favicon.svg")
def favicon():
    return Response(FAVICON, media_type="image/svg+xml")


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "static", "index.html"), headers={"Cache-Control": "no-cache"})


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--open", action="store_true", help="open the page in the default browser")
    a = ap.parse_args()
    import uvicorn
    url = f"http://127.0.0.1:{a.port}/"
    if a.open:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print(f"3d-print-tools web UI: {url}  (Ctrl+C to stop)")
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
