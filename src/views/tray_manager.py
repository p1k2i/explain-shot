"""
Tray Manager Module

Implements system tray icon management with pystray, context menu handling,
and event integration following the MVC architecture pattern.
"""

import logging
import asyncio
import threading
from typing import Optional, Dict, Any, Callable, List
from enum import Enum
try:
    import pystray
    from pystray import MenuItem as Item
    PYSTRAY_AVAILABLE = True
except ImportError:
    # Handle case where pystray is not available
    pystray = None
    Item = None
    PYSTRAY_AVAILABLE = False
from PIL import Image
import io

from ..controllers.event_bus import get_event_bus
from ..utils.icon_manager import get_icon_manager
from .. import EventTypes, IconState as AppIconState

logger = logging.getLogger(__name__)


class MenuItemType(Enum):
    """Menu item type enumeration."""
    ACTION = "action"
    SEPARATOR = "separator"
    SUBMENU = "submenu"
    CHECKABLE = "checkable"


class TrayMenuAction(Enum):
    """Tray menu action enumeration."""
    TAKE_SCREENSHOT = "take_screenshot"
    SHOW_GALLERY = "show_gallery"
    SHOW_OVERLAY = "show_overlay"
    OPEN_SETTINGS = "open_settings"
    TOGGLE_AUTO_START = "toggle_auto_start"
    ABOUT = "about"
    EXIT = "exit"


