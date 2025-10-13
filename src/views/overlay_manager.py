"""
Overlay Manager Module

Manages the lifecycle and state of the overlay window.
Coordinates data fetching, window positioning, and event handling.
"""

import asyncio
import logging
from typing import Optional, Dict, Any, List, Tuple
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QCursor

from ..controllers.event_bus import EventBus
from ..models.settings_manager import SettingsManager
from ..models.screenshot_manager import ScreenshotManager
from .overlay_window import OverlayWindow
from src import EventTypes

logger = logging.getLogger(__name__)


class OverlayManager(QObject):
    """
    Manages overlay window lifecycle and coordination.

    Handles window creation, data fetching, positioning,
    and communication with other application components.
    """

    # Signals for thread-safe communication
    overlay_action_requested = pyqtSignal(str, dict)

    def __init__(
        self,
        event_bus: EventBus,
        settings_manager: SettingsManager,
        screenshot_manager: Optional[ScreenshotManager] = None,
        parent: Optional[QObject] = None
    ):
        """
        Initialize OverlayManager.

        Args:
            event_bus: EventBus instance for communication
            settings_manager: SettingsManager for configuration
            screenshot_manager: Optional ScreenshotManager for data
            parent: Parent QObject
        """
        super().__init__(parent)

        self.event_bus = event_bus
        self.settings_manager = settings_manager
        self.screenshot_manager = screenshot_manager

        # Overlay window instance
        self.overlay_window: Optional[OverlayWindow] = None

        # State management
        self._initialized = False
        self._overlay_visible = False
        self._last_position: Optional[Tuple[int, int]] = None

        # Configuration cache
        self._config_cache: Dict[str, Any] = {}

        # Data cache for performance
        self._screenshot_cache: List[Dict[str, Any]] = []
        self._cache_timestamp = 0.0
        self._cache_duration = 30.0  # Cache for 30 seconds

        logger.info("OverlayManager initialized")

    @property
    def is_initialized(self) -> bool:
        """Check if overlay manager is initialized."""
        return self._initialized

    def is_overlay_visible(self) -> bool:
        """Check if overlay window is currently visible."""
        return self._overlay_visible and self.overlay_window is not None

    async def initialize(self) -> bool:
        """
        Initialize the overlay manager.

        Returns:
            True if initialization successful
        """
        if self._initialized:
            logger.warning("OverlayManager already initialized")
            return True

        try:
            logger.info("Initializing OverlayManager...")

            # Load configuration
            await self._load_configuration()

            # Subscribe to events
            await self._subscribe_to_events()

            self._initialized = True
            logger.info("OverlayManager initialization complete")

            return True

        except Exception as e:
            logger.error(f"OverlayManager initialization failed: {e}")
            return False

    async def _load_configuration(self) -> None:
        """Load overlay configuration from settings."""
        try:
            # Default overlay settings
            defaults = {
                "overlay.width": 280,
                "overlay.height": 400,
                "overlay.opacity": 0.92,
                "overlay.auto_hide_timeout": 10000,  # 10 seconds
                "overlay.position_mode": "cursor",  # "cursor" or "center"
                "overlay.screenshot_limit": 3,
                "overlay.theme": "dark"
            }

            # Load settings with defaults
            for key, default_value in defaults.items():
                self._config_cache[key] = await self.settings_manager.get_setting(key, default_value)

            logger.debug(f"Loaded overlay configuration: {self._config_cache}")

        except Exception as e:
            logger.error(f"Failed to load overlay configuration: {e}")
            # Use defaults if loading fails
            self._config_cache = {
                "overlay.width": 280,
                "overlay.height": 400,
                "overlay.opacity": 0.92,
                "overlay.auto_hide_timeout": 10000,
                "overlay.position_mode": "cursor",
                "overlay.screenshot_limit": 3,
                "overlay.theme": "dark"
            }

    async def _subscribe_to_events(self) -> None:
        """Subscribe to relevant events."""
        try:
            # Overlay-specific events
            await self.event_bus.subscribe(
                "overlay.item_selected",
                self._handle_item_selected,
                priority=100
            )

            await self.event_bus.subscribe(
                "overlay.dismissed",
                self._handle_overlay_dismissed,
                priority=100
            )

            # Screenshot events for cache invalidation
            await self.event_bus.subscribe(
                EventTypes.SCREENSHOT_CAPTURED,
                self.handle_screenshot_update,
                priority=90
            )

        except Exception as e:
            logger.error(f"Failed to subscribe to overlay events: {e}")

    async def show_overlay(self, position: Optional[Tuple[int, int]] = None, **kwargs) -> bool:
        """
        Show the overlay window.

        Args:
            position: Optional position override
            **kwargs: Additional parameters

        Returns:
            True if overlay shown successfully
        """
        try:
            logger.info("Showing overlay window...")

            # Create overlay window if needed (in main thread)
            if self.overlay_window is None:
                await self._ensure_overlay_window_created()

            if self.overlay_window is None:
                logger.error("Failed to create overlay window")
                return False

            # Fetch recent screenshots
            screenshot_data = await self._fetch_screenshot_data()

            # Get app functions data
            app_functions = self._get_app_functions()

            # Populate overlay with data
            self.overlay_window.populate_lists(app_functions, screenshot_data)

            # Position the window
            overlay_position = position or self._calculate_overlay_position()
            self.overlay_window.move(overlay_position[0], overlay_position[1])

            # Show the window
            self.overlay_window.show()
            self.overlay_window.raise_()
            self.overlay_window.activateWindow()

            # Process any pending events to ensure window is properly displayed
            from PyQt6.QtWidgets import QApplication
            app = QApplication.instance()
            if app:
                app.processEvents()

            self._overlay_visible = True
            self._last_position = overlay_position

            # Emit overlay shown event
            await self.event_bus.emit(
                "overlay.shown",
                {
                    "position": overlay_position,
                    "screenshot_count": len(screenshot_data),
                    "timestamp": asyncio.get_event_loop().time()
                },
                source="OverlayManager"
            )

            logger.info(f"Overlay window shown at position {overlay_position}")
            return True

        except Exception as e:
            logger.error(f"Error showing overlay window: {e}")
            return False

    async def hide_overlay(self, reason: str = "unknown", **kwargs) -> bool:
        """
        Hide the overlay window.

        Args:
            reason: Reason for hiding the overlay
            **kwargs: Additional parameters

        Returns:
            True if overlay hidden successfully
        """
        try:
            if not self._overlay_visible or self.overlay_window is None:
                return True

            logger.info(f"Hiding overlay window (reason: {reason})")

            # Hide the window
            self.overlay_window.hide()
            self._overlay_visible = False

            # Emit overlay hidden event
            await self.event_bus.emit(
                "overlay.hidden",
                {
                    "reason": reason,
                    "last_position": self._last_position,
                    "timestamp": asyncio.get_event_loop().time()
                },
                source="OverlayManager"
            )

            logger.info("Overlay window hidden")
            return True

        except Exception as e:
            logger.error(f"Error hiding overlay window: {e}")
            return False

    async def _ensure_overlay_window_created(self) -> None:
        """Ensure overlay window is created in the main thread."""
        try:
            # Create window synchronously - UIManager should ensure this is called from main thread
            self._create_overlay_window()

        except Exception as e:
            logger.error(f"Error ensuring overlay window creation: {e}")
            raise

    def _create_overlay_window(self) -> None:
        """Create the overlay window synchronously in main thread."""
        try:
            logger.info("Creating overlay window...")

            # Create window with configuration
            self.overlay_window = OverlayWindow(
                event_bus=self.event_bus,
                config=self._config_cache,
                parent=None  # Frameless window should be top-level
            )

            # Connect window signals
            self.overlay_window.item_selected.connect(self._on_window_item_selected)
            self.overlay_window.overlay_dismissed.connect(self._on_window_dismissed)

            logger.info("Overlay window created successfully")

        except Exception as e:
            logger.error(f"Failed to create overlay window: {e}")
            raise

    async def _fetch_screenshot_data(self) -> List[Dict[str, Any]]:
        """
        Fetch recent screenshot data for display.

        Returns:
            List of screenshot data dictionaries
        """
        try:
            current_time = asyncio.get_event_loop().time()

            # Check cache validity
            if (current_time - self._cache_timestamp) < self._cache_duration and self._screenshot_cache:
                logger.debug("Using cached screenshot data")
                return self._screenshot_cache

            # Fetch fresh data
            screenshot_limit = self._config_cache.get("overlay.screenshot_limit", 3)

            if self.screenshot_manager:
                try:
                    screenshots = await self.screenshot_manager.get_recent_screenshots(limit=screenshot_limit)

                    # Convert to display format
                    screenshot_data = []
                    for screenshot in screenshots:
                        screenshot_data.append({
                            "id": screenshot.id,
                            "filename": screenshot.filename,
                            "timestamp": screenshot.timestamp.isoformat(),
                            "file_size": screenshot.file_size,
                            "resolution": f"{screenshot.resolution[0]}x{screenshot.resolution[1]}" if screenshot.resolution else "Unknown"
                        })

                    # Update cache
                    self._screenshot_cache = screenshot_data
                    self._cache_timestamp = current_time

                    logger.debug(f"Fetched {len(screenshot_data)} recent screenshots")
                    return screenshot_data

                except Exception as e:
                    logger.error(f"Error fetching screenshots from manager: {e}")

            logger.error("ScreenshotManager not available, returning empty screenshot list")
            return []

        except Exception as e:
            logger.error(f"Error fetching screenshot data: {e}")
            return []

    def _get_app_functions(self) -> List[Dict[str, Any]]:
        """
        Get list of application functions for display.

        Returns:
            List of app function data dictionaries
        """
        return [
            {
                "id": "settings",
                "title": "📱 Open Settings",
                "description": "Configure application settings",
                "action": "open_settings"
            },
            {
                "id": "gallery",
                "title": "🖼️ Open Gallery",
                "description": "View screenshot gallery",
                "action": "open_gallery"
            }
        ]

    def _calculate_overlay_position(self) -> Tuple[int, int]:
        """
        Calculate optimal position for overlay window.

        Returns:
            Tuple of (x, y) coordinates
        """
        try:
            position_mode = self._config_cache.get("overlay.position_mode", "cursor")
            window_width = self._config_cache.get("overlay.width", 280)
            window_height = self._config_cache.get("overlay.height", 400)

            if position_mode == "cursor":
                # Position near cursor
                cursor_pos = QCursor.pos()

                # Offset to avoid cursor overlap
                x = cursor_pos.x() + 20
                y = cursor_pos.y() + 20

                # TODO: Add screen boundary checking
                # For now, use simple offset
                return (x, y)

            else:
                # Center of screen (fallback)
                # TODO: Get actual screen dimensions
                return (960 - window_width // 2, 540 - window_height // 2)

        except Exception as e:
            logger.error(f"Error calculating overlay position: {e}")
            # Fallback position
            return (100, 100)

    def _on_window_item_selected(self, item_type: str, item_data: Dict[str, Any]) -> None:
        """
        Handle item selection from overlay window.

        Args:
            item_type: Type of item selected ("function" or "screenshot")
            item_data: Data associated with the selected item
        """
        try:
            logger.info(f"Overlay item selected: {item_type} - {item_data}")

            # Create async task for event emission
            asyncio.create_task(self._handle_item_selection_async(item_type, item_data))

        except Exception as e:
            logger.error(f"Error handling window item selection: {e}")

    async def _handle_item_selection_async(self, item_type: str, item_data: Dict[str, Any]) -> None:
        """
        Handle item selection asynchronously.

        Args:
            item_type: Type of item selected
            item_data: Data associated with the selected item
        """
        try:
            # Emit selection event
            await self.event_bus.emit(
                "overlay.item_selected",
                {
                    "type": item_type,
                    "data": item_data,
                    "timestamp": asyncio.get_event_loop().time()
                },
                source="OverlayManager"
            )

            # Hide overlay after selection
            await self.hide_overlay(reason="item_selected")

        except Exception as e:
            logger.error(f"Error in async item selection handler: {e}")

    def _on_window_dismissed(self, reason: str) -> None:
        """
        Handle overlay window dismissal.

        Args:
            reason: Reason for dismissal
        """
        try:
            logger.info(f"Overlay window dismissed: {reason}")

            # Create async task for hiding
            asyncio.create_task(self.hide_overlay(reason=reason))

        except Exception as e:
            logger.error(f"Error handling window dismissal: {e}")

    async def _handle_item_selected(self, event_data) -> None:
        """
        Handle overlay item selection events.

        Args:
            event_data: Event data containing selection information
        """
        try:
            selection_data = event_data.data or {}
            item_type = selection_data.get("type", "unknown")
            item_data = selection_data.get("data", {})

            logger.info(f"Processing overlay item selection: {item_type}")

            if item_type == "function":
                await self._handle_function_selection(item_data)
            elif item_type == "screenshot":
                await self._handle_screenshot_selection(item_data)
            else:
                logger.warning(f"Unknown item type selected: {item_type}")

        except Exception as e:
            logger.error(f"Error handling item selected event: {e}")

    async def _handle_function_selection(self, item_data: Dict[str, Any]) -> None:
        """
        Handle application function selection.

        Args:
            item_data: Function item data
        """
        try:
            action = item_data.get("action", "unknown")

            if action == "open_settings":
                logger.info("Opening settings window from overlay...")

                # Emit real settings show event
                await self.event_bus.emit(
                    EventTypes.UI_SETTINGS_SHOW,
                    {
                        "trigger_source": "overlay",
                        "function_id": item_data.get("id")
                    },
                    source="OverlayManager"
                )

                # Hide overlay after action
                await self.hide_overlay(reason="settings_opened")

            elif action == "open_gallery":
                logger.info("Opening gallery window from overlay...")

                # Emit gallery show event (gallery implementation remains future feature)
                await self.event_bus.emit(
                    EventTypes.UI_GALLERY_SHOW,
                    {
                        "trigger_source": "overlay",
                        "function_id": item_data.get("id")
                    },
                    source="OverlayManager"
                )

                # For now, show a message that gallery is not implemented
                logger.info("Gallery window not implemented - keeping as future feature")

            else:
                logger.warning(f"Unknown function action: {action}")

        except Exception as e:
            logger.error(f"Error handling function selection: {e}")

    async def _handle_screenshot_selection(self, item_data: Dict[str, Any]) -> None:
        """
        Handle screenshot selection.

        Args:
            item_data: Screenshot item data
        """
        try:
            screenshot_id = item_data.get("id", "unknown")
            filename = item_data.get("filename", "unknown")

            logger.info(f"Opening gallery with screenshot: {filename}")

            # Emit gallery show event with specific screenshot (gallery remains future feature)
            await self.event_bus.emit(
                EventTypes.UI_GALLERY_SHOW,
                {
                    "trigger_source": "overlay",
                    "screenshot_id": screenshot_id,
                    "filename": filename,
                    "action": "open_gallery_with_selection"
                },
                source="OverlayManager"
            )

            # For now, just log that gallery is not implemented
            logger.info("Gallery window not implemented - keeping as future feature")

            # Hide overlay after selection
            await self.hide_overlay(reason="screenshot_selected")

        except Exception as e:
            logger.error(f"Error handling screenshot selection: {e}")

    async def _handle_overlay_dismissed(self, event_data) -> None:
        """
        Handle overlay dismissal events.

        Args:
            event_data: Event data containing dismissal information
        """
        try:
            dismissal_data = event_data.data or {}
            reason = dismissal_data.get("reason", "unknown")

            logger.info(f"Overlay dismissed: {reason}")

            # Update internal state if needed
            self._overlay_visible = False

        except Exception as e:
            logger.error(f"Error handling overlay dismissal event: {e}")

    async def handle_settings_change(self, settings_data: Dict[str, Any]) -> None:
        """
        Handle settings change events.

        Args:
            settings_data: Updated settings data
        """
        try:
            key = settings_data.get("key", "")

            if key.startswith("overlay."):
                logger.info(f"Overlay setting changed: {key}")

                # Reload configuration
                await self._load_configuration()

                # Apply changes to existing window if visible
                if self.overlay_window and self._overlay_visible:
                    self.overlay_window.apply_configuration(self._config_cache)

        except Exception as e:
            logger.error(f"Error handling settings change: {e}")

    async def handle_screenshot_update(self, screenshot_data: Dict[str, Any]) -> None:
        """
        Handle screenshot update events.

        Args:
            screenshot_data: Screenshot update data
        """
        try:
            logger.debug("Screenshot update received, invalidating cache")

            # Invalidate cache to force refresh
            self._cache_timestamp = 0.0
            self._screenshot_cache.clear()

            # Refresh overlay data if visible
            if self._overlay_visible and self.overlay_window:
                await self._refresh_overlay_data()

        except Exception as e:
            logger.error(f"Error handling screenshot update: {e}")

    async def _refresh_overlay_data(self) -> None:
        """Refresh overlay data without recreating the window."""
        try:
            if not self.overlay_window:
                return

            # Fetch updated data
            screenshot_data = await self._fetch_screenshot_data()
            app_functions = self._get_app_functions()

            # Update window contents
            self.overlay_window.populate_lists(app_functions, screenshot_data)

            logger.debug("Overlay data refreshed")

        except Exception as e:
            logger.error(f"Error refreshing overlay data: {e}")

    async def shutdown(self) -> None:
        """Shutdown the overlay manager."""
        try:
            logger.info("Shutting down OverlayManager...")

            # Hide overlay if visible
            if self._overlay_visible:
                await self.hide_overlay(reason="shutdown")

            # Destroy overlay window
            if self.overlay_window:
                self.overlay_window.close()
                self.overlay_window.deleteLater()
                self.overlay_window = None

            # Clear caches
            self._screenshot_cache.clear()
            self._config_cache.clear()

            self._initialized = False
            logger.info("OverlayManager shutdown complete")

        except Exception as e:
            logger.error(f"Error during OverlayManager shutdown: {e}")
