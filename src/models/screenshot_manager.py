"""
Screenshot Manager for capturing, saving, and managing screenshots.

This module implements the core screenshot functionality including capture,
file management, database integration, and event handling.
"""

import asyncio
import logging
import os
import shutil
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, TYPE_CHECKING, Any

try:
    from PIL import Image, ImageGrab
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    ImageGrab = None
    Image = None

if TYPE_CHECKING and PIL_AVAILABLE:
    from PIL.Image import Image as PILImage
else:
    PILImage = Any

from ..models.screenshot_models import (
    ScreenshotMetadata, ScreenshotResult, ValidationResult,
    StorageStats, CaptureRegion, ScreenshotConfig,
    CaptureError, SaveError, DirectoryError
)
from .. import EventTypes


class ScreenshotManager:
    """
    Manages screenshot capture, storage, and metadata operations.

    This class handles all screenshot-related operations including:
    - Screen capture using PIL/Pillow
    - File management with atomic saves
    - Database integration for metadata
    - Event emission via EventBus
    - Directory management and validation
    """

    def __init__(self, database_manager, settings_manager, event_bus, logger=None):
        """
        Initialize the ScreenshotManager.

        Args:
            database_manager: DatabaseManager instance for metadata storage
            settings_manager: SettingsManager instance for configuration
            event_bus: EventBus instance for event communication
            logger: Optional logger instance
        """
        self.database_manager = database_manager
        self.settings_manager = settings_manager
        self.event_bus = event_bus
        self.logger = logger or logging.getLogger(__name__)

        # Internal state
        self._initialized = False
        self._config: Optional[ScreenshotConfig] = None
        self._current_directory = ""
        self._capture_count = 0
        self._last_cleanup = datetime.now()

        # Performance tracking
        self._capture_times = []
        self._save_times = []

        # Ensure PIL is available
        if not PIL_AVAILABLE:
            self.logger.error("PIL/Pillow not available - screenshot functionality disabled")
            raise ImportError("PIL/Pillow is required for screenshot functionality")

    @property
    def is_initialized(self) -> bool:
        """Check if the manager has been initialized."""
        return self._initialized

    @property
    def current_directory(self) -> str:
        """Get the current screenshot directory."""
        return self._current_directory

    @property
    def capture_count(self) -> int:
        """Get the number of screenshots captured in this session."""
        return self._capture_count

    async def initialize(self) -> None:
        """
        Initialize the ScreenshotManager.

        Sets up configuration, validates directories, and prepares for operations.
        """
        try:
            self.logger.info("Initializing ScreenshotManager")

            # Load configuration from settings
            await self._load_configuration()

            # Validate and setup directory
            await self._setup_directory()

            # Subscribe to relevant events
            await self._subscribe_to_events()

            # Perform initial cleanup if needed
            await self._perform_initial_cleanup()

            self._initialized = True
            self.logger.info(f"ScreenshotManager initialized successfully, directory: {self._current_directory}")

            # Emit initialization complete event
            await self.event_bus.emit("screenshot.manager.initialized", {
                "directory": self._current_directory,
                "config": self._config.__dict__ if self._config else {}
            })

        except Exception as e:
            self.logger.error(f"Failed to initialize ScreenshotManager: {e}")
            await self.event_bus.emit("screenshot.manager.initialization_failed", {
                "error": str(e)
            })
            raise

    async def capture_screenshot(self, region: Optional[CaptureRegion] = None) -> ScreenshotResult:
        """
        Capture a screenshot and save it to disk.

        Args:
            region: Optional region to capture, None for full screen

        Returns:
            ScreenshotResult with success status and metadata
        """
        if not self._initialized:
            raise RuntimeError("ScreenshotManager not initialized")

        start_time = time.time()

        try:
            # Emit capture started event
            await self.event_bus.emit("screenshot.capture_started", {
                "timestamp": datetime.now(),
                "region": region.__dict__ if region else None
            })

            # Perform the actual capture
            capture_start = time.time()
            image = await self._capture_screen(region)
            capture_duration = time.time() - capture_start

            # Generate filename and path
            filename = self._generate_filename()
            full_path = os.path.join(self._current_directory, filename)

            # Save the image
            save_start = time.time()
            await self._save_image_atomic(image, full_path)
            save_duration = time.time() - save_start

            # Create metadata
            metadata = ScreenshotMetadata(
                filename=filename,
                full_path=full_path,
                timestamp=datetime.now(),
                file_size=os.path.getsize(full_path),
                resolution=image.size,
                format="PNG"
            )

            # Register in database
            try:
                metadata.id = await self.database_manager.create_screenshot(metadata)
            except Exception as e:
                self.logger.warning(f"Failed to register screenshot in database: {e}")
                # Continue without database registration

            # Update statistics
            self._capture_count += 1
            self._capture_times.append(capture_duration)
            self._save_times.append(save_duration)

            # Create result
            result = ScreenshotResult(
                success=True,
                metadata=metadata,
                capture_duration=capture_duration,
                save_duration=save_duration
            )

            self.logger.info(f"Screenshot captured successfully: {full_path}")

            # Emit success events
            await self.event_bus.emit("screenshot.captured", {
                "metadata": metadata.to_dict(),
                "file_size": metadata.file_size,
                "duration": result.total_duration
            })

            await self.event_bus.emit("screenshot.save_completed", {
                "path": full_path,
                "metadata": metadata.to_dict()
            })

            return result

        except Exception as e:
            error_message = f"Screenshot capture failed: {e}"
            self.logger.error(error_message)

            # Emit failure event
            await self.event_bus.emit("screenshot.capture_failed", {
                "error": str(e),
                "error_type": type(e).__name__,
                "timestamp": datetime.now()
            })

            return ScreenshotResult(
                success=False,
                error_message=error_message,
                capture_duration=time.time() - start_time
            )

    async def get_recent_screenshots(self, limit: int = 3) -> List[ScreenshotMetadata]:
        """
        Get recent screenshots from the database.

        Args:
            limit: Maximum number of screenshots to return

        Returns:
            List of ScreenshotMetadata objects
        """
        try:
            screenshots = await self.database_manager.get_screenshots(limit=limit, offset=0)

            # Validate that files still exist
            valid_screenshots = []
            for screenshot in screenshots:
                if Path(screenshot.full_path).exists():
                    valid_screenshots.append(screenshot)
                else:
                    # Remove from database if file doesn't exist
                    try:
                        await self.database_manager.delete_screenshot(screenshot.id)
                        self.logger.info(f"Removed orphaned screenshot record: {screenshot.filename}")
                    except Exception as e:
                        self.logger.warning(f"Failed to remove orphaned record: {e}")

            return valid_screenshots

        except Exception as e:
            self.logger.error(f"Failed to get recent screenshots: {e}")
            return []

    async def cleanup_old_screenshots(self, days: Optional[int] = None) -> int:
        """
        Clean up old screenshots based on age.

        Args:
            days: Number of days to keep, uses config default if None

        Returns:
            Number of screenshots cleaned up
        """
        cleanup_days = days or (self._config.cleanup_days if self._config else 30)
        if cleanup_days == 0:
            return 0  # No cleanup configured

        try:
            cutoff_date = datetime.now() - timedelta(days=cleanup_days)

            # Get old screenshots from database
            old_screenshots = await self.database_manager.get_screenshots_before_date(cutoff_date)

            cleaned_count = 0
            for screenshot in old_screenshots:
                try:
                    # Remove file if it exists
                    if Path(screenshot.full_path).exists():
                        os.remove(screenshot.full_path)

                    # Remove thumbnail if it exists
                    if screenshot.thumbnail_path and Path(screenshot.thumbnail_path).exists():
                        os.remove(screenshot.thumbnail_path)

                    # Remove from database
                    await self.database_manager.delete_screenshot(screenshot.id)
                    cleaned_count += 1

                except Exception as e:
                    self.logger.warning(f"Failed to cleanup screenshot {screenshot.filename}: {e}")

            if cleaned_count > 0:
                self.logger.info(f"Cleaned up {cleaned_count} old screenshots")
                await self.event_bus.emit("screenshot.cleanup_completed", {
                    "cleaned_count": cleaned_count,
                    "cutoff_date": cutoff_date
                })

            self._last_cleanup = datetime.now()
            return cleaned_count

        except Exception as e:
            self.logger.error(f"Failed to cleanup old screenshots: {e}")
            return 0

    async def refresh_directory_config(self) -> None:
        """Refresh directory configuration from settings."""
        try:
            old_directory = self._current_directory
            await self._load_configuration()
            await self._setup_directory()

            if old_directory != self._current_directory:
                await self.event_bus.emit("screenshot.directory_changed", {
                    "old_path": old_directory,
                    "new_path": self._current_directory
                })

        except Exception as e:
            self.logger.error(f"Failed to refresh directory configuration: {e}")

    def validate_directory(self, path: str) -> ValidationResult:
        """
        Validate a directory for screenshot storage.

        Args:
            path: Directory path to validate

        Returns:
            ValidationResult with validation status and details
        """
        result = ValidationResult(is_valid=True, can_write=False, available_space=0)

        try:
            path_obj = Path(path)

            # Check if path exists
            if not path_obj.exists():
                if self._config and self._config.auto_create_directory:
                    result.add_warning("Directory will be created automatically")
                else:
                    result.add_error("Directory does not exist")
                    return result
            elif not path_obj.is_dir():
                result.add_error("Path exists but is not a directory")
                return result

            # Check write permissions
            try:
                test_file = path_obj / ".test_write_permission"
                test_file.touch()
                test_file.unlink()
                result.can_write = True
            except (OSError, PermissionError):
                result.add_error("No write permission for directory")
                return result

            # Check available space
            try:
                stat = shutil.disk_usage(str(path_obj))
                result.available_space = stat.free

                # Warn if less than 100MB available
                if result.available_space < 100 * 1024 * 1024:
                    result.add_warning("Low disk space (< 100MB available)")

            except Exception as e:
                result.add_warning(f"Could not check disk space: {e}")

            # Validate path length (Windows limitation)
            if len(str(path_obj)) > 240:  # Leave room for filenames
                result.add_error("Path too long (Windows limitation)")

        except Exception as e:
            result.add_error(f"Path validation failed: {e}")

        return result

    def generate_filename(self, base_name: str = "screenshot") -> str:
        """
        Generate a unique filename for a screenshot.

        Args:
            base_name: Base name for the file

        Returns:
            Unique filename with extension
        """
        return self._generate_filename(base_name)

    async def get_storage_statistics(self) -> StorageStats:
        """
        Get storage statistics for screenshots.

        Returns:
            StorageStats with current storage information
        """
        try:
            # Get database statistics
            total_count = await self.database_manager.get_screenshot_count()
            total_size = await self.database_manager.get_total_screenshot_size()
            oldest = await self.database_manager.get_oldest_screenshot_date()
            newest = await self.database_manager.get_newest_screenshot_date()

            # Get directory size
            directory_size = 0
            if Path(self._current_directory).exists():
                for file_path in Path(self._current_directory).rglob("*"):
                    if file_path.is_file():
                        try:
                            directory_size += file_path.stat().st_size
                        except (OSError, PermissionError):
                            pass

            return StorageStats(
                total_screenshots=total_count,
                total_size_bytes=total_size,
                oldest_screenshot=oldest,
                newest_screenshot=newest,
                directory_size=directory_size
            )

        except Exception as e:
            self.logger.error(f"Failed to get storage statistics: {e}")
            return StorageStats(
                total_screenshots=0,
                total_size_bytes=0,
                directory_size=0
            )

    async def shutdown(self) -> None:
        """Clean shutdown of the ScreenshotManager."""
        try:
            self.logger.info("Shutting down ScreenshotManager")

            # Perform final cleanup if needed
            if self._config and self._config.cleanup_days > 0:
                await self.cleanup_old_screenshots()

            # Emit shutdown event
            await self.event_bus.emit("screenshot.manager.shutdown", {
                "capture_count": self._capture_count,
                "average_capture_time": sum(self._capture_times) / len(self._capture_times) if self._capture_times else 0,
                "average_save_time": sum(self._save_times) / len(self._save_times) if self._save_times else 0
            })

            self._initialized = False

        except Exception as e:
            self.logger.error(f"Error during ScreenshotManager shutdown: {e}")

    # Private methods

    async def _load_configuration(self) -> None:
        """Load configuration from SettingsManager."""
        try:
            screenshot_dir = await self.settings_manager.get_setting(
                "screenshot_directory",
                self._get_default_directory()
            )
            filename_format = await self.settings_manager.get_setting(
                "filename_format",
                "screenshot_%Y%m%d_%H%M%S_%f"
            )
            compression_level = await self.settings_manager.get_setting("compression_level", 6)
            auto_create = await self.settings_manager.get_setting("auto_create_directory", True)
            max_screenshots = await self.settings_manager.get_setting("max_screenshots", 1000)
            cleanup_days = await self.settings_manager.get_setting("cleanup_days", 30)

            self._config = ScreenshotConfig(
                directory=screenshot_dir,
                filename_format=filename_format,
                compression_level=compression_level,
                auto_create_directory=auto_create,
                max_screenshots=max_screenshots,
                cleanup_days=cleanup_days
            )

        except Exception as e:
            self.logger.warning(f"Failed to load configuration, using defaults: {e}")
            self._config = ScreenshotConfig(directory=self._get_default_directory())

    def _get_default_directory(self) -> str:
        """Get default screenshot directory for the platform."""
        if os.name == 'nt':  # Windows
            # Try Pictures/Screenshots first
            pictures_dir = os.path.join(os.path.expanduser("~"), "Pictures", "Screenshots")
            if os.path.exists(os.path.dirname(pictures_dir)):
                return pictures_dir

            # Fallback to user home/Screenshots
            return os.path.join(os.path.expanduser("~"), "Screenshots")
        else:
            # Linux/macOS
            return os.path.join(os.path.expanduser("~"), "Screenshots")

    async def _setup_directory(self) -> None:
        """Setup and validate the screenshot directory."""
        if not self._config:
            raise RuntimeError("Configuration not loaded")

        directory = self._config.directory
        validation = self.validate_directory(directory)

        if not validation.is_valid:
            if self._config.auto_create_directory:
                try:
                    Path(directory).mkdir(parents=True, exist_ok=True)
                    self.logger.info(f"Created screenshot directory: {directory}")
                except Exception as e:
                    raise DirectoryError(f"Failed to create directory {directory}: {e}")
            else:
                raise DirectoryError(f"Directory validation failed: {', '.join(validation.error_messages)}")

        self._current_directory = directory

    async def _subscribe_to_events(self) -> None:
        """Subscribe to relevant events from EventBus."""
        try:
            await self.event_bus.subscribe(
                EventTypes.SETTINGS_UPDATED,
                self._handle_settings_updated,
                priority=75
            )
            await self.event_bus.subscribe(
                EventTypes.APP_SHUTDOWN_REQUESTED,
                self._handle_app_shutdown,
                priority=50
            )
        except Exception as e:
            self.logger.warning(f"Failed to subscribe to events: {e}")

    async def _handle_settings_updated(self, event_data) -> None:
        """Handle settings update events."""
        try:
            data = event_data.data if event_data else {}
            key = data.get("key", "")

            # Handle screenshot-related settings
            if key.startswith("screenshot."):
                self.logger.info(f"Screenshot setting updated: {key}")
                await self.refresh_directory_config()
            elif key in ["filename_format", "compression_level"]:
                self.logger.info(f"Screenshot configuration updated: {key}")
                await self.refresh_directory_config()

        except Exception as e:
            self.logger.error(f"Error handling settings update: {e}")

    async def _handle_app_shutdown(self, data: dict) -> None:
        """Handle application shutdown events."""
        await self.shutdown()

    async def _perform_initial_cleanup(self) -> None:
        """Perform initial cleanup if needed."""
        if self._config and self._config.cleanup_days > 0:
            # Check if cleanup was performed recently
            last_cleanup = await self.settings_manager.get_setting("last_cleanup_date", None)
            if last_cleanup:
                try:
                    last_cleanup_date = datetime.fromisoformat(last_cleanup)
                    if (datetime.now() - last_cleanup_date).days < 1:
                        return  # Cleanup was recent, skip
                except Exception:
                    pass  # Invalid date format, proceed with cleanup

            await self.cleanup_old_screenshots()
            await self.settings_manager.update_setting("last_cleanup_date", datetime.now().isoformat())

    async def _capture_screen(self, region: Optional[CaptureRegion] = None) -> Any:
        """
        Capture the screen using PIL.

        Args:
            region: Optional region to capture

        Returns:
            PIL Image object
        """
        if not PIL_AVAILABLE or ImageGrab is None:
            raise CaptureError("PIL/Pillow not available")

        assert ImageGrab is not None  # For type checker

        try:
            # Run capture in thread pool to avoid blocking
            loop = asyncio.get_event_loop()

            assert ImageGrab is not None  # For type checker

            if region:
                image = await loop.run_in_executor(
                    None,
                    lambda: ImageGrab.grab(bbox=region.bbox)  # type: ignore
                )
            else:
                image = await loop.run_in_executor(None, ImageGrab.grab)  # type: ignore

            if image is None:
                raise CaptureError("Failed to capture screen - ImageGrab returned None")

            return image

        except Exception as e:
            raise CaptureError(f"Screen capture failed: {e}") from e

    async def _save_image_atomic(self, image: Any, full_path: str) -> None:
        """
        Save image atomically to prevent corruption.

        Args:
            image: PIL Image to save
            full_path: Full path where to save the image
        """
        if not PIL_AVAILABLE or Image is None:
            raise SaveError("PIL/Pillow not available")

        assert Image is not None  # For type checker

        temp_path = None
        try:
            # Create temporary file in the same directory
            directory = os.path.dirname(full_path)
            filename = os.path.basename(full_path)

            with tempfile.NamedTemporaryFile(
                dir=directory,
                prefix=f".{filename}.",
                suffix=".tmp",
                delete=False
            ) as temp_file:
                temp_path = temp_file.name

            # Save image to temporary file
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: image.save(
                    temp_path,
                    "PNG",
                    compress_level=self._config.compression_level if self._config else 6
                )
            )

            # Verify the file was saved correctly
            if not os.path.exists(temp_path) or os.path.getsize(temp_path) == 0:
                raise SaveError("Temporary file was not created or is empty")

            # Atomic rename to final path
            if os.name == 'nt':  # Windows
                # On Windows, rename might fail if target exists
                if os.path.exists(full_path):
                    os.remove(full_path)

            os.rename(temp_path, full_path)
            temp_path = None  # Successfully renamed, don't cleanup

        except Exception as e:
            # Cleanup temporary file if it exists
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass  # Ignore cleanup errors

            raise SaveError(f"Failed to save image: {e}") from e

    def _generate_filename(self, base_name: str = "screenshot") -> str:
        """
        Generate a unique filename with collision resolution.

        Args:
            base_name: Base name for the file

        Returns:
            Unique filename with extension
        """
        now = datetime.now()

        # Use config format if available
        if self._config and self._config.filename_format:
            try:
                # Handle microseconds separately for %f format
                format_str = self._config.filename_format
                if "%f" in format_str:
                    # Replace %f with milliseconds (3 digits)
                    milliseconds = f"{now.microsecond // 1000:03d}"
                    format_str = format_str.replace("%f", milliseconds)

                base_filename = now.strftime(format_str)
            except Exception as e:
                self.logger.warning(f"Invalid filename format, using default: {e}")
                base_filename = f"{base_name}_{now.strftime('%Y%m%d_%H%M%S_%f')[:-3]}"
        else:
            base_filename = f"{base_name}_{now.strftime('%Y%m%d_%H%M%S_%f')[:-3]}"

        filename = f"{base_filename}.png"
        full_path = os.path.join(self._current_directory, filename)

        # Handle collisions
        counter = 1
        while os.path.exists(full_path) and counter <= 1000:
            filename = f"{base_filename}_{counter}.png"
            full_path = os.path.join(self._current_directory, filename)
            counter += 1

        if counter > 1000:
            # Emergency fallback with UUID
            import uuid
            filename = f"{base_filename}_{uuid.uuid4().hex[:8]}.png"

        return filename
