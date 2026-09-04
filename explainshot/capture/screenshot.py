"""Screenshot capture and metadata storage.

Replaces the sprawling ScreenshotManager + StorageManager + screenshot_models
tangle. The image is written to disk; the metadata row goes into SQLite.
Directory scanning happens once on startup so the DB is authoritative
afterwards.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image, ImageGrab

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

    # -- public API ------------------------------------------------------------

    def capture(self, region: CaptureRegion | None = None) -> ScreenshotRecord:
        image = ImageGrab.grab(bbox=region.bbox if region else None, all_screens=True)
        record = self._persist(image)
        self.signals.screenshot_captured.emit(record)
        return record

    def import_existing(self, source: Path) -> ScreenshotRecord:
        """Copy a file the user drops in, or one that appeared while the app
        was closed, into the managed directory and register it in the db."""
        with Image.open(source) as image:
            record = self._persist(image.copy(), source_name=source.name)
        return record

    def list_recent(self, limit: int | None = 500) -> list[ScreenshotRecord]:
        return [self._row_to_record(row) for row in self.db.list_screenshots(limit=limit)]

    def get(self, screenshot_id: str) -> ScreenshotRecord | None:
        row = self.db.get_screenshot(screenshot_id)
        return self._row_to_record(row) if row else None

    def delete(self, screenshot_id: str) -> None:
        row = self.db.get_screenshot(screenshot_id)
        if not row:
            return
        Path(row["path"]).unlink(missing_ok=True)
        self.db.delete_screenshot(screenshot_id)
        self.signals.screenshot_deleted.emit(screenshot_id)

    def scan_directory(self) -> int:
        """Register any image files sitting in the directory that the DB doesn't know about."""
        added = 0
        known = {row["path"] for row in self.db.list_screenshots(limit=None)}
        for entry in self.directory.iterdir():
            if entry.is_file() and entry.suffix.lower() in {".png", ".jpg", ".jpeg"}:
                if str(entry) not in known:
                    try:
                        self.import_existing(entry)
                        added += 1
                    except Exception as exc:  # corrupt file, permission etc — skip loudly
                        log.warning("scan skipped %s: %s", entry, exc)
        return added

    # -- internals -------------------------------------------------------------

    def _persist(self, image: Image.Image, source_name: str | None = None) -> ScreenshotRecord:
        fmt = self.config.image_format.upper()
        if fmt not in {"PNG", "JPEG"}:
            fmt = "PNG"
        # Compute the content hash first so id + filename are deterministic.
        # PIL keeps image data in memory; hashing the raw pixels avoids re-encoding twice.
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
