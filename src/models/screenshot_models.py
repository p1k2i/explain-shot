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
    id: Optional[int] = None  # Legacy database ID - will be deprecated in v3
    hash: Optional[str] = None  # SHA-256 hash used as unique identifier
    checksum: Optional[str] = None  # SHA256 for integrity verification (deprecated, use hash)
    thumbnail_path: Optional[str] = None

    def __post_init__(self):
        """Calculate hash if file exists and hash not provided."""
        if self.hash is None and Path(self.full_path).exists():
            self.hash = self._calculate_hash()

        # For backwards compatibility, set checksum to hash if not provided
        if self.checksum is None:
            self.checksum = self.hash

    def _calculate_hash(self) -> str:
        """Calculate SHA-256 hash of the screenshot file."""
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

    def _calculate_checksum(self) -> str:
        """Calculate SHA256 checksum of the screenshot file. (Deprecated: use _calculate_hash)"""
        return self._calculate_hash()

    @property
    def unique_id(self) -> str:
        """Get unique identifier for this screenshot (hash-based)."""
        return self.hash or ""

    @property
    def is_valid_file(self) -> bool:
        """Check if the screenshot file still exists."""
        return Path(self.full_path).exists()

    @property
    def file_extension(self) -> str:
        """Get file extension from filename."""
        return Path(self.filename).suffix.lower()

    @property
    def file_size_mb(self) -> float:
        """Get file size in megabytes."""
        return self.file_size / (1024 * 1024)

    @property
    def aspect_ratio(self) -> float:
        """Calculate aspect ratio (width/height)."""
        if self.resolution[1] == 0:
            return 0.0
        return self.resolution[0] / self.resolution[1]

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            'filename': self.filename,
            'path': self.full_path,
            'timestamp': self.timestamp.isoformat(),
            'file_size': self.file_size,
            'thumbnail_path': self.thumbnail_path,
            'hash': self.hash,
            'id': self.id,  # Legacy field for backwards compatibility
            'metadata': {
                'resolution': self.resolution,
                'format': self.format,
                'checksum': self.checksum,  # Legacy field
                'hash': self.hash  # New primary identifier
            }
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'ScreenshotMetadata':
        """Create from dictionary (e.g., from database or JSON)."""
        metadata = data.get('metadata', {})
        if isinstance(metadata, str):
            import json
            metadata = json.loads(metadata)

        # Prefer hash from metadata, fallback to checksum for backwards compatibility
        hash_value = metadata.get('hash') or metadata.get('checksum') or data.get('hash')

        return cls(
            id=data.get('id'),
            filename=data['filename'],
            full_path=data['path'],
            timestamp=datetime.fromisoformat(data['timestamp']),
            file_size=data['file_size'],
            resolution=tuple(metadata.get('resolution', (0, 0))),
            format=metadata.get('format', 'PNG'),
            hash=hash_value,
            checksum=metadata.get('checksum') or hash_value,  # Backwards compatibility
            thumbnail_path=data.get('thumbnail_path')
        )

    @classmethod
    def from_file_path(cls, file_path: str) -> 'ScreenshotMetadata':
        """
        Create ScreenshotMetadata from a file path by reading file properties.

        Args:
            file_path: Path to screenshot file

        Returns:
            ScreenshotMetadata instance

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If file can't be processed
        """
        path_obj = Path(file_path)

        if not path_obj.exists():
            raise FileNotFoundError(f"Screenshot file not found: {file_path}")

        if not path_obj.is_file():
            raise ValueError(f"Path is not a file: {file_path}")

        # Get file statistics
        stat = path_obj.stat()

        # Try to get image properties
        resolution = (0, 0)
        image_format = "PNG"

        try:
            from PIL import Image
            with Image.open(path_obj) as img:
                resolution = img.size
                image_format = img.format or "PNG"
        except Exception:
            # Fall back to extension-based format detection
            ext = path_obj.suffix.lower()
            if ext in ['.jpg', '.jpeg']:
                image_format = "JPEG"
            elif ext == '.bmp':
                image_format = "BMP"
            elif ext == '.tiff':
                image_format = "TIFF"

        # Extract timestamp from filename or use modification time
        timestamp = cls._extract_timestamp_from_filename(path_obj.name)
        if timestamp is None:
            timestamp = datetime.fromtimestamp(stat.st_mtime)

        return cls(
            filename=path_obj.name,
            full_path=str(path_obj.absolute()),
            timestamp=timestamp,
            file_size=stat.st_size,
            resolution=resolution,
            format=image_format
            # hash will be computed in __post_init__
        )

    @staticmethod
    def _extract_timestamp_from_filename(filename: str) -> Optional[datetime]:
        """
        Extract timestamp from screenshot filename.

        Args:
            filename: Screenshot filename

        Returns:
            datetime object or None if extraction fails
        """
        try:
            import re

            # Pattern for default format: screenshot_YYYYMMDD_HHMMSS_mmm.ext
            pattern = r'screenshot_(\d{8})_(\d{6})_(\d{3})'
            match = re.search(pattern, filename)

            if match:
                date_str = match.group(1)  # YYYYMMDD
                time_str = match.group(2)  # HHMMSS
                ms_str = match.group(3)    # milliseconds

                year = int(date_str[:4])
                month = int(date_str[4:6])
                day = int(date_str[6:8])
                hour = int(time_str[:2])
                minute = int(time_str[2:4])
                second = int(time_str[4:6])
                microsecond = int(ms_str) * 1000

                return datetime(year, month, day, hour, minute, second, microsecond)

            # ISO format pattern: screenshot_YYYY-MM-DD_HH-MM-SS.ext
            iso_pattern = r'screenshot_(\d{4}-\d{2}-\d{2})_(\d{2}-\d{2}-\d{2})'
            match = re.search(iso_pattern, filename)

            if match:
                date_str = match.group(1)
                time_str = match.group(2).replace('-', ':')
                return datetime.fromisoformat(f"{date_str} {time_str}")

            return None

        except Exception:
            return None


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
    format: str = "PNG"  # Image format (PNG, JPEG, etc.)

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
