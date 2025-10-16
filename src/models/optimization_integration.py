"""
Integration Module for Performance Optimization.

This module provides optimized versions of existing components that
wrap them with performance optimization layers while maintaining
backwards compatibility and the existing API surface.
"""

import logging
from typing import Optional, Dict, Any, TYPE_CHECKING

from ..controllers.event_bus import EventBus
from ..models.database_manager import DatabaseManager
from ..models.database_extensions import DatabaseExtensions
from ..models.database_schema_migration import DatabaseSchemaMigration
from .thumbnail_manager import ThumbnailManager
from .storage_manager import StorageManager
from .cache_manager import CacheManager
from .request_manager import RequestManager
from ..models.performance_monitor import PerformanceMonitor
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
        database_manager: DatabaseManager,
        settings_manager: SettingsManager,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize optimized component manager.

        Args:
            event_bus: EventBus for component communication
            database_manager: DatabaseManager for persistence
            settings_manager: SettingsManager for configuration
            logger: Optional logger instance
        """
        self.event_bus = event_bus
        self.db_manager = database_manager
        self.settings_manager = settings_manager
        self.logger = logger or logging.getLogger(__name__)

        # Core optimization components
        self.db_extensions: Optional[DatabaseExtensions] = None
        self.migration_manager: Optional[DatabaseSchemaMigration] = None
        self.thumbnail_manager: Optional[ThumbnailManager] = None
        self.storage_manager: Optional[StorageManager] = None
        self.cache_manager: Optional[CacheManager] = None
        self.request_manager: Optional[RequestManager] = None
        self.performance_monitor: Optional[PerformanceMonitor] = None

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

            # Initialize cache manager
            self.cache_manager = CacheManager(
                database_manager=self.db_manager,
                settings_manager=self.settings_manager,
                event_bus=self.event_bus
            )
            await self.cache_manager.initialize()

            # Initialize request manager if ollama client is provided
            if ollama_client:
                self.request_manager = RequestManager(
                    ollama_client=ollama_client,
                    cache_manager=self.cache_manager,
                    event_bus=self.event_bus
                )
                await self.request_manager.initialize()

            # Initialize performance monitor
            self.performance_monitor = PerformanceMonitor(
                event_bus=self.event_bus
            )

            # Register components with performance monitor
            if self.thumbnail_manager:
                self.performance_monitor.register_component("thumbnail_manager", self.thumbnail_manager)
            if self.storage_manager:
                self.performance_monitor.register_component("storage_manager", self.storage_manager)
            if self.cache_manager:
                self.performance_monitor.register_component("cache_manager", self.cache_manager)
            if self.request_manager:
                self.performance_monitor.register_component("request_manager", self.request_manager)

            # Start performance monitoring
            await self.performance_monitor.start_monitoring()

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
            if current_version < 2:  # Performance optimization schema
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
                'enable_performance_monitoring': True,
                'cleanup_interval_hours': 24,
                'memory_threshold_mb': 1024,
                'disk_usage_threshold_percent': 90
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
            'cache_manager': self.cache_manager is not None and self.cache_manager.is_initialized,
            'request_manager': self.request_manager is not None and self.request_manager.is_initialized,
            'performance_monitor': self.performance_monitor is not None and self.performance_monitor.is_monitoring
        }

    # Component access methods

    def get_thumbnail_manager(self) -> Optional[ThumbnailManager]:
        """Get the optimized thumbnail manager."""
        return self.thumbnail_manager

    def get_storage_manager(self) -> Optional[StorageManager]:
        """Get the optimized storage manager."""
        return self.storage_manager

    def get_cache_manager(self) -> Optional[CacheManager]:
        """Get the optimized cache manager."""
        return self.cache_manager

    def get_request_manager(self) -> Optional[RequestManager]:
        """Get the optimized request manager."""
        return self.request_manager

    def get_performance_monitor(self) -> Optional[PerformanceMonitor]:
        """Get the performance monitor."""
        return self.performance_monitor

    # Convenience methods for common operations

    async def get_cached_ai_response(
        self,
        prompt: str,
        model_name: str = "default"
    ) -> Optional[str]:
        """
        Get cached AI response for a prompt.

        Args:
            prompt: User prompt
            model_name: AI model name

        Returns:
            Cached response or None if not found
        """
        if not self.cache_manager:
            return None

        try:
            return await self.cache_manager.get_cached_response(prompt, model_name)
        except Exception as e:
            self.logger.error(f"Error getting cached response: {e}")
            return None

    async def store_ai_response(
        self,
        prompt: str,
        response: str,
        model_name: str = "default",
        processing_time: float = 0.0
    ) -> bool:
        """
        Store AI response in cache.

        Args:
            prompt: User prompt
            response: AI response
            model_name: AI model name
            processing_time: Time taken to generate response

        Returns:
            True if stored successfully
        """
        if not self.cache_manager:
            return False

        try:
            return await self.cache_manager.store_response(
                prompt, response, model_name, processing_time
            )
        except Exception as e:
            self.logger.error(f"Error storing AI response: {e}")
            return False

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
            # Cleanup expired cache entries
            if self.cache_manager:
                expired_count = await self.cache_manager.cleanup_expired()
                cleanup_stats['expired_cache_entries'] = expired_count

            # Cleanup old screenshots if storage manager is available
            if self.storage_manager:
                storage_stats = await self.storage_manager.cleanup_old_files()
                cleanup_stats['old_screenshots'] = storage_stats.get('files_removed', 0)
                cleanup_stats['freed_bytes'] = storage_stats.get('bytes_freed', 0)

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
            # Get cache statistics
            if self.cache_manager:
                stats['cache'] = await self.cache_manager.get_cache_stats()

            # Get storage statistics
            if self.storage_manager:
                stats['storage'] = await self.storage_manager.get_storage_stats()

            # Get performance metrics
            if self.performance_monitor and self.db_extensions:
                stats['performance'] = await self.db_extensions.get_metric_aggregates(
                    'memory_usage', hours_back=1
                )

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
                success = await self.settings_manager.set_setting(setting_key, value)
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
            if 'thumbnail_cache_size' in config and self.thumbnail_manager:
                self.thumbnail_manager.update_cache_size(config['thumbnail_cache_size'])

            # Update cache configuration
            if self.cache_manager:
                if 'cache_max_entries' in config:
                    self.cache_manager.max_cache_size = config['cache_max_entries']
                if 'cache_ttl_hours' in config:
                    self.cache_manager.default_ttl_hours = config['cache_ttl_hours']

            # Update request manager configuration
            if self.request_manager:
                if 'max_concurrent_requests' in config:
                    self.request_manager.max_concurrent_requests = config['max_concurrent_requests']
                if 'request_timeout' in config:
                    self.request_manager.request_timeout = config['request_timeout']

        except Exception as e:
            self.logger.error(f"Error applying config changes: {e}")

    async def shutdown(self) -> None:
        """Shutdown all optimization components."""
        if not self._initialized:
            return

        try:
            self.logger.info("Shutting down optimization components...")

            # Stop performance monitoring
            if self.performance_monitor:
                await self.performance_monitor.stop_monitoring()

            # Shutdown request manager
            if self.request_manager:
                await self.request_manager.shutdown()

            # Shutdown storage manager
            if self.storage_manager:
                await self.storage_manager.shutdown()

            # Final cache cleanup
            if self.cache_manager:
                await self.cache_manager.cleanup_expired()

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
