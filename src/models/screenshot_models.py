"""
Data models for screenshot functionality.

This module contains the data structures used by the ScreenshotManager
and related components for handling screenshot metadata, results, and validation.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Tuple
from pathlib import Path
import hashlib


@dataclass
class ScreenshotMetadata:
    """Metadata for a captured screenshot."""

    filename: str
    full_path: str
    timestamp: datetime
    file_size: int
    resolution: Tuple[int, int]
    format: str = "PNG"
    id: Optional[int] = None  # Database ID after registration
    checksum: Optional[str] = None  # SHA256 for integrity verification
    thumbnail_path: Optional[str] = None

    def __post_init__(self):
        """Calculate checksum if file exists and checksum not provided."""
        if self.checksum is None and Path(self.full_path).exists():
            self.checksum = self._calculate_checksum()

    def _calculate_checksum(self) -> str:
        """Calculate SHA256 checksum of the screenshot file."""
        try:
            with open(self.full_path, 'rb') as f:
                file_hash = hashlib.sha256()
                chunk = f.read(8192)
                while chunk:
                    file_hash.update(chunk)
                    chunk = f.read(8192)
                return file_hash.hexdigest()
        except (OSError, IOError):
            return ""

    def to_dict(self) -> dict:
        """Convert to dictionary for database storage."""
        return {
            'filename': self.filename,
            'path': self.full_path,
            'timestamp': self.timestamp.isoformat(),
            'file_size': self.file_size,
            'thumbnail_path': self.thumbnail_path,
            'metadata': {
                'resolution': self.resolution,
                'format': self.format,
                'checksum': self.checksum
            }
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'ScreenshotMetadata':
        """Create from dictionary (e.g., from database)."""
        metadata = data.get('metadata', {})
        if isinstance(metadata, str):
            import json
            metadata = json.loads(metadata)

        return cls(
            id=data.get('id'),
            filename=data['filename'],
            full_path=data['path'],
            timestamp=datetime.fromisoformat(data['timestamp']),
            file_size=data['file_size'],
            resolution=tuple(metadata.get('resolution', (0, 0))),
            format=metadata.get('format', 'PNG'),
            checksum=metadata.get('checksum'),
            thumbnail_path=data.get('thumbnail_path')
        )


@dataclass
class ScreenshotResult:
    """Result of a screenshot capture operation."""

    success: bool
    metadata: Optional[ScreenshotMetadata] = None
    error_message: Optional[str] = None
    capture_duration: float = 0.0
    save_duration: float = 0.0

    @property
    def total_duration(self) -> float:
        """Total time for capture and save operations."""
        return self.capture_duration + self.save_duration

    def to_dict(self) -> dict:
        """Convert to dictionary for logging/debugging."""
        return {
            'success': self.success,
            'error_message': self.error_message,
            'capture_duration': self.capture_duration,
            'save_duration': self.save_duration,
            'total_duration': self.total_duration,
            'metadata': self.metadata.to_dict() if self.metadata else None
        }


@dataclass
class ValidationResult:
    """Result of directory or path validation."""

    is_valid: bool
    error_messages: List[str] = field(default_factory=list)
    can_write: bool = False
    available_space: int = 0  # in bytes

    def add_error(self, message: str) -> None:
        """Add an error message."""
        self.error_messages.append(message)
        self.is_valid = False

    def add_warning(self, message: str) -> None:
        """Add a warning message (doesn't invalidate)."""
        self.error_messages.append(f"WARNING: {message}")


@dataclass
class StorageStats:
    """Statistics about screenshot storage."""

    total_screenshots: int
    total_size_bytes: int
    oldest_screenshot: Optional[datetime] = None
    newest_screenshot: Optional[datetime] = None
    directory_size: int = 0

    @property
    def total_size_mb(self) -> float:
        """Total size in megabytes."""
        return self.total_size_bytes / (1024 * 1024)

    @property
    def directory_size_mb(self) -> float:
        """Directory size in megabytes."""
        return self.directory_size / (1024 * 1024)

    @property
    def average_file_size_mb(self) -> float:
        """Average file size in megabytes."""
        if self.total_screenshots == 0:
            return 0.0
        return self.total_size_mb / self.total_screenshots


@dataclass
class CaptureRegion:
    """Defines a region for screenshot capture."""

    x: int
    y: int
    width: int
    height: int

    @property
    def bbox(self) -> Tuple[int, int, int, int]:
        """Return as PIL-compatible bounding box (left, top, right, bottom)."""
        return (self.x, self.y, self.x + self.width, self.y + self.height)

    @property
    def area(self) -> int:
        """Calculate area in pixels."""
        return self.width * self.height

    def __str__(self) -> str:
        return f"Region({self.x}, {self.y}, {self.width}x{self.height})"


@dataclass
class ScreenshotConfig:
    """Configuration for screenshot operations."""

    directory: str
    filename_format: str = "screenshot_%Y%m%d_%H%M%S_%f"
    compression_level: int = 6  # PNG compression level 0-9
    auto_create_directory: bool = True
    max_screenshots: int = 1000  # 0 = unlimited
    cleanup_days: int = 30  # 0 = never cleanup
    quality: int = 95  # For future JPEG support

    def __post_init__(self):
        """Validate configuration values."""
        if not (0 <= self.compression_level <= 9):
            self.compression_level = 6
        if not (1 <= self.quality <= 100):
            self.quality = 95
        if self.max_screenshots < 0:
            self.max_screenshots = 0
        if self.cleanup_days < 0:
            self.cleanup_days = 0


# Error classes for specific screenshot operations
class ScreenshotError(Exception):
    """Base exception for screenshot operations."""
    pass


class CaptureError(ScreenshotError):
    """Exception raised during screenshot capture."""
    pass


class SaveError(ScreenshotError):
    """Exception raised during screenshot save operations."""
    pass


class DirectoryError(ScreenshotError):
    """Exception raised for directory-related issues."""
    pass


class ValidationError(ScreenshotError):
    """Exception raised for validation failures."""
    pass
