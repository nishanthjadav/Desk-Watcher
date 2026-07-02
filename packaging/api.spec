# PyInstaller spec for the api sidecar.
#
# Entry point is backend/api_entry.py which imports the FastAPI app and
# runs uvicorn against it on 127.0.0.1:8765. See that file for why it
# exists (string-lookup import doesn't work when frozen).

# ruff: noqa
# type: ignore

import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

BACKEND_DIR = os.path.abspath(os.path.join(SPECPATH, "..", "backend"))

# uvicorn loads its lifespan / http / ws implementation modules by string,
# and FastAPI pulls in Pydantic v2's Rust core via a dynamic extension.
hidden = (
    collect_submodules("uvicorn")
    + collect_submodules("uvicorn.lifespan")
    + collect_submodules("uvicorn.protocols")
    + collect_submodules("uvicorn.loops")
    + [
        "starlette.routing",
        "pydantic",
        "pydantic_core",
    ]
)

datas = collect_data_files("uvicorn") + collect_data_files("fastapi")

a = Analysis(
    [os.path.join(BACKEND_DIR, "api_entry.py")],
    pathex=[BACKEND_DIR],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Same story as watcher.spec — the ML deps aren't needed for the
        # API-only sidecar. Excluding them cuts the api dist by ~90%.
        "torch",
        "torchvision",
        "mediapipe",
        "ultralytics",
        "cv2",
        "matplotlib",
        "IPython",
        "jupyter",
        "pytest",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="api",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="api",
)
