"""
Integration Module for Performance Optimization.

This module provides optimized versions of existing components that
wrap them with performance optimization layers while maintaining
backwards compatibility and the existing API surface.
"""

import logging
from typing import Optional, Dict, Any, TYPE_CHECKING, cast

from ..controllers.event_bus import EventBus
from ..models.database_manager import DatabaseManager
from ..models.database_extensions import DatabaseExtensions
from ..models.database_schema_migration import DatabaseSchemaMigration
from .thumbnail_manager import ThumbnailManager
from .storage_manager import StorageManager
from .request_manager import RequestManager
from ..models.settings_manager import SettingsManager

if TYPE_CHECKING:
    from ..models.screenshot_manager import ScreenshotManager
    from ..models.ollama_client import OllamaClient

logger = logging.getLogger(__name__)


class OptimizationIntegrationError(Exception):
    """Exception raised for optimization integration errors."""
    pass


class OptimizedComponentManager:
    """
    Manages the integration of performance optimization components
    with existing application components.

    Provides a facade over the optimization layers while maintaining
    compatibility with existing code.
    """

    def __init__(
        self,
        event_bus: EventBus,
        database_manager: Optional[DatabaseManager],
        settings_manager: SettingsManager,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize optimized component manager.

        Args:
            event_bus: EventBus for component communication
            database_manager: DatabaseManager for persistence (can be None)
            settings_manager: SettingsManager for configuration
            logger: Optional logger instance
        """
        self.event_bus = event_bus
        self.settings_manager = settings_manager
        self.logger = logger or logging.getLogger(__name__)

        # Validate required components
        if not database_manager:
            raise ValueError("database_manager is required for optimization components")

        # Cast to non-optional type after validation
        self.db_manager: DatabaseManager = cast(DatabaseManager, database_manager)

        # Core optimization components
        self.db_extensions: Optional[DatabaseExtensions] = None
        self.migration_manager: Optional[DatabaseSchemaMigration] = None
        self.thumbnail_manager: Optional[ThumbnailManager] = None
        self.storage_manager: Optional[StorageManager] = None
        self.request_manager: Optional[RequestManager] = None

        # Component state
        self._initialized = False
        self._migration_complete = False

        self.logger.info("OptimizedComponentManager initialized")

    async def initialize(
        self,
        screenshot_manager: Optional['ScreenshotManager'] = None,
        ollama_client: Optional['OllamaClient'] = None
    ) -> bool:
        """
        Initialize all optimization components.

        Args:
            screenshot_manager: ScreenshotManager instance to wrap
            ollama_client: OllamaClient instance to wrap

        Returns:
            True if initialization successful
        """
        if self._initialized:
            self.logger.warning("OptimizedComponentManager already initialized")
            return True

        try:
            self.logger.info("Initializing optimization components...")

            # Initialize database extensions
            self.db_extensions = DatabaseExtensions(self.db_manager, self.logger)

            # Initialize migration manager and ensure schema is up to date
            self.migration_manager = DatabaseSchemaMigration(self.db_manager, self.logger)
            self._migration_complete = await self._ensure_database_migration()

            if not self._migration_complete:
                self.logger.error("Database migration failed, optimization features may not work")
                return False

            # Load optimization settings
            optimization_config = await self._load_optimization_config()

            # Initialize thumbnail manager
            self.thumbnail_manager = ThumbnailManager(
                event_bus=self.event_bus,
                cache_size=optimization_config.get('thumbnail_cache_size', 100)
            )

            # Initialize storage manager if screenshot manager is provided
            if screenshot_manager:
                self.storage_manager = StorageManager(
                    screenshot_manager=screenshot_manager,
                    database_manager=self.db_manager,
                    settings_manager=self.settings_manager,
                    event_bus=self.event_bus
                )
                await self.storage_manager.initialize()

            # Initialize request manager if ollama client is provided
            if ollama_client:
                self.request_manager = RequestManager(
                    ollama_client=ollama_client,
                    event_bus=self.event_bus
                )
                await self.request_manager.initialize()

            self._initialized = True
            self.logger.info("Optimization components initialized successfully")

            # Emit initialization event
            await self.event_bus.emit(
                "optimization.components.initialized",
                {
                    'components': self._get_component_status(),
                    'migration_complete': self._migration_complete,
                    'config': optimization_config
                },
                source="OptimizedComponentManager"
            )

            return True

        except Exception as e:
            self.logger.error(f"Failed to initialize optimization components: {e}")
            return False

    async def _ensure_database_migration(self) -> bool:
        """
        Ensure database schema is migrated to support optimization features.

        Returns:
            True if migration successful or already complete
        """
        try:
            if not self.migration_manager:
                return False

            # Check current schema version
            current_version = await self.migration_manager.get_schema_version()
            self.logger.info(f"Current database schema version: {current_version}")

            # Migrate to latest if needed
            if current_version < 3:
                self.logger.info("Migrating database for performance optimization...")
                success = await self.migration_manager.migrate_to_latest()

                if success:
                    self.logger.info("Database migration completed successfully")

                    # Validate migration
                    validation = await self.migration_manager.validate_schema()
                    if not validation['valid']:
                        self.logger.error(f"Migration validation failed: {validation['errors']}")
                        return False

                    return True
                else:
                    self.logger.error("Database migration failed")
                    return False
            else:
                self.logger.info("Database schema already up to date")
                return True

        except Exception as e:
            self.logger.error(f"Database migration error: {e}")
            return False

    async def _load_optimization_config(self) -> Dict[str, Any]:
        """
        Load optimization configuration from settings.

        Returns:
            Dictionary with optimization configuration
        """
        try:
            # Define default configuration
            default_config = {
                'thumbnail_cache_size': 100,
                'max_storage_gb': 10.0,
                'max_file_count': 1000,
                'cache_max_entries': 500,
                'cache_ttl_hours': 24,
                'max_concurrent_requests': 3,
                'request_timeout': 30.0,
                'cleanup_interval_hours': 24
            }

            # Load settings with defaults
            config = {}
            for key, default_value in default_config.items():
                setting_key = f"optimization.{key}"
                try:
                    value = await self.settings_manager.get_setting(setting_key)
                    config[key] = value if value is not None else default_value
                except Exception as e:
                    self.logger.warning(f"Failed to load setting {setting_key}: {e}")
                    config[key] = default_value

            self.logger.debug(f"Loaded optimization configuration: {config}")
            return config

        except Exception as e:
            self.logger.error(f"Failed to load optimization config: {e}")
            return {}

    def _get_component_status(self) -> Dict[str, bool]:
        """Get status of all optimization components."""
        return {
            'database_extensions': self.db_extensions is not None,
            'migration_manager': self.migration_manager is not None,
            'thumbnail_manager': self.thumbnail_manager is not None,
            'storage_manager': self.storage_manager is not None,
            'request_manager': self.request_manager is not None and self.request_manager._initialized
        }

    # Component access methods

    def get_thumbnail_manager(self) -> Optional[ThumbnailManager]:
        """Get the optimized thumbnail manager."""
        return self.thumbnail_manager

    def get_storage_manager(self) -> Optional[StorageManager]:
        """Get the optimized storage manager."""
        return self.storage_manager

    def get_request_manager(self) -> Optional[RequestManager]:
        """Get the optimized request manager."""
        return self.request_manager

    # Convenience methods for common operations

    async def cleanup_old_data(self) -> Dict[str, int]:
        """
        Perform cleanup of old data across all components.

        Returns:
            Dictionary with cleanup statistics
        """
        cleanup_stats = {
            'expired_cache_entries': 0,
            'old_screenshots': 0,
            'freed_bytes': 0
        }

        try:
            # Cleanup old screenshots if storage manager is available
            if self.storage_manager:
                # Execute pruning to clean up old files
                pruning_result = await self.storage_manager.execute_pruning(require_consent=False)
                cleanup_stats['old_screenshots'] = pruning_result.deleted_count
                cleanup_stats['freed_bytes'] = pruning_result.freed_bytes

            self.logger.info(f"Cleanup completed: {cleanup_stats}")
            return cleanup_stats

        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")
            return cleanup_stats

    async def get_performance_stats(self) -> Dict[str, Any]:
        """
        Get performance statistics from all components.

        Returns:
            Dictionary with performance statistics
        """
        stats = {}

        try:
            # Get storage statistics
            if self.storage_manager:
                stats['storage'] = await self.storage_manager.get_storage_statistics()

            # Get component status
            stats['components'] = self._get_component_status()

            return stats

        except Exception as e:
            self.logger.error(f"Error getting performance stats: {e}")
            return {}

    async def update_optimization_config(self, config: Dict[str, Any]) -> bool:
        """
        Update optimization configuration.

        Args:
            config: New configuration values

        Returns:
            True if update successful
        """
        try:
            # Store new settings
            for key, value in config.items():
                setting_key = f"optimization.{key}"
                success = await self.settings_manager.update_setting(setting_key, value)
                if not success:
                    self.logger.warning(f"Failed to store setting {setting_key}")

            # Apply configuration changes to components
            await self._apply_config_changes(config)

            self.logger.info("Optimization configuration updated")
            return True

        except Exception as e:
            self.logger.error(f"Error updating optimization config: {e}")
            return False

    async def _apply_config_changes(self, config: Dict[str, Any]) -> None:
        """Apply configuration changes to optimization components."""
        try:
            # Update thumbnail cache size
            # Note: ThumbnailManager doesn't have update_cache_size method
            # Cache size is set during initialization
            pass

            # Update cache configuration
            # Note: CacheManager configuration is loaded from settings
            # To update cache config, update settings and reload
            pass

            # Update request manager configuration
            if self.request_manager:
                max_concurrent = config.get('max_concurrent_requests')
                timeout = config.get('request_timeout')
                if max_concurrent is not None or timeout is not None:
                    await self.request_manager.configure_limits(
                        max_concurrent=max_concurrent,
                        timeout=timeout
                    )

        except Exception as e:
            self.logger.error(f"Error applying config changes: {e}")

    async def shutdown(self) -> None:
        """Shutdown all optimization components."""
        if not self._initialized:
            return

        try:
            self.logger.info("Shutting down optimization components...")

            # Shutdown request manager
            if self.request_manager:
                await self.request_manager.shutdown()

            # Shutdown storage manager
            if self.storage_manager:
                await self.storage_manager.shutdown()

            self._initialized = False
            self.logger.info("Optimization components shutdown complete")

        except Exception as e:
            self.logger.error(f"Error during optimization shutdown: {e}")

    def is_initialized(self) -> bool:
        """Check if optimization components are initialized."""
        return self._initialized

    def is_migration_complete(self) -> bool:
        """Check if database migration is complete."""
        return self._migration_complete
