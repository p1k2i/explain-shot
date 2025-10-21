"""
Enhanced Storage Manager for Screenshot Pruning and Management

This module provides intelligent storage management with configurable limits,
automatic pruning, periodic cleanup, and user consent workflows.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path
from enum import Enum

logger = logging.getLogger(__name__)


class PruningAction(Enum):
    """Types of pruning actions that can be performed."""
    DELETE_FILES = "delete_files"
    DELETE_METADATA = "delete_metadata"
    DELETE_BOTH = "delete_both"


class PruningStrategy(Enum):
    """Strategies for determining which screenshots to prune."""
    OLDEST_FIRST = "oldest_first"
    LARGEST_FIRST = "largest_first"
    LEAST_ACCESSED = "least_accessed"


@dataclass
class StorageStatus:
    """Current storage status information."""
    total_screenshots: int
    total_size_bytes: int
    available_space_bytes: Optional[int]
    limit_exceeded: bool
    excess_count: int
    suggested_prune_count: int


@dataclass
class PruningCandidate:
    """Information about a screenshot candidate for pruning."""
    screenshot_id: int
    filename: str
    file_path: str
    timestamp: datetime
    file_size: int
    access_count: int = 0
    last_accessed: Optional[datetime] = None


@dataclass
class PruningResult:
    """Result of a pruning operation."""
    success: bool
    deleted_count: int
    freed_bytes: int
    errors: List[str]
    duration: float
    user_cancelled: bool = False


@dataclass
class StorageConfig:
    """Configuration for storage management."""
    max_screenshots: int = 1000
    max_size_mb: int = 5000
    auto_prune_enabled: bool = True
    prune_strategy: PruningStrategy = PruningStrategy.OLDEST_FIRST
    prune_action: PruningAction = PruningAction.DELETE_BOTH
    require_user_consent: bool = True
    cleanup_interval_hours: int = 24
    keep_minimum: int = 10


class StorageManager:
    """
    Enhanced storage manager with intelligent pruning and cleanup.

    Provides:
    - Configurable screenshot count and size limits
    - Automatic pruning with multiple strategies
    - User consent workflows for deletions
    - Periodic cleanup tasks
    - Storage monitoring and alerts
    - Integration with existing ScreenshotManager
    """

    def __init__(self, screenshot_manager, database_manager, settings_manager, event_bus):
        """
        Initialize the storage manager.

        Args:
            screenshot_manager: Existing ScreenshotManager instance
            database_manager: DatabaseManager for metadata operations
            settings_manager: SettingsManager for configuration
            event_bus: EventBus for communication
        """
        self.screenshot_manager = screenshot_manager
        self.database_manager = database_manager
        self.settings_manager = settings_manager
        self.event_bus = event_bus

        # Configuration
        self._config = StorageConfig()
        self._initialized = False

        # Monitoring
        self._last_check = datetime.now()
        self._check_interval = timedelta(minutes=5)
        self._periodic_task: Optional[asyncio.Task] = None

        # Statistics
        self._pruning_stats = {
            'total_operations': 0,
            'total_deleted': 0,
            'total_freed_bytes': 0,
            'user_cancellations': 0,
            'last_prune': None
        }

        # User consent handling
        self._consent_callbacks = []
        self._pending_consent_requests = {}

        logger.debug("StorageManager initialized")

    async def initialize(self) -> None:
        """Initialize the storage manager."""
        try:
            # Load configuration
            await self._load_settings()

            # Subscribe to events
            if self.event_bus:
                self.event_bus.subscribe("screenshot.captured", self._handle_screenshot_captured)
                self.event_bus.subscribe("settings.changed", self._handle_settings_changed)
                self.event_bus.subscribe("storage.check_requested", self._handle_check_requested)

            # Start periodic monitoring if enabled
            if self._config.auto_prune_enabled:
                await self._start_periodic_monitoring()

            self._initialized = True
            logger.debug("StorageManager initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize StorageManager: {e}")
            raise

    async def _load_settings(self) -> None:
        """Load storage configuration from settings."""
        try:
            if not self.settings_manager:
                return

            settings = await self.settings_manager.load_settings()

            # Load storage configuration if available
            if hasattr(settings, 'storage'):
                storage_config = settings.storage
                self._config.max_screenshots = getattr(storage_config, 'max_screenshots', 1000)
                self._config.max_size_mb = getattr(storage_config, 'max_size_mb', 5000)
                self._config.auto_prune_enabled = getattr(storage_config, 'auto_prune_enabled', True)
                self._config.require_user_consent = getattr(storage_config, 'require_user_consent', True)
                self._config.cleanup_interval_hours = getattr(storage_config, 'cleanup_interval_hours', 24)
                self._config.keep_minimum = getattr(storage_config, 'keep_minimum', 10)

                # Parse enum values
                strategy_str = getattr(storage_config, 'prune_strategy', 'oldest_first')
                try:
                    self._config.prune_strategy = PruningStrategy(strategy_str)
                except ValueError:
                    self._config.prune_strategy = PruningStrategy.OLDEST_FIRST

                action_str = getattr(storage_config, 'prune_action', 'delete_both')
                try:
                    self._config.prune_action = PruningAction(action_str)
                except ValueError:
                    self._config.prune_action = PruningAction.DELETE_BOTH

            logger.debug(f"Loaded storage settings - Max: {self._config.max_screenshots}, "
                        f"Auto-prune: {self._config.auto_prune_enabled}")

        except Exception as e:
            logger.warning(f"Failed to load storage settings: {e}")

    async def check_storage_limit(self) -> StorageStatus:
        """
        Check current storage status against limits.

        Returns:
            StorageStatus object with current state
        """
        try:
            # Get screenshot count and total size from filesystem
            screenshots = await self.screenshot_manager.scan_screenshot_directory()
            total_count = len(screenshots)
            total_size = sum(s.file_size for s in screenshots if s.file_size)

            # Check available disk space
            available_space = None
            if screenshots:
                try:
                    sample_path = Path(screenshots[0].full_path).parent
                    stat = sample_path.stat() if sample_path.exists() else None
                    if stat:
                        # This is a simplified check - real implementation would use shutil.disk_usage
                        available_space = 1024 * 1024 * 1024  # Placeholder: 1GB
                except Exception:
                    pass

            # Determine if limits are exceeded
            count_exceeded = total_count > self._config.max_screenshots
            size_exceeded = total_size > (self._config.max_size_mb * 1024 * 1024)
            limit_exceeded = count_exceeded or size_exceeded

            # Calculate excess and suggested prune count
            excess_count = 0
            if count_exceeded:
                excess_count = total_count - self._config.max_screenshots
            elif size_exceeded:
                # Estimate based on average file size
                avg_size = total_size / total_count if total_count > 0 else 0
                if avg_size > 0:
                    target_size = self._config.max_size_mb * 1024 * 1024
                    excess_bytes = total_size - target_size
                    excess_count = int(excess_bytes / avg_size)

            # Add buffer for suggested prune count
            suggested_prune = max(excess_count, int(total_count * 0.1)) if limit_exceeded else 0

            status = StorageStatus(
                total_screenshots=total_count,
                total_size_bytes=total_size,
                available_space_bytes=available_space,
                limit_exceeded=limit_exceeded,
                excess_count=excess_count,
                suggested_prune_count=suggested_prune
            )

            # Emit status event
            if self.event_bus:
                await self.event_bus.emit("storage.status_checked", {
                    'status': status,
                    'timestamp': datetime.now().isoformat()
                })

            return status

        except Exception as e:
            logger.error(f"Failed to check storage limits: {e}")
            return StorageStatus(
                total_screenshots=0,
                total_size_bytes=0,
                available_space_bytes=None,
                limit_exceeded=False,
                excess_count=0,
                suggested_prune_count=0
            )

    async def execute_pruning(self,
                            prune_count: Optional[int] = None,
                            strategy: Optional[PruningStrategy] = None,
                            require_consent: Optional[bool] = None) -> PruningResult:
        """
        Execute pruning operation with specified parameters.

        Args:
            prune_count: Number of screenshots to prune (auto-calculated if None)
            strategy: Pruning strategy to use (uses config default if None)
            require_consent: Whether to require user consent (uses config default if None)

        Returns:
            PruningResult with operation details
        """
        start_time = time.time()
        result = PruningResult(
            success=False,
            deleted_count=0,
            freed_bytes=0,
            errors=[],
            duration=0.0
        )

        try:
            # Determine parameters
            if strategy is None:
                strategy = self._config.prune_strategy
            if require_consent is None:
                require_consent = self._config.require_user_consent

            # Check storage status
            status = await self.check_storage_limit()
            if not status.limit_exceeded:
                logger.info("Storage limits not exceeded, skipping pruning")
                result.success = True
                result.duration = time.time() - start_time
                return result

            # Determine prune count
            if prune_count is None:
                prune_count = status.suggested_prune_count

            # Ensure we don't delete too many
            total_count = status.total_screenshots
            max_deletable = total_count - self._config.keep_minimum
            prune_count = min(prune_count, max_deletable)

            if prune_count <= 0:
                logger.info("No screenshots to prune after applying minimum keep limit")
                result.success = True
                result.duration = time.time() - start_time
                return result

            # Get pruning candidates
            candidates = await self._get_pruning_candidates(prune_count, strategy)
            if not candidates:
                result.errors.append("No pruning candidates found")
                result.duration = time.time() - start_time
                return result

            # Request user consent if required
            if require_consent:
                consent_granted = await self._request_user_consent(candidates)
                if not consent_granted:
                    result.user_cancelled = True
                    result.duration = time.time() - start_time
                    self._pruning_stats['user_cancellations'] += 1
                    return result

            # Execute pruning
            deleted_count, freed_bytes, errors = await self._execute_deletion(candidates)

            # Update result
            result.success = len(errors) == 0 or deleted_count > 0
            result.deleted_count = deleted_count
            result.freed_bytes = freed_bytes
            result.errors = errors
            result.duration = time.time() - start_time

            # Update statistics
            self._pruning_stats['total_operations'] += 1
            self._pruning_stats['total_deleted'] += deleted_count
            self._pruning_stats['total_freed_bytes'] += freed_bytes
            self._pruning_stats['last_prune'] = datetime.now()

            # Emit completion event
            if self.event_bus:
                await self.event_bus.emit("storage.prune_executed", {
                    'result': result,
                    'candidates_count': len(candidates),
                    'strategy': strategy.value,
                    'timestamp': datetime.now().isoformat()
                })

            logger.info(f"Pruning completed: {deleted_count} deleted, {freed_bytes} bytes freed")

        except Exception as e:
            result.errors.append(str(e))
            result.duration = time.time() - start_time
            logger.error(f"Pruning operation failed: {e}")

        return result

    async def _get_pruning_candidates(self, count: int, strategy: PruningStrategy) -> List[PruningCandidate]:
        """Get list of pruning candidates based on strategy."""
        try:
            # Get all screenshots from filesystem
            screenshots = await self.screenshot_manager.scan_screenshot_directory()

            if not screenshots:
                return []

            # Convert to pruning candidates
            candidates = []
            for screenshot in screenshots:
                candidate = PruningCandidate(
                    screenshot_id=screenshot.hash or screenshot.unique_id,  # Use hash instead of ID
                    filename=screenshot.filename,
                    file_path=screenshot.full_path,
                    timestamp=screenshot.timestamp,
                    file_size=screenshot.file_size or 0
                )
                candidates.append(candidate)

            # Sort based on strategy
            if strategy == PruningStrategy.OLDEST_FIRST:
                candidates.sort(key=lambda x: x.timestamp)
            elif strategy == PruningStrategy.LARGEST_FIRST:
                candidates.sort(key=lambda x: x.file_size, reverse=True)
            elif strategy == PruningStrategy.LEAST_ACCESSED:
                # For now, use oldest as fallback since we don't track access count
                candidates.sort(key=lambda x: x.timestamp)

            # Return requested count
            return candidates[:count]

        except Exception as e:
            logger.error(f"Failed to get pruning candidates: {e}")
            return []

    async def _request_user_consent(self, candidates: List[PruningCandidate]) -> bool:
        """Request user consent for deletion."""
        try:
            if not self._consent_callbacks:
                logger.warning("No consent callbacks registered, proceeding with deletion")
                return True

            # Prepare consent request data
            request_data = {
                'candidate_count': len(candidates),
                'total_size': sum(c.file_size for c in candidates),
                'oldest_file': min(candidates, key=lambda x: x.timestamp).filename if candidates else None,
                'newest_file': max(candidates, key=lambda x: x.timestamp).filename if candidates else None,
                'strategy': self._config.prune_strategy.value
            }

            # Create consent request
            request_id = f"prune_consent_{int(time.time())}"
            consent_future = asyncio.Future()
            self._pending_consent_requests[request_id] = consent_future

            # Call consent callbacks
            for callback in self._consent_callbacks:
                try:
                    callback(request_id, request_data)
                except Exception as e:
                    logger.error(f"Error in consent callback: {e}")

            # Wait for user response with timeout
            try:
                result = await asyncio.wait_for(consent_future, timeout=30.0)
                return result
            except asyncio.TimeoutError:
                logger.warning("User consent request timed out, denying deletion")
                return False
            finally:
                self._pending_consent_requests.pop(request_id, None)

        except Exception as e:
            logger.error(f"Failed to request user consent: {e}")
            return False

    def add_consent_callback(self, callback):
        """Add callback for user consent requests."""
        self._consent_callbacks.append(callback)

    async def respond_to_consent_request(self, request_id: str, granted: bool) -> None:
        """Respond to a consent request."""
        try:
            if request_id in self._pending_consent_requests:
                future = self._pending_consent_requests[request_id]
                if not future.done():
                    future.set_result(granted)

        except Exception as e:
            logger.error(f"Failed to respond to consent request: {e}")

    async def _execute_deletion(self, candidates: List[PruningCandidate]) -> Tuple[int, int, List[str]]:
        """Execute actual deletion of candidates."""
        deleted_count = 0
        freed_bytes = 0
        errors = []

        for candidate in candidates:
            try:
                deleted_size = 0

                # Delete file if it exists and action includes files
                if self._config.prune_action in [PruningAction.DELETE_FILES, PruningAction.DELETE_BOTH]:
                    file_path = Path(candidate.file_path)
                    if file_path.exists():
                        file_size = file_path.stat().st_size
                        file_path.unlink()
                        deleted_size += file_size
                        logger.debug(f"Deleted file: {candidate.filename}")

                # Note: No database metadata to delete since screenshots are now file-based only

                deleted_count += 1
                freed_bytes += deleted_size

            except Exception as e:
                error_msg = f"Failed to delete {candidate.filename}: {e}"
                errors.append(error_msg)
                logger.error(error_msg)

        return deleted_count, freed_bytes, errors

    async def schedule_periodic_cleanup(self) -> None:
        """Schedule periodic cleanup task."""
        try:
            if self._periodic_task and not self._periodic_task.done():
                self._periodic_task.cancel()

            self._periodic_task = asyncio.create_task(self._periodic_cleanup_loop())
            logger.info("Periodic cleanup scheduled")

        except Exception as e:
            logger.error(f"Failed to schedule periodic cleanup: {e}")

    async def _start_periodic_monitoring(self) -> None:
        """Start periodic monitoring task."""
        try:
            if self._config.auto_prune_enabled:
                await self.schedule_periodic_cleanup()

        except Exception as e:
            logger.error(f"Failed to start periodic monitoring: {e}")

    async def _periodic_cleanup_loop(self) -> None:
        """Periodic cleanup loop."""
        try:
            interval_seconds = self._config.cleanup_interval_hours * 3600

            while True:
                await asyncio.sleep(interval_seconds)

                try:
                    # Check if cleanup is needed
                    status = await self.check_storage_limit()

                    if status.limit_exceeded:
                        logger.info("Periodic cleanup triggered - storage limits exceeded")

                        # Execute automatic pruning
                        result = await self.execute_pruning(
                            prune_count=status.suggested_prune_count,
                            require_consent=self._config.require_user_consent
                        )

                        if result.success:
                            logger.info(f"Periodic cleanup completed: {result.deleted_count} deleted")
                        else:
                            logger.warning(f"Periodic cleanup failed: {result.errors}")

                except Exception as e:
                    logger.error(f"Error in periodic cleanup cycle: {e}")

        except asyncio.CancelledError:
            logger.info("Periodic cleanup task cancelled")
        except Exception as e:
            logger.error(f"Periodic cleanup loop failed: {e}")

    async def get_storage_statistics(self) -> Dict[str, Any]:
        """Get storage statistics and pruning history."""
        try:
            status = await self.check_storage_limit()

            return {
                'current_status': {
                    'total_screenshots': status.total_screenshots,
                    'total_size_mb': round(status.total_size_bytes / (1024 * 1024), 2),
                    'total_size_bytes': status.total_size_bytes,
                    'limit_exceeded': status.limit_exceeded,
                    'excess_count': status.excess_count
                },
                'configuration': {
                    'max_screenshots': self._config.max_screenshots,
                    'max_size_mb': self._config.max_size_mb,
                    'auto_prune_enabled': self._config.auto_prune_enabled,
                    'strategy': self._config.prune_strategy.value,
                    'require_consent': self._config.require_user_consent
                },
                'pruning_history': self._pruning_stats.copy()
            }

        except Exception as e:
            logger.error(f"Failed to get storage statistics: {e}")
            return {}

    async def set_auto_prune_enabled(self, enabled: bool) -> None:
        """Enable or disable automatic pruning."""
        try:
            self._config.auto_prune_enabled = enabled

            if enabled:
                await self._start_periodic_monitoring()
            else:
                if self._periodic_task and not self._periodic_task.done():
                    self._periodic_task.cancel()
                    self._periodic_task = None

            # Update settings if available
            if self.settings_manager:
                await self.settings_manager.update_setting('storage.auto_prune_enabled', enabled)

            logger.info(f"Auto-prune {'enabled' if enabled else 'disabled'}")

        except Exception as e:
            logger.error(f"Failed to set auto-prune enabled: {e}")

    async def _handle_screenshot_captured(self, event_data) -> None:
        """Handle screenshot capture events."""
        try:
            # Check if we should trigger pruning after capture
            if self._config.auto_prune_enabled:
                # Only check every few captures to avoid overhead
                now = datetime.now()
                if now - self._last_check >= self._check_interval:
                    self._last_check = now

                    status = await self.check_storage_limit()
                    if status.limit_exceeded:
                        logger.info("Storage limit exceeded after capture, triggering pruning")

                        # Execute pruning in background
                        asyncio.create_task(self.execute_pruning())

        except Exception as e:
            logger.error(f"Error handling screenshot captured: {e}")

    async def _handle_settings_changed(self, event_data) -> None:
        """Handle settings change events."""
        try:
            data = event_data.get('data', {})
            key = data.get('key', '')

            if key.startswith('storage.'):
                await self._load_settings()
                logger.info("Reloaded storage settings")

        except Exception as e:
            logger.error(f"Failed to handle settings change: {e}")

    async def _handle_check_requested(self, event_data) -> None:
        """Handle manual storage check requests."""
        try:
            status = await self.check_storage_limit()

            if self.event_bus:
                await self.event_bus.emit("storage.check_completed", {
                    'status': status,
                    'timestamp': datetime.now().isoformat()
                })

        except Exception as e:
            logger.error(f"Failed to handle check request: {e}")

    async def shutdown(self) -> None:
        """Shutdown the storage manager."""
        try:
            logger.debug("Shutting down StorageManager")

            # Cancel periodic task
            if self._periodic_task and not self._periodic_task.done():
                self._periodic_task.cancel()
                try:
                    await self._periodic_task
                except asyncio.CancelledError:
                    pass

            # Clear pending consent requests
            for request_id, future in self._pending_consent_requests.items():
                if not future.done():
                    future.set_result(False)
            self._pending_consent_requests.clear()

            logger.debug("StorageManager shutdown complete")

        except Exception as e:
            logger.error(f"Error during StorageManager shutdown: {e}")
