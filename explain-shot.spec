# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for ExplainShot."""

import os
from pathlib import Path

project_root = Path(os.getcwd())

APP_NAME = "ExplainShot"

a = Analysis(
    ["main.py"],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        (str(project_root / "resources"), "resources"),
    ],
    hiddenimports=[
        "PyQt6.sip",
        "PyQt6.QtCore",
        "PyQt6.QtGui",
        "PyQt6.QtWidgets",
        "PIL",
        "PIL.Image",
        "PIL.ImageGrab",
        "pynput",
        "pynput.keyboard",
        "qasync",
        "httpx",
        "sqlite3",
    ],
    excludes=[
        "matplotlib",
        "numpy",
        "scipy",
        "pandas",
        # legacy dependencies from the pre-rewrite build — force PyInstaller
        # not to look for them if a stale venv still has them installed.
        "ollama",
        "pystray",
        "aiosqlite",
        "aiofiles",
        "psutil",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    name=APP_NAME,
    debug=False,
    strip=False,
    upx=True,
    console=False,
    icon=str(project_root / "resources" / "icons" / "app.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    name=APP_NAME,
)
