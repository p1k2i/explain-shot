"""
Main Controller Module

Orchestrates the application components and handles business logic
following the MVC pattern with event-driven architecture.
"""

import asyncio
import logging
from typing import Optional, Dict, Any, TYPE_CHECKING
from datetime import datetime

if TYPE_CHECKING:
    from src.views.tray_manager import TrayManager
    from src.views.ui_manager import UIManager

# Local imports
from src.controllers.event_bus import EventBus
from src.controllers.hotkey_handler import HotkeyHandler
from src.models.settings_manager import SettingsManager
from src.models.database_manager import DatabaseManager
from src.models.screenshot_manager import ScreenshotManager
from src.utils.auto_start import AutoStartManager
from src import EventTypes, AppState

logger = logging.getLogger(__name__)


class MainController:
    """
    Main application controller that orchestrates all components.

    Handles initialization, event coordination, and business logic
    implementation across the MVC architecture.
    """

    def __init__(
        self,
        event_bus: EventBus,
        settings_manager: SettingsManager,
        database_manager: Optional[DatabaseManager] = None,
        screenshot_manager: Optional[ScreenshotManager] = None,
        tray_manager: Optional["TrayManager"] = None,
        ui_manager: Optional["UIManager"] = None,
        auto_start_manager: Optional[AutoStartManager] = None
    ):
        """
        Initialize MainController.

        Args:
            event_bus: EventBus instance for coordination
            settings_manager: SettingsManager for configuration
            database_manager: DatabaseManager for data persistence
            screenshot_manager: ScreenshotManager for screenshot operations
            tray_manager: Optional TrayManager instance
            ui_manager: Optional UIManager instance for PyQt6 UI components
            auto_start_manager: Optional AutoStartManager instance
        """
        self.event_bus = event_bus
        self.settings_manager = settings_manager
        self.database_manager = database_manager
        self.screenshot_manager = screenshot_manager
        self.tray_manager = tray_manager
        self.ui_manager = ui_manager
        self.auto_start_manager = auto_start_manager

        # Controllers
        self.hotkey_handler: Optional[HotkeyHandler] = None

        # State
        self._initialized = False
        self._app_state = AppState.STARTING

        logger.info("MainController initialized")

    async def initialize(self) -> bool:
        """
        Initialize all controllers and components.

        Returns:
            True if initialization successful
        """
        if self._initialized:
            logger.warning("MainController already initialized")
            return True

        try:
            logger.info("Initializing MainController...")

            # Subscribe to core events
            await self._subscribe_to_events()

            # Initialize database if available
            if self.database_manager:
                await self.database_manager.initialize_database()

            # Initialize screenshot manager if available
            if self.screenshot_manager:
                await self.screenshot_manager.initialize()

            # Initialize UI manager if available
            if self.ui_manager:
                ui_success = await self.ui_manager.initialize()
                if not ui_success:
                    logger.warning("UI manager initialization failed, continuing without UI components")

            # Initialize HotkeyHandler
            self.hotkey_handler = HotkeyHandler(
                event_bus=self.event_bus,
                settings_manager=self.settings_manager
            )

            # Initialize hotkey system
            hotkey_success = await self.hotkey_handler.initialize_handlers()
            if not hotkey_success:
                logger.warning("Hotkey handler initialization failed, continuing without hotkeys")

            # Set state to ready
            self._app_state = AppState.READY
            self._initialized = True

            # Emit ready event
            await self.event_bus.emit(
                EventTypes.APP_STATE_CHANGED,
                {
                    'old_state': AppState.STARTING,
                    'new_state': self._app_state,
                    'timestamp': datetime.now().isoformat()
                },
                source="MainController"
            )

            logger.info("MainController initialization complete")
            return True

        except Exception as e:
            logger.error("MainController initialization failed: %s", e)
            self._app_state = AppState.ERROR
            return False

    async def _subscribe_to_events(self) -> None:
        """Subscribe to application events."""
        # Hotkey events
        await self.event_bus.subscribe(
            EventTypes.HOTKEY_SCREENSHOT_CAPTURE,
            self._handle_screenshot_hotkey,
            priority=100,
            weak_ref=False
        )

        await self.event_bus.subscribe(
            EventTypes.HOTKEY_OVERLAY_TOGGLE,
            self._handle_overlay_hotkey,
            priority=100,
            weak_ref=False
        )

        await self.event_bus.subscribe(
            EventTypes.HOTKEY_SETTINGS_OPEN,
            self._handle_settings_hotkey,
            priority=100,
            weak_ref=False
        )

        # Tray events
        await self.event_bus.subscribe(
            EventTypes.TRAY_SETTINGS_REQUESTED,
            self._handle_tray_settings_request,
            priority=90,
            weak_ref=False
        )

        await self.event_bus.subscribe(
            EventTypes.TRAY_OVERLAY_TOGGLE,
            self._handle_tray_overlay_request,
            priority=90,
            weak_ref=False
        )

        await self.event_bus.subscribe(
            EventTypes.TRAY_QUIT_REQUESTED,
            self._handle_quit_request,
            priority=100,
            weak_ref=False
        )

        # Settings events
        await self.event_bus.subscribe(
            EventTypes.SETTINGS_UPDATED,
            self._handle_settings_updated,
            priority=80,
            weak_ref=False
        )

        # Error events
        await self.event_bus.subscribe(
            EventTypes.ERROR_OCCURRED,
            self._handle_error,
            priority=50,
            weak_ref=False
        )

    async def _handle_screenshot_hotkey(self, event_data) -> None:
        """
        Handle screenshot capture hotkey.

        Args:
            event_data: Event data from hotkey trigger
        """
        try:
            logger.info("Screenshot hotkey triggered: %s",
                       event_data.data.get('combination', 'unknown'))

            # Mock screenshot capture implementation
            await self._mock_screenshot_capture(event_data.data)

            # Emit screenshot captured event
            await self.event_bus.emit(
                EventTypes.SCREENSHOT_CAPTURED,
                {
                    'trigger_source': 'hotkey',
                    'hotkey_combination': event_data.data.get('combination'),
                    'timestamp': event_data.data.get('timestamp'),
                    'mock_result': 'screenshot_captured_successfully'
                },
                source="MainController"
            )

        except Exception as e:
            logger.error("Error handling screenshot hotkey: %s", e)
            await self._emit_error("screenshot_hotkey_failed", str(e))

    async def _handle_overlay_hotkey(self, event_data) -> None:
        """
        Handle overlay toggle hotkey.

        Args:
            event_data: Event data from hotkey trigger
        """
        try:
            combination = event_data.data.get('combination', 'unknown')
            logger.info("Overlay hotkey triggered: %s", combination)

            # Use real UI manager if available, otherwise mock
            if self.ui_manager:
                # Check if overlay is currently visible
                is_visible = False
                if hasattr(self.ui_manager, 'overlay_manager') and self.ui_manager.overlay_manager:
                    is_visible = self.ui_manager.overlay_manager.is_overlay_visible()

                if is_visible:
                    # Hide overlay if it's visible
                    await self.ui_manager.hide_overlay(reason="hotkey_toggle")
                else:
                    # Show overlay if it's not visible
                    await self.ui_manager.show_overlay()
            else:
                # Mock overlay toggle implementation
                await self._mock_overlay_toggle(event_data.data)

            # Emit overlay event
            await self.event_bus.emit(
                EventTypes.UI_OVERLAY_SHOW,
                {
                    'trigger_source': 'hotkey',
                    'hotkey_combination': event_data.data.get('combination'),
                    'timestamp': event_data.data.get('timestamp'),
                    'mock_result': 'overlay_toggled_successfully'
                },
                source="MainController"
            )

        except Exception as e:
            logger.error("Error handling overlay hotkey: %s", e)
            await self._emit_error("overlay_hotkey_failed", str(e))

    async def _handle_settings_hotkey(self, event_data) -> None:
        """
        Handle settings hotkey.

        Args:
            event_data: Event data from hotkey trigger
        """
        try:
            logger.info("Settings hotkey triggered: %s",
                       event_data.data.get('combination', 'unknown'))

            # Mock settings window opening
            await self._mock_settings_open(event_data.data)

            # Emit settings show event
            await self.event_bus.emit(
                EventTypes.UI_SETTINGS_SHOW,
                {
                    'trigger_source': 'hotkey',
                    'hotkey_combination': event_data.data.get('combination'),
                    'timestamp': event_data.data.get('timestamp'),
                    'mock_result': 'settings_window_opened'
                },
                source="MainController"
            )

        except Exception as e:
            logger.error("Error handling settings hotkey: %s", e)
            await self._emit_error("settings_hotkey_failed", str(e))

    async def _handle_tray_settings_request(self, event_data) -> None:
        """Handle settings request from tray."""
        try:
            logger.info("Settings requested from tray")

            # Mock settings window opening
            await self._mock_settings_open({'trigger_source': 'tray'})

            await self.event_bus.emit(
                EventTypes.UI_SETTINGS_SHOW,
                {
                    'trigger_source': 'tray',
                    'mock_result': 'settings_window_opened'
                },
                source="MainController"
            )

        except Exception as e:
            logger.error("Error handling tray settings request: %s", e)
            await self._emit_error("tray_settings_failed", str(e))

    async def _handle_tray_overlay_request(self, event_data) -> None:
        """Handle overlay request from tray."""
        try:
            logger.info("Overlay requested from tray")

            # Use real UI manager if available, otherwise mock
            if self.ui_manager:
                await self.ui_manager.show_overlay()
            else:
                # Mock overlay toggle
                await self._mock_overlay_toggle({'trigger_source': 'tray'})

            await self.event_bus.emit(
                EventTypes.UI_OVERLAY_SHOW,
                {
                    'trigger_source': 'tray',
                    'mock_result': 'overlay_toggled_successfully'
                },
                source="MainController"
            )

        except Exception as e:
            logger.error("Error handling tray overlay request: %s", e)
            await self._emit_error("tray_overlay_failed", str(e))

    async def _handle_quit_request(self, event_data) -> None:
        """Handle application quit request."""
        try:
            logger.info("Quit requested from %s", event_data.source)

            # Emit shutdown request
            await self.event_bus.emit(
                EventTypes.APP_SHUTDOWN_REQUESTED,
                {
                    'trigger_source': event_data.source,
                    'reason': 'user_request'
                },
                source="MainController"
            )

        except Exception as e:
            logger.error("Error handling quit request: %s", e)

    async def _handle_settings_updated(self, event_data) -> None:
        """Handle settings update events."""
        try:
            settings_data = event_data.data or {}
            key = settings_data.get('key', 'unknown')

            logger.debug("Settings updated: %s", key)

            # Handle hotkey-specific settings
            if key.startswith('hotkeys.'):
                if self.hotkey_handler:
                    # Hotkey handler will receive this event and reload automatically
                    logger.debug("Hotkey settings update detected, handler will reload")

        except Exception as e:
            logger.error("Error handling settings update: %s", e)

    async def _handle_error(self, event_data) -> None:
        """Handle error events."""
        try:
            error_data = event_data.data or {}
            error_type = error_data.get('error', 'unknown_error')
            source = error_data.get('source', 'unknown')

            logger.error("Error occurred in %s: %s", source, error_type)

            # Update tray icon if available
            if self.tray_manager:
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    self.tray_manager.update_status,
                    'error',
                    f"Error: {error_type}"
                )

        except Exception as e:
            logger.error("Error in error handler: %s", e)

    async def _mock_screenshot_capture(self, trigger_data: Dict[str, Any]) -> None:
        """
        Mock screenshot capture implementation.

        Args:
            trigger_data: Data from trigger event
        """
        logger.info("MOCK: Starting screenshot capture...")
        logger.info("MOCK: Trigger source: %s", trigger_data.get('trigger_source', 'unknown'))

        if 'hotkey_combination' in trigger_data:
            logger.info("MOCK: Triggered by hotkey: %s", trigger_data['hotkey_combination'])

        # Use actual screenshot manager if available
        if self.screenshot_manager:
            try:
                result = await self.screenshot_manager.capture_screenshot()
                if result.success and result.metadata:
                    logger.info("REAL: Screenshot captured successfully: %s", result.metadata.filename)
                else:
                    logger.error("REAL: Screenshot capture failed: %s", result.error_message)
            except Exception as e:
                logger.error("Error capturing screenshot: %s", e)
        else:
            # Simulate processing delay
            await asyncio.sleep(0.1)
            logger.info("MOCK: Screenshot captured successfully")
            logger.info("MOCK: File saved to: screenshots/mock_screenshot.png")
            logger.info("MOCK: Thumbnail generated")
            logger.info("MOCK: Database entry created")

    async def _mock_overlay_toggle(self, trigger_data: Dict[str, Any]) -> None:
        """
        Mock overlay toggle implementation.

        Args:
            trigger_data: Data from trigger event
        """
        logger.info("MOCK: Toggling overlay window...")

        if 'hotkey_combination' in trigger_data:
            logger.info("MOCK: Triggered by hotkey: %s", trigger_data['hotkey_combination'])

        # Simulate state toggle
        await asyncio.sleep(0.05)

        logger.info("MOCK: Overlay window toggled successfully")

    async def _mock_settings_open(self, trigger_data: Dict[str, Any]) -> None:
        """
        Mock settings window opening.

        Args:
            trigger_data: Data from trigger event
        """
        logger.info("MOCK: Opening settings window...")
        logger.info("MOCK: Trigger source: %s", trigger_data.get('trigger_source', 'unknown'))

        if 'hotkey_combination' in trigger_data:
            logger.info("MOCK: Triggered by hotkey: %s", trigger_data['hotkey_combination'])

        # Simulate window creation
        await asyncio.sleep(0.05)

        logger.info("MOCK: Settings window opened successfully")
        logger.info("MOCK: Configuration panels loaded")
        logger.info("MOCK: Hotkey assignments displayed")

    async def _emit_error(self, error_type: str, error_message: str) -> None:
        """
        Emit error event.

        Args:
            error_type: Type of error
            error_message: Error message
        """
        await self.event_bus.emit(
            EventTypes.ERROR_OCCURRED,
            {
                'error': error_type,
                'message': error_message,
                'source': 'MainController',
                'timestamp': datetime.now().isoformat()
            },
            source="MainController"
        )

    async def get_application_status(self) -> Dict[str, Any]:
        """
        Get current application status.

        Returns:
            Dictionary with application status information
        """
        status = {
            'initialized': self._initialized,
            'state': self._app_state,
            'components': {
                'event_bus': self.event_bus is not None,
                'settings_manager': self.settings_manager is not None,
                'database_manager': self.database_manager is not None,
                'screenshot_manager': self.screenshot_manager is not None and self.screenshot_manager.is_initialized,
                'hotkey_handler': self.hotkey_handler is not None and self.hotkey_handler.is_handler_active(),
                'tray_manager': self.tray_manager is not None,
                'ui_manager': self.ui_manager is not None and self.ui_manager.is_initialized,
                'auto_start_manager': self.auto_start_manager is not None
            }
        }

        # Add hotkey status if available
        if self.hotkey_handler:
            try:
                status['hotkeys'] = {
                    'registered': self.hotkey_handler.get_registered_hotkeys(),
                    'conflicts': len(self.hotkey_handler.get_conflict_report()),
                    'handler_active': self.hotkey_handler.is_handler_active()
                }
            except Exception as e:
                logger.error("Error getting hotkey status: %s", e)
                status['hotkeys'] = {'error': str(e)}

        return status

    async def shutdown(self) -> None:
        """Shutdown all controllers and components."""
        if not self._initialized:
            return

        logger.info("Shutting down MainController...")

        try:
            # Update state
            old_state = self._app_state
            self._app_state = AppState.SHUTTING_DOWN

            await self.event_bus.emit(
                EventTypes.APP_STATE_CHANGED,
                {
                    'old_state': old_state,
                    'new_state': self._app_state,
                    'timestamp': datetime.now().isoformat()
                },
                source="MainController"
            )

            # Shutdown hotkey handler
            if self.hotkey_handler:
                await self.hotkey_handler.shutdown_handlers()

            # Shutdown UI manager
            if self.ui_manager:
                await self.ui_manager.shutdown()

            # Save any pending settings
            try:
                await self.settings_manager.save_settings()
            except Exception as e:
                logger.error("Error saving settings during shutdown: %s", e)

            self._initialized = False
            logger.info("MainController shutdown complete")

        except Exception as e:
            logger.error("Error during MainController shutdown: %s", e)

    def __str__(self) -> str:
        """String representation."""
        return (f"MainController(initialized={self._initialized}, "
                f"state={self._app_state}, "
                f"hotkeys_active={self.hotkey_handler.is_handler_active() if self.hotkey_handler else False})")
