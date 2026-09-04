"""Thumbnail cache. LRU in memory, lazy on demand.

The old thumbnail_manager was 590 lines and juggled concurrent queues,
placeholder emissions, per-item state tracking, and settings for cache
size + quality + enabled flag — all for what is fundamentally
"scale down an image, remember it". This is that, minus the ceremony.
"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Callable

from PIL import Image
from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap


class _Signals(QObject):
    ready = pyqtSignal(str, QPixmap)   # screenshot_id, pixmap
    failed = pyqtSignal(str, str)      # screenshot_id, error


class _Task(QRunnable):
    def __init__(self, screenshot_id: str, path: str, size: int, signals: _Signals) -> None:
        super().__init__()
        self.screenshot_id = screenshot_id
        self.path = path
        self.size = size
        self.signals = signals

    def run(self) -> None:
        try:
            with Image.open(self.path) as image:
                image.thumbnail((self.size, self.size), Image.Resampling.LANCZOS)
                if image.mode != "RGBA":
                    image = image.convert("RGBA")
                qimg = QImage(
                    image.tobytes("raw", "RGBA"),
                    image.width,
                    image.height,
                    QImage.Format.Format_RGBA8888,
                )
                pixmap = QPixmap.fromImage(qimg.copy())
            self.signals.ready.emit(self.screenshot_id, pixmap)
        except Exception as exc:
            self.signals.failed.emit(self.screenshot_id, str(exc))


class ThumbnailCache(QObject):
    ready = pyqtSignal(str, QPixmap)
    failed = pyqtSignal(str, str)

    def __init__(self, size: int = 160, capacity: int = 256, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.size = size
        self.capacity = capacity
        self._cache: OrderedDict[str, QPixmap] = OrderedDict()
        self._pending: set[str] = set()

        self._signals = _Signals()
        self._signals.ready.connect(self._on_ready)
        self._signals.failed.connect(self._on_failed)

        self._pool = QThreadPool.globalInstance()

    # -- public API ------------------------------------------------------------

    def request(self, screenshot_id: str, path: str) -> QPixmap | None:
        """Return the cached pixmap synchronously if we already have one;
        otherwise return None and emit `ready` when the async decode finishes."""
        cached = self._cache.get(screenshot_id)
        if cached is not None:
            self._cache.move_to_end(screenshot_id)
            return cached
        if screenshot_id not in self._pending and Path(path).exists():
            self._pending.add(screenshot_id)
            self._pool.start(_Task(screenshot_id, path, self.size, self._signals))
        return None

    def evict(self, screenshot_id: str) -> None:
        self._cache.pop(screenshot_id, None)
        self._pending.discard(screenshot_id)

    def clear(self) -> None:
        self._cache.clear()
        self._pending.clear()

    def set_size(self, size: int) -> None:
        if size != self.size:
            self.size = size
            self.clear()

    # -- internal --------------------------------------------------------------

    def _on_ready(self, screenshot_id: str, pixmap: QPixmap) -> None:
        self._pending.discard(screenshot_id)
        self._cache[screenshot_id] = pixmap
        self._cache.move_to_end(screenshot_id)
        while len(self._cache) > self.capacity:
            self._cache.popitem(last=False)
        self.ready.emit(screenshot_id, pixmap)

    def _on_failed(self, screenshot_id: str, error: str) -> None:
        self._pending.discard(screenshot_id)
        self.failed.emit(screenshot_id, error)
