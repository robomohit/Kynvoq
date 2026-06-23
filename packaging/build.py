"""Build the standalone Orynn payload with PyInstaller, then zip it for a GitHub
release. The tiny online installer (orynn_online_setup.iss) downloads + extracts
this zip on the user's machine.

Usage (from the repo root, in the project venv):
    python packaging/build.py

Output:
    dist/Orynn/Orynn.exe          one-folder frozen app (the overlay re-enters via
                                  Orynn.exe --overlay, handled in run_desktop.py)
    dist/Orynn-win64.zip          the payload the installer pulls

NOTE: PyInstaller for a big PySide6 + win32 + FastAPI app almost always needs a
round or two of "ModuleNotFoundError -> add to COLLECT" the first time. This script
front-loads the usual suspects; add any that still slip through to COLLECT below.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = "Orynn"

# Packages whose submodules/data PyInstaller's static analysis tends to miss.
COLLECT = [
    "google", "google.genai", "uvicorn", "fastapi", "starlette", "anyio",
    "uiautomation", "comtypes", "mss", "keyboard", "sounddevice", "pydantic",
    "pydantic_core", "httpx", "httpcore", "dotenv", "PIL", "psutil",
]
HIDDEN = [
    "win32gui", "win32api", "win32con", "win32process", "win32ui", "win32com",
    "win32com.client", "pythoncom", "pywintypes", "numpy",
]
# We use PySide6. Other Qt bindings (pulled in transitively by cv2/pyautogui) make
# PyInstaller abort — "multiple Qt bindings". Exclude them + dev-only baggage.
EXCLUDE = [
    "PyQt5", "PyQt6", "PySide2", "tkinter", "_tkinter", "matplotlib", "pytest", "cv2",
]


def main() -> int:
    dist = ROOT / "dist"
    build = ROOT / "build"
    for d in (dist, build):
        shutil.rmtree(d, ignore_errors=True)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--name", NAME,
        "--windowed",                 # no console window
        "--noupx",
        "--distpath", str(dist),
        "--workpath", str(build),
        "--specpath", str(build),
    ]
    for pkg in COLLECT:
        cmd += ["--collect-all", pkg]
    for mod in HIDDEN:
        cmd += ["--hidden-import", mod]
    for mod in EXCLUDE:
        cmd += ["--exclude-module", mod]
    # ship the example env + any runtime assets next to the exe
    env_example = ROOT / ".env.example"
    if env_example.exists():
        cmd += ["--add-data", f"{env_example};."]
    assets = ROOT / "app" / "assets"
    if assets.exists():
        cmd += ["--add-data", f"{assets};app/assets"]
    static_dir = ROOT / "static"
    if static_dir.exists():
        cmd += ["--add-data", f"{static_dir};static"]
    cmd += [str(ROOT / "run_desktop.py")]

    print("Running:", " ".join(cmd), flush=True)
    rc = subprocess.call(cmd, cwd=str(ROOT))
    if rc != 0:
        print(f"\nPyInstaller failed (exit {rc}). Add any missing module to COLLECT/"
              "HIDDEN above and re-run.", file=sys.stderr)
        return rc

    app_dir = dist / NAME
    if not (app_dir / f"{NAME}.exe").exists():
        print("Build finished but Orynn.exe is missing — check the PyInstaller log.",
              file=sys.stderr)
        return 1

    zip_path = dist / f"{NAME}-win64.zip"
    print(f"Zipping {app_dir} -> {zip_path}", flush=True)
    # Zip the CONTENTS of dist/Orynn/ (Orynn.exe at the zip root) so the installer can
    # extract straight into the install dir.
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in app_dir.rglob("*"):
            z.write(f, f.relative_to(app_dir))
    print(f"\nDone. Upload {zip_path.name} to a GitHub release, then point the "
          "installer's PayloadUrl at it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
