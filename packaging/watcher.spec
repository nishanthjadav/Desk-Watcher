# PyInstaller spec for the watcher sidecar.
#
# `onedir` (not `onefile`): mediapipe and torch both dynamically discover
# native shared libraries at runtime via ctypes / dlopen. `onefile` unpacks
# to a temp dir on each launch and the discovery logic sometimes trips
# over it. `onedir` produces a plain folder-of-DLLs that behaves like a
# normal Python install, which is what the ML deps expect.
#
# Tauri consumes the built `dist/watcher/watcher.exe` as a sidecar, and
# `dist/watcher/` (with its DLL siblings) gets bundled into the MSI as
# a resource. See tauri/src-tauri/tauri.conf.json for the wiring.

# ruff: noqa
# type: ignore

import os
from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

BACKEND_DIR = os.path.abspath(os.path.join(SPECPATH, "..", "backend"))
MODELS_DIR = os.path.join(BACKEND_DIR, "models")

# mediapipe: bundled .tflite / .binarypb assets live under mediapipe/modules
# and are loaded relative to the package dir at runtime.
mp_datas = collect_data_files("mediapipe")

# ultralytics: does string-based imports of nn / models submodules.
ultra_submods = collect_submodules("ultralytics")
ultra_datas = collect_data_files("ultralytics")

# torch: ctypes-loaded DLLs + JIT trace data + dispatcher registration files.
torch_bins = collect_dynamic_libs("torch")
torch_datas = collect_data_files("torch")

# Ship our own model weights alongside so a first-run install has
# everything it needs without a network call. The Rust supervisor's
# first-run step copies these to %USERPROFILE%\.desk-watcher\models\
# but the watcher itself resolves them via sys._MEIPASS/models/ anyway
# — see backend/config.py _resource_dir().
own_datas = [
    (os.path.join(MODELS_DIR, "activity_classifier.pkl"), "models"),
    (os.path.join(MODELS_DIR, "pose_landmarker_lite.task"), "models"),
    (os.path.join(MODELS_DIR, "yolov8n.pt"), "models"),
]

hidden = [
    "mediapipe.tasks.python.vision.pose_landmarker",
    "mediapipe.tasks.python.core.base_options",
    "sklearn.utils._cython_blas",
    "sklearn.neighbors._typedefs",
    "sklearn.utils._weight_vector",
] + ultra_submods

a = Analysis(
    [os.path.join(BACKEND_DIR, "watcher.py")],
    pathex=[BACKEND_DIR],
    binaries=torch_bins,
    datas=mp_datas + ultra_datas + torch_datas + own_datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # These are dev/notebook deps we don't need at runtime and they
        # bloat the bundle if PyInstaller pulls them in transitively.
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
    name="watcher",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # keep a console for now so we see prints during dev builds
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
    name="watcher",
)
