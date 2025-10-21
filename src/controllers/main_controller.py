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
from src.models.preset_manager import PresetManager
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
        preset_manager: Optional[PresetManager] = None,
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
            preset_manager: PresetManager for preset operations
            tray_manager: Optional TrayManager instance
            ui_manager: Optional UIManager instance for PyQt6 UI components
            auto_start_manager: Optional AutoStartManager instance
        """
        self.event_bus = event_bus
        self.settings_manager = settings_manager
        self.database_manager = database_manager
        self.screenshot_manager = screenshot_manager
        self.preset_manager = preset_manager
        self.tray_manager = tray_manager
        self.ui_manager = ui_manager
        self.auto_start_manager = auto_start_manager

        # Controllers
        self.hotkey_handler: Optional[HotkeyHandler] = None

        # State
        self._initialized = False
        self._app_state = AppState.STARTING

        logger.debug("MainController initialized")

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
            logger.debug("Initializing MainController...")

            # Subscribe to core events
            await self._subscribe_to_events()

            # Initialize database if available
            if self.database_manager:
                await self.database_manager.initialize_database()

            # Initialize screenshot manager if available
            if self.screenshot_manager:
                await self.screenshot_manager.initialize()

            # Initialize preset manager if available
            if self.preset_manager:
                await self.preset_manager.initialize()
                logger.debug("Preset manager initialized")

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

            logger.debug("MainController initialization complete")
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
            priority=100
        )

        await self.event_bus.subscribe(
            EventTypes.HOTKEY_OVERLAY_TOGGLE,
            self._handle_overlay_hotkey,
            priority=100
        )

        await self.event_bus.subscribe(
            EventTypes.HOTKEY_SETTINGS_OPEN,
            self._handle_settings_hotkey,
            priority=100
        )

        # Tray events
        await self.event_bus.subscribe(
            EventTypes.SCREENSHOT_CAPTURE_REQUESTED,
            self._handle_screenshot_capture_request,
            priority=90
        )

        await self.event_bus.subscribe(
            EventTypes.TRAY_SETTINGS_REQUESTED,
            self._handle_tray_settings_request,
            priority=90
        )

        await self.event_bus.subscribe(
            EventTypes.TRAY_OVERLAY_TOGGLE,
            self._handle_tray_overlay_request,
            priority=90
        )

        await self.event_bus.subscribe(
            EventTypes.TRAY_QUIT_REQUESTED,
            self._handle_quit_request,
            priority=100
        )

        await self.event_bus.subscribe(
            EventTypes.TRAY_ABOUT_REQUESTED,
            self._handle_about_action,
            priority=90
        )

        # Settings events
        await self.event_bus.subscribe(
            EventTypes.SETTINGS_UPDATED,
            self._handle_settings_updated,
            priority=80
        )

        # Error events
        await self.event_bus.subscribe(
            EventTypes.ERROR_OCCURRED,
            self._handle_error,
            priority=50
        )

    async def _handle_screenshot_capture_request(self, event_data) -> None:
        """
        Handle screenshot capture request from tray or other sources.

        Args:
            event_data: Event data from capture request
        """
        try:
            source = event_data.source or 'unknown'
            logger.info("Screenshot capture requested from: %s", source)

            # Perform real screenshot capture
            result = await self._capture_screenshot_real({
                'trigger_source': source,
                'timestamp': event_data.timestamp
            })

            if result and result.get('success', False):
                # Emit screenshot captured event with real metadata
                await self.event_bus.emit(
                    EventTypes.SCREENSHOT_CAPTURED,
                    {
                        'trigger_source': source,
                        'timestamp': event_data.timestamp,
                        'result': result,
                        'metadata': result.get('metadata', {}),
                        'file_path': result.get('file_path', ''),
                        'capture_duration': result.get('capture_duration', 0),
                        'success': True
                    },
                    source="MainController"
                )
                logger.debug("Screenshot captured successfully from %s: %s",
                          source, result.get('filename', 'unknown'))
            else:
                # Handle capture failure
                error_msg = result.get('error_message', 'Unknown error') if result else 'Screenshot manager unavailable'
                await self._emit_error("screenshot_capture_failed", error_msg)

                await self.event_bus.emit(
                    EventTypes.SCREENSHOT_CAPTURED,
                    {
                        'trigger_source': source,
                        'timestamp': event_data.timestamp,
                        'success': False,
                        'error_message': error_msg
                    },
                    source="MainController"
                )

        except Exception as e:
            logger.error("Error handling screenshot capture request: %s", e)
            await self._emit_error("screenshot_capture_request_failed", str(e))

    async def _handle_screenshot_hotkey(self, event_data) -> None:
        """
        Handle screenshot capture hotkey.

        Args:
            event_data: Event data from hotkey trigger
        """
        try:
            combination = event_data.data.get('combination', 'unknown')
            logger.info("Screenshot hotkey triggered: %s", combination)

            # Perform real screenshot capture
            result = await self._capture_screenshot_real(event_data.data)

            if result and result.get('success', False):
                # Emit screenshot captured event with real metadata
                await self.event_bus.emit(
                    EventTypes.SCREENSHOT_CAPTURED,
                    {
                        'trigger_source': 'hotkey',
                        'hotkey_combination': combination,
                        'timestamp': event_data.data.get('timestamp'),
                        'result': result,
                        'metadata': result.get('metadata', {}),
                        'file_path': result.get('file_path', ''),
                        'capture_duration': result.get('capture_duration', 0),
                        'success': True
                    },
                    source="MainController"
                )
                logger.debug("Screenshot captured successfully via hotkey: %s",
                          result.get('filename', 'unknown'))
            else:
                # Handle capture failure
                error_msg = result.get('error_message', 'Unknown error') if result else 'Screenshot manager unavailable'
                await self._emit_error("screenshot_capture_failed", error_msg)

                await self.event_bus.emit(
                    EventTypes.SCREENSHOT_CAPTURED,
                    {
                        'trigger_source': 'hotkey',
                        'hotkey_combination': combination,
                        'timestamp': event_data.data.get('timestamp'),
                        'success': False,
                        'error_message': error_msg
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
                logger.error("UI manager not available, cannot toggle overlay via hotkey")

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
                logger.error("UI manager not available, cannot show overlay from tray")

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


    async def _handle_about_action(self, event_data) -> None:
        """Handle the About menu action by opening the project URL in browser."""
        try:
            import webbrowser

            # Open the GitHub repository URL in the default browser
            url = "https://github.com/p1k2i/explain-shot"
            webbrowser.open(url)

            logger.info("Opened About URL in browser: %s", url)

        except Exception as e:
            logger.error("Error opening About URL: %s", e)
            await self._emit_error("about_url_open_failed", str(e))

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

    async def _capture_screenshot_real(self, trigger_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Real screenshot capture implementation.

        Args:
            trigger_data: Data from trigger event

        Returns:
            Dictionary with capture result and metadata, or None if failed
        """
        try:
            logger.debug("Starting screenshot capture...")

            if 'hotkey_combination' in trigger_data:
                logger.debug("Triggered by hotkey: %s", trigger_data['hotkey_combination'])

            # Check if screenshot manager is available
            if not self.screenshot_manager:
                logger.error("Screenshot manager not available")
                return {
                    'success': False,
                    'error_message': 'Screenshot manager not initialized'
                }

            # Perform the actual screenshot capture
            result = await self.screenshot_manager.capture_screenshot()

            if result.success and result.metadata:
                logger.debug("Screenshot captured successfully: %s", result.metadata.filename)

                return {
                    'success': True,
                    'filename': result.metadata.filename,
                    'file_path': result.metadata.full_path,
                    'file_size': result.metadata.file_size,
                    'resolution': result.metadata.resolution,
                    'capture_duration': result.capture_duration,
                    'save_duration': result.save_duration,
                    'total_duration': result.total_duration,
                    'metadata': {
                        'id': result.metadata.id,
                        'filename': result.metadata.filename,
                        'full_path': result.metadata.full_path,
                        'timestamp': result.metadata.timestamp.isoformat() if result.metadata.timestamp else None,
                        'file_size': result.metadata.file_size,
                        'resolution': result.metadata.resolution,
                        'format': result.metadata.format
                    }
                }
            else:
                error_msg = result.error_message or "Unknown capture error"
                logger.error("Screenshot capture failed: %s", error_msg)
                return {
                    'success': False,
                    'error_message': error_msg
                }

        except Exception as e:
            error_msg = f"Exception during screenshot capture: {e}"
            logger.error(error_msg)
            return {
                'success': False,
                'error_message': error_msg
            }

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
