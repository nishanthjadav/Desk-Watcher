import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

BACKEND_DIR = os.path.abspath(os.path.join(SPECPATH, "..", "backend"))

hidden = [
    "sqlalchemy",
    "sqlalchemy.sql.default_comparator",
    "psycopg2",
    "dotenv",
]

hidden += collect_submodules("fastapi")
hidden += collect_submodules("uvicorn")
hidden += collect_submodules("starlette")
hidden += collect_submodules("sqlalchemy")

datas = []
datas += collect_data_files("fastapi")
datas += collect_data_files("uvicorn")


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
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="api",
)