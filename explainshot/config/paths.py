"""Filesystem locations the app writes to. All resolved from %APPDATA%/ExplainShot on Windows."""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

from .. import APP_NAME


@lru_cache(maxsize=1)
def data_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        root = Path(base) / APP_NAME
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        root = Path(base) / APP_NAME.lower()
    root.mkdir(parents=True, exist_ok=True)
    return root


def screenshots_dir() -> Path:
    d = data_dir() / "screenshots"
    d.mkdir(parents=True, exist_ok=True)
    return d


def database_path() -> Path:
    return data_dir() / "explainshot.db"


def logs_dir() -> Path:
    d = data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def resources_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2])) / "resources"
    return Path(__file__).resolve().parents[2] / "resources"


def lock_path() -> Path:
    return data_dir() / ".instance.lock"