class TrayManager:
    """
    System tray icon manager using pystray.

    Provides system tray integration with context menu, icon state management,
    and event-driven communication with the application controller.
    """

    def __init__(
        self,
        app_name: str = "Explain Screenshot",
        tooltip: str = "Explain Screenshot - AI-powered screenshot analysis"
    ):
        """
        Initialize TrayManager.

        Args:
            app_name: Application name for tray icon
            tooltip: Tooltip text for tray icon
        """
        self.app_name = app_name
        self.tooltip = tooltip

        # Tray components
        self._icon = None  # pystray.Icon instance
        self._current_state = AppIconState.IDLE
        self._is_running = False
        self._shutdown_requested = False

        # Event system
        self._event_bus = get_event_bus()
        self._icon_manager = get_icon_manager()

        # Threading
        self._tray_thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # Menu configuration
        self._menu_items: List[Dict[str, Any]] = []
        self._setup_default_menu()

        # Status tracking
        self._settings: Dict[str, Any] = {}

        logger.info("TrayManager initialized: %s", app_name)

    def _setup_default_menu(self) -> None:
        """Set up the default context menu structure."""
        self._menu_items = [
            {
                'text': '📸 Take Screenshot',
                'action': TrayMenuAction.TAKE_SCREENSHOT,
                'type': MenuItemType.ACTION,
                'enabled': True,
                'tooltip': 'Capture a screenshot'
            },
            {
                'text': '🖼️ Show Gallery',
                'action': TrayMenuAction.SHOW_GALLERY,
                'type': MenuItemType.ACTION,
                'enabled': True,
                'tooltip': 'Open screenshot gallery'
            },
            {
                'text': '👁️ Show Overlay',
                'action': TrayMenuAction.SHOW_OVERLAY,
                'type': MenuItemType.ACTION,
                'enabled': True,
                'tooltip': 'Show overlay window'
            },
            {
                'type': MenuItemType.SEPARATOR
            },
            {
                'text': '⚙️ Settings',
                'action': TrayMenuAction.OPEN_SETTINGS,
                'type': MenuItemType.ACTION,
                'enabled': True,
                'tooltip': 'Open application settings'
            },
            {
                'text': '🚀 Auto-start',
                'action': TrayMenuAction.TOGGLE_AUTO_START,
                'type': MenuItemType.CHECKABLE,
                'checked': False,
                'enabled': True,
                'tooltip': 'Toggle auto-start on Windows boot'
            },
            {
                'type': MenuItemType.SEPARATOR
            },
            {
                'text': 'About',
                'action': TrayMenuAction.ABOUT,
                'type': MenuItemType.ACTION,
                'enabled': True,
                'tooltip': 'About this application'
            },
            {
                'text': 'Exit',
                'action': TrayMenuAction.EXIT,
                'type': MenuItemType.ACTION,
                'enabled': True,
                'tooltip': 'Exit application'
            }
        ]

    async def initialize_async(self) -> bool:
        """
        Initialize tray manager asynchronously.

        Returns:
            True if initialization was successful
        """
        if not PYSTRAY_AVAILABLE:
            logger.error("pystray library not available - tray functionality disabled")
            return False

        try:
            # Store the current event loop
            self._loop = asyncio.get_event_loop()

            # Subscribe to events
            await self._subscribe_to_events()

            # Preload icons
            self._icon_manager.preload_icons(
                states=[AppIconState.IDLE, AppIconState.CAPTURING,
                       AppIconState.PROCESSING, AppIconState.ERROR,
                       AppIconState.DISABLED],
                sizes=['tray']
            )

            # Start tray in separate thread
            self._start_tray_thread()

            # Wait for tray to be ready
            await self._wait_for_tray_ready()

            logger.info("TrayManager initialized successfully")
            return True

        except Exception as e:
            logger.error("Failed to initialize TrayManager: %s", e)
            return False

    async def _subscribe_to_events(self) -> None:
        """Subscribe to relevant application events."""
        await self._event_bus.subscribe(
            EventTypes.APP_STATE_CHANGED,
            self._handle_app_state_changed
        )

        await self._event_bus.subscribe(
            EventTypes.SCREENSHOT_COMPLETED,
            self._handle_screenshot_completed
        )

        await self._event_bus.subscribe(
            EventTypes.ERROR_OCCURRED,
            self._handle_error_occurred
        )

        await self._event_bus.subscribe(
            EventTypes.SETTINGS_CHANGED,
            self._handle_settings_changed
        )

    def _start_tray_thread(self) -> None:
        """Start the system tray in a separate thread."""
        self._tray_thread = threading.Thread(
            target=self._run_tray,
            name="TrayThread",
            daemon=True
        )
        self._tray_thread.start()

    def _run_tray(self) -> None:
        """Run the system tray (called in separate thread)."""
        if not PYSTRAY_AVAILABLE or not pystray:
            logger.error("Cannot run tray: pystray not available")
            return

        try:
            # Load initial icon
            icon_data = self._icon_manager.load_icon(self._current_state, 'tray')
            if icon_data is None:
                logger.error("Failed to load initial tray icon")
                return

            # Create PIL image from icon data
            icon_image = Image.open(io.BytesIO(icon_data))

            # Create tray icon
            self._icon = pystray.Icon(
                name=self.app_name,
                icon=icon_image,
                title=self.tooltip,
                menu=self._build_menu()
            )

            # Set up icon event handlers
            self._icon.visible = True

            # Mark as running
            self._is_running = True

            # Run the tray (this blocks until stopped)
            self._icon.run()

        except Exception as e:
            logger.error("Error running system tray: %s", e)
        finally:
            self._is_running = False

    async def _wait_for_tray_ready(self, timeout: float = 5.0) -> None:
        """
        Wait for tray to be ready.

        Args:
            timeout: Maximum time to wait
        """
        start_time = asyncio.get_event_loop().time()

        while not self._is_running:
            if asyncio.get_event_loop().time() - start_time > timeout:
                raise TimeoutError("Tray initialization timeout")

            await asyncio.sleep(0.1)

    def _build_menu(self):
        """
        Build the context menu from menu items configuration.

        Returns:
            pystray.Menu object
        """
        if not PYSTRAY_AVAILABLE or not pystray:
            return None

        menu_items = []

        for item_config in self._menu_items:
            if item_config['type'] == MenuItemType.SEPARATOR:
                menu_items.append(pystray.Menu.SEPARATOR)

            elif item_config['type'] == MenuItemType.ACTION:
                if Item:  # Check if Item is available
                    menu_items.append(
                        Item(
                            item_config['text'],
                            self._create_menu_handler(item_config['action']),
                            enabled=item_config.get('enabled', True)
                        )
                    )

            elif item_config['type'] == MenuItemType.CHECKABLE:
                if Item:  # Check if Item is available
                    menu_items.append(
                        Item(
                            item_config['text'],
                            self._create_menu_handler(item_config['action']),
                            checked=lambda item_cfg=item_config: item_cfg.get('checked', False),
                            enabled=item_config.get('enabled', True)
                        )
                    )

        return pystray.Menu(*menu_items)

    def _create_menu_handler(self, action: TrayMenuAction) -> Callable:
        """
        Create a menu item handler for the specified action.

        Args:
            action: Menu action to handle

        Returns:
            Handler function
        """
        def handler(icon, item):
            if self._loop and not self._loop.is_closed():
                # Schedule the async handler in the main loop
                asyncio.run_coroutine_threadsafe(
                    self._handle_menu_action(action, icon, item),
                    self._loop
                )

        return handler

    async def _handle_menu_action(
        self,
        action: TrayMenuAction,
        icon,  # pystray.Icon
        item   # pystray.MenuItem
    ) -> None:
        """
        Handle menu action asynchronously.

        Args:
            action: Menu action that was triggered
            icon: Tray icon instance
            item: Menu item that was clicked
        """
        try:
            logger.debug("Menu action triggered: %s", action.value)

            # Emit appropriate events based on action
            if action == TrayMenuAction.TAKE_SCREENSHOT:
                await self._event_bus.emit(
                    EventTypes.SCREENSHOT_CAPTURE_REQUESTED,
                    source="tray"
                )

            elif action == TrayMenuAction.SHOW_GALLERY:
                await self._event_bus.emit(
                    EventTypes.UI_GALLERY_SHOW,
                    source="tray"
                )

            elif action == TrayMenuAction.SHOW_OVERLAY:
                await self._event_bus.emit(
                    EventTypes.UI_OVERLAY_SHOW,
                    source="tray"
                )

            elif action == TrayMenuAction.OPEN_SETTINGS:
                await self._event_bus.emit(
                    EventTypes.UI_SETTINGS_SHOW,
                    source="tray"
                )

            elif action == TrayMenuAction.TOGGLE_AUTO_START:
                await self._event_bus.emit(
                    EventTypes.SETTINGS_UPDATED,
                    {
                        'key': 'auto_start.enabled',
                        'value': not self._settings.get('auto_start_enabled', False)
                    },
                    source="tray"
                )

            elif action == TrayMenuAction.ABOUT:
                await self._event_bus.emit(
                    EventTypes.TRAY_MENU_SELECTED,
                    {'action': 'about'},
                    source="tray"
                )

            elif action == TrayMenuAction.EXIT:
                await self._event_bus.emit(
                    EventTypes.APP_SHUTDOWN_REQUESTED,
                    source="tray"
                )

            else:
                logger.warning("Unknown menu action: %s", action)

        except Exception as e:
            logger.error("Error handling menu action '%s': %s", action, e)

    async def update_icon_state(self, state: str) -> None:
        """
        Update the tray icon state.

        Args:
            state: New icon state
        """
        if not self._is_running or self._icon is None:
            logger.warning("Cannot update icon state: tray not running")
            return

        try:
            self._current_state = state

            # Load new icon
            icon_data = self._icon_manager.load_icon(state, 'tray')
            if icon_data is None:
                logger.warning("Failed to load icon for state: %s", state)
                return

            # Update icon in tray thread
            icon_image = Image.open(io.BytesIO(icon_data))

            # Update icon (this needs to be called from tray thread)
            def update_icon():
                if self._icon:
                    self._icon.icon = icon_image

            # Schedule update in tray thread
            if self._tray_thread and self._tray_thread.is_alive():
                # For pystray, we need to update the icon property directly
                self._icon.icon = icon_image

            logger.debug("Icon state updated to: %s", state)

        except Exception as e:
            logger.error("Failed to update icon state to '%s': %s", state, e)

    async def show_notification(
        self,
        message: str,
        title: Optional[str] = None,
        duration: int = 3000
    ) -> None:
        """
        Show a system notification via the tray icon.

        Args:
            message: Notification message
            title: Notification title (uses app name if None)
            duration: Duration in milliseconds
        """
        if not self._is_running or self._icon is None:
            logger.warning("Cannot show notification: tray not running")
            return

        try:
            notification_title = title or self.app_name

            # Show notification using pystray
            def show_notify():
                if self._icon:
                    self._icon.notify(message, notification_title)

            # Schedule notification in tray thread
            if self._tray_thread and self._tray_thread.is_alive():
                show_notify()

            logger.debug("Notification shown: %s", message)

        except Exception as e:
            logger.error("Failed to show notification: %s", e)

    async def update_menu(self, force_rebuild: bool = False) -> None:
        """
        Update the context menu.

        Args:
            force_rebuild: Whether to force a complete menu rebuild
        """
        if not self._is_running or self._icon is None:
            return

        try:
            # Update menu items based on current settings
            for item in self._menu_items:
                if item.get('action') == TrayMenuAction.TOGGLE_AUTO_START:
                    item['checked'] = self._settings.get('auto_start_enabled', False)

            # Rebuild menu if needed
            if force_rebuild:
                def update_menu():
                    if self._icon:
                        self._icon.menu = self._build_menu()

                update_menu()

            logger.debug("Menu updated")

        except Exception as e:
            logger.error("Failed to update menu: %s", e)

    async def shutdown_async(self) -> None:
        """Shutdown the tray manager gracefully."""
        if self._shutdown_requested:
            return

        self._shutdown_requested = True
        logger.info("Shutting down TrayManager...")

        try:
            # Stop the tray icon
            if self._icon and self._is_running:
                def stop_tray():
                    try:
                        if self._icon and hasattr(self._icon, 'stop'):
                            self._icon.stop()
                    except Exception as e:
                        logger.error("Error stopping tray icon: %s", e)

                stop_tray()

            # Wait for tray thread to finish
            if self._tray_thread and self._tray_thread.is_alive():
                self._tray_thread.join(timeout=2.0)

            # Clear references
            self._icon = None
            self._is_running = False

            logger.info("TrayManager shutdown complete")

        except Exception as e:
            logger.error("Error during TrayManager shutdown: %s", e)

    async def _handle_app_state_changed(self, event_data) -> None:
        """Handle application state change events."""
        if event_data.data and 'state' in event_data.data:
            new_state = event_data.data['state']
            await self.update_icon_state(new_state)

    async def _handle_screenshot_completed(self, event_data) -> None:
        """Handle screenshot completion events."""
        await self.show_notification(
            "Screenshot captured successfully",
            "Screenshot"
        )

        # Return to idle state
        await self.update_icon_state(AppIconState.IDLE)

    async def _handle_error_occurred(self, event_data) -> None:
        """Handle error events."""
        if event_data.data and 'error' in event_data.data:
            await self.show_notification(
                f"Error: {event_data.data['error']}",
                "Error"
            )

            # Show error state briefly
            await self.update_icon_state(AppIconState.ERROR)
            await asyncio.sleep(2)
            await self.update_icon_state(AppIconState.IDLE)

    async def _handle_settings_changed(self, event_data) -> None:
        """Handle settings change events."""
        if event_data.data:
            # Update internal settings cache
            if 'auto_start_enabled' in event_data.data:
                self._settings['auto_start_enabled'] = event_data.data['auto_start_enabled']

            # Update menu
            await self.update_menu()

    def is_tray_available(self) -> bool:
        """
        Check if system tray is available.

        Returns:
            True if system tray is supported
        """
        try:
            # Try to check if system tray is available
            # This is a simple check - in practice, pystray handles this
            return True
        except Exception:
            return False

    def is_running(self) -> bool:
        """
        Check if tray manager is running.

        Returns:
            True if tray is running
        """
        return self._is_running

    def get_status(self) -> Dict[str, Any]:
        """
        Get tray manager status.

        Returns:
            Dictionary with status information
        """
        return {
            'running': self._is_running,
            'current_state': self._current_state,
            'tray_available': self.is_tray_available(),
            'shutdown_requested': self._shutdown_requested,
            'thread_alive': self._tray_thread.is_alive() if self._tray_thread else False,
            'menu_items_count': len(self._menu_items)
        }
