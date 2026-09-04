"""Screenshot capture and metadata storage.

The capture pipeline is now split so the region selector can hand a raw
pixmap to the editor, and the editor commits the possibly-annotated result
back through `save_pixmap`. The DB is authoritative for metadata; the file
lives in the configured directory.
"""

from __future__ import annotations

import hashlib
import io
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image, ImageGrab
from PyQt6.QtCore import QBuffer, QIODevice
from PyQt6.QtGui import QPixmap

from ..config.settings import ScreenshotConfig
from ..core.database import Database
from .models import CaptureRegion, ScreenshotRecord

if TYPE_CHECKING:
    from ..core.signals import AppSignals

log = logging.getLogger(__name__)


class ScreenshotService:
    def __init__(
        self,
        db: Database,
        config: ScreenshotConfig,
        directory: str,
        signals: "AppSignals",
    ) -> None:
        self.db = db
        self.config = config
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.signals = signals

    # -- capture pipeline ------------------------------------------------------

    def grab_region(self, region: CaptureRegion) -> QPixmap:
        """Capture the given region as a QPixmap without persisting it."""
        pil = ImageGrab.grab(bbox=region.bbox, all_screens=True)
        if pil.mode != "RGBA":
            pil = pil.convert("RGBA")
        return _pil_to_pixmap(pil)

    def grab_desktop(self) -> QPixmap:
        """Grab every pixel of the virtual desktop as a single pixmap.
        Used by the Lightshot-style overlay so it can paint the real image
        under the dim scrim and preview accurate crops / blurs."""
        pil = ImageGrab.grab(bbox=None, all_screens=True)
        if pil.mode != "RGBA":
            pil = pil.convert("RGBA")
        return _pil_to_pixmap(pil)

    def save_pixmap(self, pixmap: QPixmap) -> ScreenshotRecord:
        """Persist a QPixmap (from the editor) into the gallery."""
        pil = _pixmap_to_pil(pixmap)
        return self._persist_pil(pil)

    def capture(self, region: CaptureRegion | None = None) -> ScreenshotRecord:
        """One-shot capture straight to disk. Kept for the tray "quick capture" path."""
        image = ImageGrab.grab(bbox=region.bbox if region else None, all_screens=True)
        return self._persist_pil(image)

    # -- gallery ops -----------------------------------------------------------

    def import_existing(self, source: Path) -> ScreenshotRecord:
        with Image.open(source) as image:
            return self._persist_pil(image.copy(), source_name=source.name)

    def list_recent(self, limit: int | None = 500) -> list[ScreenshotRecord]:
        return [self._row_to_record(row) for row in self.db.list_screenshots(limit=limit)]

    def get(self, screenshot_id: str) -> ScreenshotRecord | None:
        row = self.db.get_screenshot(screenshot_id)
        return self._row_to_record(row) if row else None

    def rename(self, screenshot_id: str, new_stem: str) -> ScreenshotRecord | None:
        row = self.db.get_screenshot(screenshot_id)
        if not row:
            return None
        old_path = Path(row["path"])
        new_path = old_path.with_name(f"{new_stem}{old_path.suffix}")
        try:
            old_path.rename(new_path)
        except OSError as exc:
            log.warning("rename failed: %s", exc)
            return None
        self.db.rename_screenshot(screenshot_id, new_path.name, str(new_path))
        return self.get(screenshot_id)

    def delete(self, screenshot_id: str) -> None:
        row = self.db.get_screenshot(screenshot_id)
        if not row:
            return
        Path(row["path"]).unlink(missing_ok=True)
        self.db.delete_screenshot(screenshot_id)
        self.signals.screenshot_deleted.emit(screenshot_id)

    def scan_directory(self) -> int:
        added = 0
        known = {row["path"] for row in self.db.list_screenshots(limit=None)}
        for entry in self.directory.iterdir():
            if entry.is_file() and entry.suffix.lower() in {".png", ".jpg", ".jpeg"}:
                if str(entry) not in known:
                    try:
                        self.import_existing(entry)
                        added += 1
                    except Exception as exc:
                        log.warning("scan skipped %s: %s", entry, exc)
        return added

    # -- internals -------------------------------------------------------------

    def _persist_pil(self, image: Image.Image, source_name: str | None = None) -> ScreenshotRecord:
        fmt = self.config.image_format.upper()
        if fmt not in {"PNG", "JPEG"}:
            fmt = "PNG"
        content_bytes = image.tobytes()
        digest = hashlib.sha256(content_bytes).hexdigest()

        ext = "png" if fmt == "PNG" else "jpg"
        filename = source_name or f"{datetime.now():%Y%m%d_%H%M%S}_{digest[:8]}.{ext}"
        path = self.directory / filename
        save_kwargs: dict = {}
        if fmt == "JPEG":
            save_kwargs["quality"] = int(self.config.jpeg_quality)
            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
        image.save(path, format=fmt, **save_kwargs)

        record = ScreenshotRecord(
            id=digest,
            filename=filename,
            path=str(path),
            width=image.width,
            height=image.height,
            size_bytes=path.stat().st_size,
            format=fmt,
            created_at=datetime.now(),
        )
        self.db.upsert_screenshot(**record.__dict__)
        log.info("captured %s (%dx%d, %s)", record.filename, record.width, record.height, fmt)
        self.signals.screenshot_captured.emit(record)
        return record

    @staticmethod
    def _row_to_record(row) -> ScreenshotRecord:
        return ScreenshotRecord(
            id=row["id"],
            filename=row["filename"],
            path=row["path"],
            width=row["width"],
            height=row["height"],
            size_bytes=row["size_bytes"],
            format=row["format"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )


def _pil_to_pixmap(image: Image.Image) -> QPixmap:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    pixmap = QPixmap()
    pixmap.loadFromData(buffer.getvalue(), "PNG")
    return pixmap


def _pixmap_to_pil(pixmap: QPixmap) -> Image.Image:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.ReadWrite)
    pixmap.save(buffer, "PNG")
    data = bytes(buffer.data())
    return Image.open(io.BytesIO(data)).copy()
