"""Prevent a second instance of the app from running.

Uses a file lock in the app data dir.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from ..config.paths import lock_path


class SingleInstance:
    def __init__(self) -> None:
        self._path: Path = lock_path()
        self._handle = None

    def acquire(self) -> bool:
        try:
            self._handle = open(self._path, "w")
        except OSError:
            return False
        if sys.platform == "win32":
            import msvcrt
            try:
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                self._handle.close()
                self._handle = None
                return False
        else:
            import fcntl
            try:
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                self._handle.close()
                self._handle = None
                return False
        self._handle.write(str(os.getpid()))
        self._handle.flush()
        return True

    def release(self) -> None:
        if not self._handle:
            return
        try:
            if sys.platform == "win32":
                import msvcrt
                try:
                    msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            self._handle.close()
        finally:
            self._handle = None
