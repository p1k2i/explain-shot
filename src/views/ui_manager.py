"""
UIManager Module

Central coordinator for all PyQt6 user interface components.
Manages the lifecycle of windows, coordinates with EventBus, and handles UI state.
"""

import asyncio
import logging
from typing import Optional, Dict, Any, List
from PyQt6.QtCore import QObject, QTimer, pyqtSignal, QCoreApplication
from PyQt6.QtWidgets import QApplication

from ..controllers.event_bus import EventBus
from ..models.settings_manager import SettingsManager
from ..models.screenshot_manager import ScreenshotManager
from .overlay_manager import OverlayManager
from src import EventTypes

logger = logging.getLogger(__name__)


class UIManager(QObject):
    """
    Central coordinator for all UI components.

    Manages PyQt6 window lifecycle, coordinates between UI components
    and the EventBus, and handles UI state management.
    """

    # Signals for thread-safe communication
    ui_action_requested = pyqtSignal(str, dict)

    def __init__(
        self,
        event_bus: EventBus,
        settings_manager: SettingsManager,
        screenshot_manager: Optional[ScreenshotManager] = None
    ):
        """
        Initialize UIManager.

        Args:
            event_bus: EventBus instance for communication
            settings_manager: SettingsManager for configuration
            screenshot_manager: Optional ScreenshotManager for data
        """
        super().__init__()

        self.event_bus = event_bus
        self.settings_manager = settings_manager
        self.screenshot_manager = screenshot_manager

        # UI Components
        self.overlay_manager: Optional[OverlayManager] = None

        # State management
        self._initialized = False
        self._app_instance: Optional[QCoreApplication] = None

        # Timer for async integration
        self._async_timer = QTimer()
        self._async_timer.timeout.connect(self._process_async_events)
        self._async_timer.setInterval(10)  # 10ms for responsive UI

        # Event queue for async processing
        self._event_queue: List[Dict[str, Any]] = []

        logger.info("UIManager initialized")

    @property
    def is_initialized(self) -> bool:
        """Check if UIManager is initialized."""
        return self._initialized

    async def initialize(self) -> bool:
        """
        Initialize UIManager and all UI components.

        Returns:
            True if initialization successful
        """
        if self._initialized:
            logger.warning("UIManager already initialized")
            return True

        try:
            logger.info("Initializing UIManager...")

            # Get or create QApplication instance
            self._app_instance = QApplication.instance()
            if self._app_instance is None:
                # This should not happen in normal operation as main.py creates QApplication
                logger.warning("No QApplication instance found, creating one")
                self._app_instance = QApplication([])

            # Initialize overlay manager
            self.overlay_manager = OverlayManager(
                event_bus=self.event_bus,
                settings_manager=self.settings_manager,
                screenshot_manager=self.screenshot_manager,
                parent=self
            )

            await self.overlay_manager.initialize()

            # Subscribe to UI events
            await self._subscribe_to_events()

            # Connect signals
            self.ui_action_requested.connect(self._handle_ui_action)

            # Start async integration timer
            self._async_timer.start()

            self._initialized = True
            logger.info("UIManager initialization complete")

            # Emit initialization event
            await self.event_bus.emit(
                "ui.manager.initialized",
                {"timestamp": asyncio.get_event_loop().time()},
                source="UIManager"
            )

            return True

        except Exception as e:
            logger.error(f"UIManager initialization failed: {e}")
            return False

    async def _subscribe_to_events(self) -> None:
        """Subscribe to relevant events from EventBus."""
        try:
            # Overlay events
            await self.event_bus.subscribe(
                EventTypes.UI_OVERLAY_SHOW,
                self._handle_show_overlay,
                priority=95
            )

            await self.event_bus.subscribe(
                EventTypes.UI_OVERLAY_HIDE,
                self._handle_hide_overlay,
                priority=95
            )

            # Settings events
            await self.event_bus.subscribe(
                EventTypes.SETTINGS_UPDATED,
                self._handle_settings_updated,
                priority=80
            )

            # Screenshot events
            await self.event_bus.subscribe(
                EventTypes.SCREENSHOT_CAPTURED,
                self._handle_screenshot_captured,
                priority=70
            )

            # Application events
            await self.event_bus.subscribe(
                EventTypes.APP_SHUTDOWN_REQUESTED,
                self._handle_shutdown_request,
                priority=100
            )

        except Exception as e:
            logger.error(f"Failed to subscribe to events: {e}")

    async def _handle_show_overlay(self, event_data) -> None:
        """
        Handle overlay show request.

        Args:
            event_data: Event data containing show parameters
        """
        try:
            if not self.overlay_manager:
                logger.error("Overlay manager not initialized")
                return

            # Queue UI action for main thread processing
            self._queue_ui_action("show_overlay", event_data.data or {})

        except Exception as e:
            logger.error(f"Error handling show overlay request: {e}")

    async def _handle_hide_overlay(self, event_data) -> None:
        """
        Handle overlay hide request.

        Args:
            event_data: Event data containing hide parameters
        """
        try:
            if not self.overlay_manager:
                logger.error("Overlay manager not initialized")
                return

            # Queue UI action for main thread processing
            self._queue_ui_action("hide_overlay", event_data.data or {})

        except Exception as e:
            logger.error(f"Error handling hide overlay request: {e}")

    async def _handle_settings_updated(self, event_data) -> None:
        """
        Handle settings update events.

        Args:
            event_data: Event data containing updated settings
        """
        try:
            settings_data = event_data.data or {}
            key = settings_data.get('key', '')

            # Handle UI-related settings
            if key.startswith('ui.') or key.startswith('overlay.'):
                if self.overlay_manager:
                    await self.overlay_manager.handle_settings_change(settings_data)

        except Exception as e:
            logger.error(f"Error handling settings update: {e}")

    async def _handle_screenshot_captured(self, event_data) -> None:
        """
        Handle screenshot captured events.

        Args:
            event_data: Event data containing screenshot information
        """
        try:
            if self.overlay_manager:
                # Refresh overlay data if it's currently visible
                await self.overlay_manager.handle_screenshot_update(event_data.data or {})

        except Exception as e:
            logger.error(f"Error handling screenshot captured event: {e}")

    async def _handle_shutdown_request(self, event_data) -> None:
        """
        Handle application shutdown request.

        Args:
            event_data: Event data containing shutdown information
        """
        try:
            logger.info("UIManager shutdown requested")
            await self.shutdown()

        except Exception as e:
            logger.error(f"Error handling shutdown request: {e}")

    def _queue_ui_action(self, action: str, data: Dict[str, Any]) -> None:
        """
        Queue a UI action for main thread processing.

        Args:
            action: Action type to perform
            data: Action data
        """
        self._event_queue.append({
            "action": action,
            "data": data,
            "timestamp": asyncio.get_event_loop().time()
        })

    def _process_async_events(self) -> None:
        """Process queued async events in main thread."""
        try:
            # Process all queued events
            while self._event_queue:
                event = self._event_queue.pop(0)
                self.ui_action_requested.emit(event["action"], event["data"])

            # Process any pending Qt events to ensure UI updates
            if self._app_instance:
                self._app_instance.processEvents()

        except Exception as e:
            logger.error(f"Error processing async events: {e}")

    def _handle_ui_action(self, action: str, data: Dict[str, Any]) -> None:
        """
        Handle UI action in main thread.

        Args:
            action: Action type to perform
            data: Action data
        """
        try:
            if action == "show_overlay" and self.overlay_manager:
                # Schedule overlay show for next event loop iteration
                QTimer.singleShot(0, self._show_overlay_sync)

            elif action == "hide_overlay" and self.overlay_manager:
                # Schedule overlay hide for next event loop iteration
                QTimer.singleShot(0, lambda: self._hide_overlay_sync(data.get("reason", "unknown")))

            else:
                logger.warning(f"Unknown UI action: {action}")

        except Exception as e:
            logger.error(f"Error handling UI action {action}: {e}")

    def _show_overlay_sync(self) -> None:
        """Show overlay synchronously in main thread."""
        try:
            if self.overlay_manager:
                # Create task but don't await it - let it run in background
                asyncio.create_task(self.overlay_manager.show_overlay())
        except Exception as e:
            logger.error(f"Error showing overlay synchronously: {e}")

    def _hide_overlay_sync(self, reason: str) -> None:
        """Hide overlay synchronously in main thread."""
        try:
            if self.overlay_manager:
                # Create task but don't await it - let it run in background
                asyncio.create_task(self.overlay_manager.hide_overlay(reason=reason))
        except Exception as e:
            logger.error(f"Error hiding overlay synchronously: {e}")

    async def show_overlay(self, **kwargs) -> bool:
        """
        Show the overlay window.

        Args:
            **kwargs: Arguments to pass to overlay manager

        Returns:
            True if overlay shown successfully
        """
        try:
            if not self.overlay_manager:
                logger.error("Overlay manager not available")
                return False

            return await self.overlay_manager.show_overlay(**kwargs)

        except Exception as e:
            logger.error(f"Error showing overlay: {e}")
            return False

    async def hide_overlay(self, **kwargs) -> bool:
        """
        Hide the overlay window.

        Args:
            **kwargs: Arguments to pass to overlay manager

        Returns:
            True if overlay hidden successfully
        """
        try:
            if not self.overlay_manager:
                logger.error("Overlay manager not available")
                return False

            return await self.overlay_manager.hide_overlay(**kwargs)

        except Exception as e:
            logger.error(f"Error hiding overlay: {e}")
            return False

    async def get_ui_status(self) -> Dict[str, Any]:
        """
        Get current UI status.

        Returns:
            Dictionary with UI status information
        """
        status = {
            "initialized": self._initialized,
            "app_instance": self._app_instance is not None,
            "event_queue_size": len(self._event_queue),
            "overlay_manager": {
                "available": self.overlay_manager is not None,
                "initialized": self.overlay_manager.is_initialized if self.overlay_manager else False,
                "visible": self.overlay_manager.is_overlay_visible() if self.overlay_manager else False
            }
        }

        return status

    async def shutdown(self) -> None:
        """Shutdown UIManager and all UI components."""
        if not self._initialized:
            return

        try:
            logger.info("Shutting down UIManager...")

            # Stop async timer
            self._async_timer.stop()

            # Shutdown overlay manager
            if self.overlay_manager:
                await self.overlay_manager.shutdown()

            # Clear event queue
            self._event_queue.clear()

            self._initialized = False
            logger.info("UIManager shutdown complete")

        except Exception as e:
            logger.error(f"Error during UIManager shutdown: {e}")
