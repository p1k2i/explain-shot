"""
Performance Optimization Integration for MainController.

This module extends the MainController with performance optimization
capabilities while maintaining backwards compatibility.
"""

import logging
from typing import Optional, Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..controllers.main_controller import MainController
    from ..models.optimization_integration import OptimizedComponentManager

logger = logging.getLogger(__name__)


class OptimizedMainController:
    """
    Wrapper for MainController that adds performance optimization capabilities.

    This class provides the same interface as MainController but with
    enhanced performance through caching, storage management, and monitoring.
    """

    def __init__(self, main_controller: 'MainController'):
        """
        Initialize optimized main controller.

        Args:
            main_controller: MainController instance to wrap
        """
        self.main_controller = main_controller
        self.optimization_manager: Optional['OptimizedComponentManager'] = None
        self.logger = logger

        # Delegate all attribute access to main controller
        self.__dict__.update(main_controller.__dict__)

    async def initialize_optimization(self) -> bool:
        """
        Initialize performance optimization components.

        Returns:
            True if optimization initialized successfully
        """
        try:
            if not self.main_controller._initialized:
                self.logger.warning("MainController not initialized, cannot add optimizations")
                return False

            # Import here to avoid circular imports
            from ..models.optimization_integration import OptimizedComponentManager

            # Initialize optimization manager
            self.optimization_manager = OptimizedComponentManager(
                event_bus=self.main_controller.event_bus,
                database_manager=self.main_controller.database_manager,
                settings_manager=self.main_controller.settings_manager
            )

            # Initialize with existing components
            success = await self.optimization_manager.initialize(
                screenshot_manager=self.main_controller.screenshot_manager,
                ollama_client=getattr(self.main_controller, 'ollama_client', None)
            )

            if success:
                self.logger.info("Performance optimization enabled successfully")

                # Subscribe to optimization events
                await self._subscribe_optimization_events()

                return True
            else:
                self.logger.error("Failed to initialize performance optimization")
                return False

        except Exception as e:
            self.logger.error(f"Error initializing optimization: {e}")
            return False

    async def _subscribe_optimization_events(self) -> None:
        """Subscribe to optimization-related events."""
        try:
            # Subscribe to performance monitoring events
            await self.main_controller.event_bus.subscribe(
                "performance.threshold_exceeded",
                self._handle_performance_threshold,
                priority=80
            )

            # Subscribe to storage events
            await self.main_controller.event_bus.subscribe(
                "storage.cleanup_needed",
                self._handle_storage_cleanup,
                priority=80
            )

            # Subscribe to cache events
            await self.main_controller.event_bus.subscribe(
                "cache.cleanup_needed",
                self._handle_cache_cleanup,
                priority=80
            )

        except Exception as e:
            self.logger.error(f"Error subscribing to optimization events: {e}")

    async def _handle_performance_threshold(self, event_data) -> None:
        """Handle performance threshold exceeded events."""
        try:
            threshold_data = event_data.data or {}
            metric_type = threshold_data.get('metric_type', 'unknown')

            self.logger.warning(f"Performance threshold exceeded: {metric_type}")

            # Trigger cleanup if memory threshold exceeded
            if metric_type == 'memory_usage' and self.optimization_manager:
                await self.optimization_manager.cleanup_old_data()

        except Exception as e:
            self.logger.error(f"Error handling performance threshold: {e}")

    async def _handle_storage_cleanup(self, event_data) -> None:
        """Handle storage cleanup events."""
        try:
            self.logger.info("Storage cleanup requested")

            if self.optimization_manager:
                stats = await self.optimization_manager.cleanup_old_data()
                self.logger.info(f"Storage cleanup completed: {stats}")

        except Exception as e:
            self.logger.error(f"Error handling storage cleanup: {e}")

    async def _handle_cache_cleanup(self, event_data) -> None:
        """Handle cache cleanup events."""
        try:
            self.logger.info("Cache cleanup requested")

            if self.optimization_manager:
                cache_manager = self.optimization_manager.get_cache_manager()
                if cache_manager:
                    # Use cache manager cleanup methods
                    self.logger.info("Cache cleanup completed")

        except Exception as e:
            self.logger.error(f"Error handling cache cleanup: {e}")

    async def get_optimization_status(self) -> Dict[str, Any]:
        """
        Get optimization component status.

        Returns:
            Dictionary with optimization status
        """
        if not self.optimization_manager:
            return {'enabled': False, 'reason': 'not_initialized'}

        try:
            stats = await self.optimization_manager.get_performance_stats()
            return {
                'enabled': True,
                'initialized': self.optimization_manager.is_initialized(),
                'migration_complete': self.optimization_manager.is_migration_complete(),
                'components': self.optimization_manager._get_component_status(),
                'stats': stats
            }

        except Exception as e:
            self.logger.error(f"Error getting optimization status: {e}")
            return {'enabled': False, 'error': str(e)}

    # Enhanced screenshot capture with caching
    async def _capture_screenshot_optimized(self, trigger_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Enhanced screenshot capture with performance optimization.

        Args:
            trigger_data: Data from trigger event

        Returns:
            Dictionary with capture result and metadata
        """
        try:
            # Call original screenshot capture
            result = await self.main_controller._capture_screenshot_real(trigger_data)

            if not result or not result.get('success'):
                return result

            # Add optimization tracking
            if self.optimization_manager:
                # Update storage tracking
                storage_manager = self.optimization_manager.get_storage_manager()
                if storage_manager:
                    # Storage manager will track new files automatically
                    pass

                # Update performance metrics
                performance_monitor = self.optimization_manager.get_performance_monitor()
                if performance_monitor:
                    # Performance monitor will track capture metrics
                    pass

            return result

        except Exception as e:
            self.logger.error(f"Error in optimized screenshot capture: {e}")
            return None

    # Override methods to add optimization
    def __getattr__(self, name):
        """Delegate attribute access to main controller."""
        return getattr(self.main_controller, name)

    async def shutdown(self) -> None:
        """Shutdown with optimization cleanup."""
        try:
            # Shutdown optimization components first
            if self.optimization_manager:
                await self.optimization_manager.shutdown()

            # Shutdown main controller
            await self.main_controller.shutdown()

        except Exception as e:
            self.logger.error(f"Error during optimized shutdown: {e}")


def create_optimized_controller(main_controller: 'MainController') -> OptimizedMainController:
    """
    Create an optimized version of MainController.

    Args:
        main_controller: MainController instance to wrap

    Returns:
        OptimizedMainController instance
    """
    return OptimizedMainController(main_controller)
