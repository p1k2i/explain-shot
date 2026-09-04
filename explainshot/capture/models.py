"""Small dataclasses for capture. The old screenshot_models.py had ~360 lines
across five classes with many redundant fields; almost none of the ceremony
was used."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class CaptureRegion:
    x: int
    y: int
    width: int
    height: int

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.x + self.width, self.y + self.height)


@dataclass
class ScreenshotRecord:
    id: str
    filename: str
    path: str
    width: int
    height: int
    size_bytes: int
    format: str
    created_at: datetime
