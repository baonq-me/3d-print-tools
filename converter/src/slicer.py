"""Run Creality Print's hidden command line to slice a project into G-code.

    CrealityPrint --cli --slice <plate> --need-gcode-file --outputdir <dir>/ project.3mf

writes <dir>/plate_<plate>.gcode. The command line shares its configuration with
the app, so it must not run while the Creality Print window is open. The log
marks ordinary lines as [error]; success is exit code 0 plus the G-code file.
Tested on macOS with Creality Print 7.3.1.
"""
import glob
import os
import plistlib
import re
import subprocess
import sys

ENV_VAR = "CREALITY_PRINT"   # full path to the executable, overrides the search


class SlicerError(Exception):
    pass


def _version_key(path):
    return [int(n) for n in re.findall(r"\d+", path)]


def candidates():
    home = os.path.expanduser("~")
    if sys.platform == "darwin":
        pats = [os.path.join(root, "Creality Print*.app", "Contents", "MacOS", "CrealityPrint")
                for root in ("/Applications", os.path.join(home, "Applications"))]
    elif sys.platform == "win32":
        roots = [os.environ.get(k) for k in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")]
        pats = [os.path.join(r, "Creality", "Creality Print*", "CrealityPrint.exe") for r in roots if r]
    else:
        pats = ["/usr/bin/CrealityPrint", "/usr/local/bin/CrealityPrint",
                "/opt/CrealityPrint*/CrealityPrint", "/opt/Creality Print*/CrealityPrint",
                os.path.join(home, "Applications", "CrealityPrint*.AppImage")]
    found = [p for pat in pats for p in glob.glob(pat) if os.path.isfile(p)]
    return sorted(found, key=_version_key, reverse=True)


def find_executable():
    path = os.environ.get(ENV_VAR)
    if path:
        return path if os.path.isfile(path) else None
    found = candidates()
    return found[0] if found else None


def app_version(exe):
    """Version of the installed app, where the OS makes it easy to read."""
    if exe and sys.platform == "darwin":
        plist = os.path.join(os.path.dirname(os.path.dirname(exe)), "Info.plist")
        try:
            with open(plist, "rb") as f:
                info = plistlib.load(f)
            return info.get("CFBundleShortVersionString") or info.get("CFBundleVersion")
        except (OSError, plistlib.InvalidFileException):
            return None
    return None


def gui_running(exe=None):
    """True when the Creality Print window (not a --cli run) is open."""
    name = os.path.basename(exe) if exe else ("CrealityPrint.exe" if sys.platform == "win32" else "CrealityPrint")
    try:
        if sys.platform == "win32":
            out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {name}", "/FO", "CSV", "/NH"],
                                 capture_output=True, text=True, timeout=10).stdout
            return name.lower() in out.lower()   # cannot tell a --cli run apart here
        # comm = executable path only, so other programs that merely mention the name do not match
        out = subprocess.run(["ps", "-axo", "pid=,comm="], capture_output=True, text=True, timeout=10).stdout
        pids = [line.split(None, 1)[0] for line in out.splitlines()
                if len(line.split(None, 1)) == 2 and os.path.basename(line.split(None, 1)[1].strip()) == name]
        for pid in pids:
            args = subprocess.run(["ps", "-o", "args=", "-p", pid], capture_output=True, text=True,
                                  timeout=10).stdout
            if args.strip() and "--cli" not in args:
                return True
    except (OSError, subprocess.SubprocessError):
        return False
    return False


def slice_plate(project, workdir, plate=1, exe=None, timeout=600, on_start=None):
    """Slice one plate; return the path of the G-code inside workdir.

    on_start(process) is called once the slicer runs, so a caller can cancel it.
    """
    exe = exe or find_executable()
    if not exe:
        raise SlicerError("Creality Print was not found; set CREALITY_PRINT to its executable")
    os.makedirs(workdir, exist_ok=True)
    out = os.path.join(workdir, f"plate_{plate}.gcode")
    if os.path.exists(out):
        os.remove(out)
    cmd = [exe, "--cli", "--slice", str(plate), "--need-gcode-file",
           "--outputdir", workdir.rstrip(os.sep) + os.sep, os.path.abspath(project)]
    # cwd=workdir: the slicer drops a result.json in its working directory
    proc = subprocess.Popen(cmd, cwd=workdir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            errors="replace")
    if on_start:
        on_start(proc)
    try:
        log, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise SlicerError(f"slicing plate {plate} took longer than {timeout} s and was stopped")
    if proc.returncode != 0 or not os.path.exists(out):
        if proc.returncode is not None and proc.returncode < 0:
            raise SlicerError("slicing was cancelled")
        lines = [l.split("] ", 2)[-1] for l in (log or "").splitlines() if l.strip()]
        useful = [l for l in lines if any(w in l.lower() for w in ("fail", "invalid", "not ", "error code"))]
        detail = "; ".join((useful or lines)[-3:])
        raise SlicerError(f"Creality Print could not slice plate {plate} (exit {proc.returncode}): {detail}")
    return out


def gcode_names(project_path, plates):
    """G-code file names for a project: <stem>.gcode, or <stem>_plate<n>.gcode per plate."""
    stem = os.path.splitext(os.path.basename(project_path))[0]
    if plates == 1:
        return {1: stem + ".gcode"}
    return {n: f"{stem}_plate{n}.gcode" for n in range(1, plates + 1)}
