"""
Gallery Window Module

New implementation that coordinates gallery components from the components directory.
Implements the main gallery interface for screenshot management, AI chat, and preset interactions.
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QSplitter, QFrame
)

from src.utils.style_loader import (
    DynamicStyleManager,
    ScreenshotItemStyleManager, PresetItemStyleManager
)
from src.utils.icon_manager import get_icon_manager
from src import EventTypes

from .components import (
    CustomTitleBar, ChatInterface, ScreenshotGallery,
    PresetsPanel, GalleryState, PresetData
)

if TYPE_CHECKING:
    from src.controllers.event_bus import EventBus
    from src.models.screenshot_manager import ScreenshotManager
    from src.models.database_manager import DatabaseManager
    from src.models.preset_manager import PresetManager
    from src.models.settings_manager import SettingsManager

logger = logging.getLogger(__name__)


class GalleryWindow(QWidget):
    """Main gallery window with three-column layout using coordinated components."""

    # Signals for communication with the EventBus
    screenshot_selected = pyqtSignal(str)  # screenshot_id (now hash-based string)
    preset_executed = pyqtSignal(str, dict)  # preset_id, context
    chat_message_sent = pyqtSignal(str, dict)  # message, context
    gallery_closed = pyqtSignal()

    def __init__(
        self,
        event_bus: 'EventBus',
        screenshot_manager: 'ScreenshotManager',
        database_manager: 'DatabaseManager',
        preset_manager: 'PresetManager',
        settings_manager: 'SettingsManager',
        parent=None
    ):
        super().__init__(parent)

        self.event_bus = event_bus
        self.screenshot_manager = screenshot_manager
        self.database_manager = database_manager
        self.preset_manager = preset_manager
        self.settings_manager = settings_manager

        self.setObjectName("GalleryWindow")

        # State management
        self.gallery_state = GalleryState()
        self._initialized = False
        self._content_loaded = False  # Track if content has been loaded
        self._current_theme = "dark"  # Default theme, will be loaded from settings

        # Cache system for performance optimization
        self._screenshot_cache = {}  # Cache for screenshot metadata
        self._preset_cache = {}  # Cache for preset data
        self._thumbnail_cache = {}  # Cache for thumbnail paths/data
        self._ui_state_cache = {}  # Cache for UI state preservation
        self._cache_timestamp = None  # Track when cache was last updated
        self._cache_expiry_seconds = 300  # Cache expires after 5 minutes

        # Style management
        self._style_manager: Optional[DynamicStyleManager] = None
        self._screenshot_item_style_manager: Optional[ScreenshotItemStyleManager] = None
        self._preset_item_style_manager: Optional[PresetItemStyleManager] = None

        # Components
        self.title_bar: Optional[CustomTitleBar] = None
        self.screenshots_gallery: Optional[ScreenshotGallery] = None
        self.chat_interface: Optional[ChatInterface] = None
        self.presets_panel: Optional[PresetsPanel] = None

        # Initialize UI
        self._setup_ui()

    async def _subscribe_to_events(self) -> None:
        """Subscribe to EventBus events."""
        # Subscribe to Ollama response events
        await self.event_bus.subscribe(
            EventTypes.OLLAMA_RESPONSE_RECEIVED,
            self._handle_ollama_response,
            priority=90
        )

        # Subscribe to streaming updates
        await self.event_bus.subscribe(
            "ollama.streaming.update",
            self._handle_streaming_update,
            priority=90
        )

        # Subscribe to settings updates
        await self.event_bus.subscribe(
            EventTypes.SETTINGS_UPDATED,
            self._handle_settings_updated,
            priority=80
        )

        # Subscribe to screenshot events
        await self.event_bus.subscribe(
            EventTypes.SCREENSHOT_CAPTURED,
            self._handle_screenshot_captured,
            priority=75
        )

        await self.event_bus.subscribe(
            EventTypes.SCREENSHOT_COMPLETED,
            self._handle_screenshot_completed,
            priority=75
        )

        # Subscribe to preset events
        await self.event_bus.subscribe(
            EventTypes.PRESET_CREATED,
            self._handle_preset_created,
            priority=70
        )

        await self.event_bus.subscribe(
            EventTypes.PRESET_UPDATED,
            self._handle_preset_updated,
            priority=70
        )

        await self.event_bus.subscribe(
            EventTypes.PRESET_DELETED,
            self._handle_preset_deleted,
            priority=70
        )

        # Subscribe to application state changes
        await self.event_bus.subscribe(
            EventTypes.APP_STATE_CHANGED,
            self._handle_app_state_changed,
            priority=60
        )

        # Subscribe to error events
        await self.event_bus.subscribe(
            EventTypes.ERROR_OCCURRED,
            self._handle_error_occurred,
            priority=50
        )

    def _handle_ollama_response(self, event_data) -> None:
        """Handle Ollama response events."""
        try:
            if self.chat_interface and event_data.data and 'response' in event_data.data:
                response = event_data.data['response']
                screenshot_hash = event_data.data.get('screenshot_hash')

                # Only add the response if it matches the currently selected screenshot
                if screenshot_hash and self.gallery_state.selected_screenshot_id == screenshot_hash:
                    self.chat_interface.add_ai_message(response)
                    self.chat_interface.set_status("Response received")

        except Exception as e:
            logger.error(f"Error handling Ollama response: {e}")

    def _handle_streaming_update(self, event_data) -> None:
        """Handle streaming update events."""
        try:
            if self.chat_interface and event_data.data and 'content' in event_data.data:
                # Note: Streaming updates don't include screenshot_hash, so we can't filter by screenshot
                # This is a limitation of the current streaming implementation
                # For now, we'll show streaming updates only if a screenshot is selected
                if self.gallery_state.selected_screenshot_id:
                    content = event_data.data['content']
                    self.chat_interface.set_status(f"Streaming: {content[:50]}...")
                else:
                    logger.debug("Ignoring streaming update - no screenshot selected")

        except Exception as e:
            logger.error(f"Error handling streaming update: {e}")

    def _handle_settings_updated(self, event_data) -> None:
        """Handle settings updated events."""
        try:
            if not event_data.data:
                return

            data = event_data.data

            # Handle single setting updates
            if 'key' in data and 'value' in data:
                key = data['key']
                value = data['value']

                # UI Theme settings
                if key == 'ui.theme' and value != self._current_theme:
                    self._current_theme = value
                    asyncio.create_task(self._apply_theme_change())

                # Window opacity settings
                elif key == 'ui.opacity':
                    opacity = float(value)
                    self.setWindowOpacity(opacity)
                    self._update_translucent_background(opacity)

                # Gallery-specific opacity setting
                elif key == 'ui.gallery_opacity':
                    opacity = float(value)
                    self.setWindowOpacity(opacity)
                    self._update_translucent_background(opacity)

                # Font size changes
                elif key == 'ui.font_size':
                    asyncio.create_task(self._apply_font_size_change(int(value)))

                # Window behavior settings
                elif key == 'ui.window_always_on_top':
                    self._apply_always_on_top_change(bool(value))

                # Screenshot display settings
                elif key == 'screenshot.thumbnail_size':
                    asyncio.create_task(self._apply_thumbnail_size_change(value))

                elif key in ['screenshot.image_format', 'screenshot.quality']:
                    asyncio.create_task(self._handle_screenshot_display_change(key, value))

                # Ollama/AI settings that affect chat interface
                elif key in ['ollama.server_url', 'ollama.default_model',
                           'ollama.max_retries', 'ollama.enable_streaming']:
                    asyncio.create_task(self._handle_ollama_setting_change(key, value))

                # Cache and optimization settings
                elif key.startswith('optimization.'):
                    asyncio.create_task(self._handle_optimization_setting_change(key, value))

            # Handle full settings save (if it contains all settings)
            elif 'settings' in data:
                settings = data['settings']

                # Check for theme changes
                if 'ui.theme' in settings and settings['ui.theme'] != self._current_theme:
                    self._current_theme = settings['ui.theme']
                    asyncio.create_task(self._apply_theme_change())

                # Check for opacity changes (prefer gallery-specific opacity)
                opacity_key = 'ui.gallery_opacity' if 'ui.gallery_opacity' in settings else 'ui.opacity'
                if opacity_key in settings:
                    opacity = float(settings[opacity_key])
                    self.setWindowOpacity(opacity)
                    self._update_translucent_background(opacity)

                # Check for font size changes
                if 'ui.font_size' in settings:
                    asyncio.create_task(self._apply_font_size_change(int(settings['ui.font_size'])))

                # Check for window behavior changes
                if 'ui.window_always_on_top' in settings:
                    self._apply_always_on_top_change(bool(settings['ui.window_always_on_top']))

                # Check for screenshot-related changes
                screenshot_keys = ['screenshot.thumbnail_size', 'screenshot.image_format', 'screenshot.quality']
                for key in screenshot_keys:
                    if key in settings:
                        asyncio.create_task(self._handle_screenshot_display_change(key, settings[key]))

                # Check for Ollama setting changes
                ollama_keys = ['ollama.server_url', 'ollama.default_model',
                              'ollama.max_retries', 'ollama.enable_streaming']
                for key in ollama_keys:
                    if key in settings:
                        asyncio.create_task(self._handle_ollama_setting_change(key, settings[key]))

                # Check for optimization setting changes
                for key, value in settings.items():
                    if key.startswith('optimization.'):
                        asyncio.create_task(self._handle_optimization_setting_change(key, value))

        except Exception as e:
            logger.error(f"Error handling settings update: {e}")

    def _handle_screenshot_captured(self, event_data) -> None:
        """Handle screenshot captured events with cache invalidation."""
        try:
            # Invalidate screenshot cache since we have new content
            self.invalidate_cache('screenshots')

            # Only refresh if gallery is visible and content is already loaded
            if self.isVisible() and self._content_loaded and self.screenshots_gallery and event_data.data:
                # Use the new refresh method for incremental updates
                refresh_method = getattr(self.screenshots_gallery, 'refresh_screenshots', None) or \
                               getattr(self.screenshots_gallery, 'load_screenshots', None)
                if refresh_method:
                    asyncio.create_task(refresh_method())
                logger.debug("Gallery refreshed after screenshot capture")

        except Exception as e:
            logger.error(f"Error handling screenshot captured: {e}")

    def _handle_screenshot_completed(self, event_data) -> None:
        """Handle screenshot completed events with cache update."""
        try:
            # Additional handling for completed screenshots
            if event_data.data and 'screenshot_id' in event_data.data:
                screenshot_id = event_data.data['screenshot_id']
                logger.debug(f"Screenshot completed: {screenshot_id}")

                # Update cache with new screenshot data
                asyncio.create_task(self._update_cache())

                # Optionally auto-select the new screenshot in gallery
                if self.screenshots_gallery:
                    select_method = getattr(self.screenshots_gallery, 'select_screenshot', None)
                    if select_method:
                        asyncio.create_task(select_method(screenshot_id))

        except Exception as e:
            logger.error(f"Error handling screenshot completed: {e}")

    async def _handle_preset_created(self, event_data) -> None:
        """Handle preset created events with cache invalidation."""
        try:
            # Invalidate preset cache
            self.invalidate_cache('presets')

            # Only refresh if gallery is visible and content is loaded
            if self.isVisible() and self._content_loaded and self.presets_panel:
                await self.presets_panel.refresh_presets()
                logger.debug("Presets panel refreshed after preset creation")

        except Exception as e:
            logger.error(f"Error handling preset created: {e}")

    async def _handle_preset_updated(self, event_data) -> None:
        """Handle preset updated events with cache invalidation."""
        try:
            # Invalidate preset cache
            self.invalidate_cache('presets')

            # Only refresh if gallery is visible and content is loaded
            if self.isVisible() and self._content_loaded and self.presets_panel:
                await self.presets_panel.refresh_presets()
                logger.debug("Presets panel refreshed after preset update")

        except Exception as e:
            logger.error(f"Error handling preset updated: {e}")

    async def _handle_preset_deleted(self, event_data) -> None:
        """Handle preset deleted events with cache invalidation."""
        try:
            # Invalidate preset cache
            self.invalidate_cache('presets')

            # Only refresh if gallery is visible and content is loaded
            if self.isVisible() and self._content_loaded and self.presets_panel:
                await self.presets_panel.refresh_presets()
                logger.debug("Presets panel refreshed after preset deletion")

        except Exception as e:
            logger.error(f"Error handling preset deleted: {e}")

    def _handle_app_state_changed(self, event_data) -> None:
        """Handle application state change events."""
        try:
            if event_data.data and 'state' in event_data.data:
                state = event_data.data['state']

                # Update gallery UI based on app state
                if state == 'busy':
                    # Show busy indicator in gallery
                    if self.chat_interface:
                        self.chat_interface.set_status("Application busy...")
                elif state == 'ready':
                    # Clear busy indicator
                    if self.chat_interface:
                        self.chat_interface.set_status("Ready")
                elif state == 'error':
                    # Show error state
                    if self.chat_interface:
                        self.chat_interface.set_status("Application error occurred")

                logger.info(f"Gallery updated for app state: {state}")

        except Exception as e:
            logger.error(f"Error handling app state change: {e}")

    def _handle_error_occurred(self, event_data) -> None:
        """Handle error events."""
        try:
            if event_data.data:
                error_info = event_data.data
                error_message = error_info.get('message', 'Unknown error')

                # Show error in chat interface
                if self.chat_interface:
                    self.chat_interface.add_system_message(f"Error: {error_message}")

                    # Set status to "Timeout" if it's a timeout error
                    if 'timed out' in error_message.lower():
                        self.chat_interface.set_status("Timeout")

                logger.warning(f"Gallery received error event: {error_message}")

        except Exception as e:
            logger.error(f"Error handling error event: {e}")

    async def _apply_theme_change(self):
        """Apply theme changes to all components."""
        try:
            # Reload style managers
            await self._initialize_style_managers()

            # Apply theme to all components
            self._apply_theme()

            logger.info(f"Theme changed to: {self._current_theme}")

        except Exception as e:
            logger.error(f"Error applying theme change: {e}")

    async def _apply_font_size_change(self, font_size: int):
        """Apply font size changes to all components."""
        try:
            # Re-apply theme with new font size (this will update all styling)
            await self._apply_theme_change()

            # Emit event for components that might want to handle font size changes
            await self.event_bus.emit(
                "gallery.font_size_changed",
                {
                    "font_size": font_size,
                    "gallery_id": id(self)
                },
                source="GalleryWindow"
            )

            logger.info(f"Font size changed to: {font_size}")

        except Exception as e:
            logger.error(f"Error applying font size change: {e}")

    def _apply_always_on_top_change(self, always_on_top: bool):
        """Apply window always-on-top setting change."""
        try:
            flags = self.windowFlags()

            if always_on_top:
                flags |= Qt.WindowType.WindowStaysOnTopHint
            else:
                flags &= ~Qt.WindowType.WindowStaysOnTopHint

            self.setWindowFlags(flags)

            # Show window again as setWindowFlags hides it
            if self.isVisible():
                self.show()

            logger.info(f"Always on top changed to: {always_on_top}")

        except Exception as e:
            logger.error(f"Error applying always on top change: {e}")

    async def _apply_thumbnail_size_change(self, thumbnail_size):
        """Apply thumbnail size changes."""
        try:
            # Emit event for screenshots gallery to handle
            await self.event_bus.emit(
                "gallery.thumbnail_size_changed",
                {
                    "thumbnail_size": thumbnail_size,
                    "gallery_id": id(self)
                },
                source="GalleryWindow"
            )

            # Components should listen for the event emitted above

            logger.info(f"Thumbnail size changed to: {thumbnail_size}")

        except Exception as e:
            logger.error(f"Error applying thumbnail size change: {e}")

    async def _handle_screenshot_display_change(self, key: str, value):
        """Handle screenshot display setting changes."""
        try:
            # Emit event for screenshots gallery to handle
            await self.event_bus.emit(
                "gallery.screenshot_display_changed",
                {
                    "setting_key": key,
                    "setting_value": value,
                    "gallery_id": id(self)
                },
                source="GalleryWindow"
            )

            # Components should listen for the event emitted above
            logger.info(f"Screenshot display setting updated: {key} = {value}")

        except Exception as e:
            logger.error(f"Error handling screenshot display change ({key}): {e}")

    async def _handle_ollama_setting_change(self, key: str, value):
        """Handle Ollama/AI setting changes that affect chat interface."""
        try:
            # Emit event for chat interface to handle
            await self.event_bus.emit(
                "gallery.ollama_setting_changed",
                {
                    "setting_key": key,
                    "setting_value": value,
                    "gallery_id": id(self)
                },
                source="GalleryWindow"
            )

            # Components should listen for the event emitted above
            logger.info(f"Ollama setting updated: {key} = {value}")

        except Exception as e:
            logger.error(f"Error handling Ollama setting change ({key}): {e}")

    async def _handle_optimization_setting_change(self, key: str, value):
        """Handle optimization setting changes."""
        try:
            logger.debug(f"Handling optimization setting change: {key} = {value}")

            # Handle specific optimization settings
            if key == "optimization.thumbnail_cache_enabled":
                await self._handle_thumbnail_cache_enabled_change(bool(value))
            elif key == "optimization.thumbnail_cache_size":
                await self._handle_thumbnail_cache_size_change(int(value))
            elif key == "optimization.thumbnail_quality":
                await self._handle_thumbnail_quality_change(int(value))
            elif key == "optimization.storage_management_enabled":
                await self._handle_storage_management_change(bool(value))
            elif key == "optimization.max_storage_gb":
                await self._handle_storage_limit_change(float(value))
            elif key == "optimization.max_file_count":
                await self._handle_file_count_limit_change(int(value))
            elif key == "optimization.auto_cleanup_enabled":
                await self._handle_auto_cleanup_change(bool(value))
            elif key == "optimization.request_pooling_enabled":
                await self._handle_request_pooling_change(bool(value))
            elif key == "optimization.max_concurrent_requests":
                await self._handle_max_concurrent_change(int(value))
            elif key == "optimization.request_timeout":
                await self._handle_request_timeout_change(float(value))

            # Emit event for other components that might need it
            await self.event_bus.emit(
                "gallery.optimization_setting_changed",
                {
                    "setting_key": key,
                    "setting_value": value,
                    "gallery_id": id(self)
                },
                source="GalleryWindow"
            )

            logger.debug(f"Optimization setting updated: {key} = {value}")

        except Exception as e:
            logger.error(f"Error handling optimization setting change ({key}): {e}")

    async def initialize(self) -> bool:
        """Initialize the gallery window."""
        try:
            # Load settings
            self._current_theme = await self.settings_manager.get_setting("ui.theme", "dark")

            # Load opacity settings - prefer gallery-specific opacity over general opacity
            opacity = await self.settings_manager.get_setting("ui.gallery_opacity", None)
            if opacity is None:
                opacity = await self.settings_manager.get_setting("ui.opacity", 1.0)
            opacity = float(opacity)

            # Apply window settings
            self.setWindowOpacity(opacity)
            self._update_translucent_background(opacity)

            # Initialize style managers
            await self._initialize_style_managers()

            # Initialize components
            await self._initialize_components()

            # Subscribe to events
            await self._subscribe_to_events()

            # Apply theme
            self._apply_theme()

            self._initialized = True
            logger.debug("GalleryWindow initialized successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize GalleryWindow: {e}")
            return False

    async def _initialize_style_managers(self):
        """Initialize style managers."""
        try:
            # Load base stylesheets
            self._style_manager = DynamicStyleManager("gallery", self._current_theme)

            self._screenshot_item_style_manager = ScreenshotItemStyleManager(
                self._style_manager
            )

            self._preset_item_style_manager = PresetItemStyleManager(
                self._style_manager
            )

            logger.debug("Style managers initialized")

        except Exception as e:
            logger.error(f"Failed to initialize style managers: {e}")

    async def _initialize_components(self):
        """Initialize all gallery components."""
        try:
            # Initialize screenshot gallery thumbnail loader
            if self.screenshots_gallery:
                self.screenshots_gallery.initialize_thumbnail_loader(self.screenshot_manager)

                # Load and apply optimization settings to thumbnail loader
                if self.settings_manager:
                    try:
                        settings = await self.settings_manager.load_settings()
                        optimization = settings.optimization

                        # Apply thumbnail settings
                        if hasattr(self.screenshots_gallery, 'thumbnail_loader') and self.screenshots_gallery.thumbnail_loader:
                            thumbnail_cache_enabled = optimization.thumbnail_cache_enabled
                            thumbnail_cache_size = optimization.thumbnail_cache_size
                            thumbnail_quality = optimization.thumbnail_quality

                            self.screenshots_gallery.thumbnail_loader.set_cache_enabled(thumbnail_cache_enabled)
                            self.screenshots_gallery.thumbnail_loader.set_cache_size(thumbnail_cache_size)
                            self.screenshots_gallery.thumbnail_loader.set_quality(thumbnail_quality)

                            logger.debug(f"Applied thumbnail settings: cache={thumbnail_cache_enabled}, size={thumbnail_cache_size}, quality={thumbnail_quality}")
                    except Exception as e:
                        logger.warning(f"Failed to load optimization settings: {e}")

                # Set style manager
                if self._screenshot_item_style_manager:
                    self.screenshots_gallery.set_style_manager(self._screenshot_item_style_manager)

            # Set style manager for presets panel
            if self.presets_panel and self._preset_item_style_manager:
                self.presets_panel.set_style_manager(self._preset_item_style_manager)

            logger.debug("Components initialized")

        except Exception as e:
            logger.error(f"Failed to initialize components: {e}")

    def _setup_ui(self):
        """Setup the user interface."""
        self.setWindowTitle("ExplainShot Gallery")

        # Set window icon
        icon_manager = get_icon_manager()
        app_icon = icon_manager.get_app_icon()
        if app_icon:
            self.setWindowIcon(app_icon)

        self.setGeometry(100, 100, 1200, 800)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)

        # Enable key events for shortcuts
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Custom title bar
        self.title_bar = CustomTitleBar("ExplainShot Gallery", self)
        main_layout.addWidget(self.title_bar)

        # Three-column splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setSizes([400, 400, 400])  # Equal width columns

        # Left column - Screenshots
        self.screenshots_gallery = ScreenshotGallery(self.screenshot_manager, self)
        screenshots_frame = QFrame()
        screenshots_frame.setObjectName("screenshots_frame")
        screenshots_layout = QVBoxLayout(screenshots_frame)
        screenshots_layout.setContentsMargins(0, 0, 0, 0)
        screenshots_layout.addWidget(self.screenshots_gallery)
        splitter.addWidget(screenshots_frame)

        # Middle column - Chat
        self.chat_interface = ChatInterface(self)
        chat_frame = QFrame()
        chat_frame.setObjectName("chat_frame")
        chat_layout = QVBoxLayout(chat_frame)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        chat_layout.addWidget(self.chat_interface)
        splitter.addWidget(chat_frame)

        # Right column - Presets
        self.presets_panel = PresetsPanel(self.preset_manager, self)
        presets_frame = QFrame()
        presets_frame.setObjectName("presets_frame")
        presets_layout = QVBoxLayout(presets_frame)
        presets_layout.setContentsMargins(0, 0, 0, 0)
        presets_layout.addWidget(self.presets_panel)
        splitter.addWidget(presets_frame)

        main_layout.addWidget(splitter)

        # Connect signals
        self._connect_signals()

    def _connect_signals(self):
        """Connect component signals."""
        # Screenshots gallery signals
        if self.screenshots_gallery:
            self.screenshots_gallery.screenshot_selected.connect(self._on_screenshot_selected)
            self.screenshots_gallery.screenshot_deselected.connect(self._on_screenshot_deselected)

        # Chat interface signals
        if self.chat_interface:
            self.chat_interface.message_sent.connect(self._on_chat_message_sent)

        # Presets panel signals
        if self.presets_panel:
            self.presets_panel.preset_run_clicked.connect(self._on_preset_run)
            self.presets_panel.preset_paste_clicked.connect(self._on_preset_paste)

    async def show_gallery(self, pre_selected_screenshot_id: Optional[str] = None):
        """Show the gallery window with optional pre-selection."""
        try:
            if not self._initialized:
                success = await self.initialize()
                if not success:
                    logger.error("Failed to initialize gallery")
                    return

            # Only load content if not already loaded or cache is invalid
            content_was_loaded = self._content_loaded
            if not self._content_loaded or not self._is_cache_valid():
                await self._load_content_with_cache()
                self._content_loaded = True

            # Show the window
            self.show()
            self.raise_()
            self.activateWindow()

            # Handle pre-selection logic
            if pre_selected_screenshot_id:
                if content_was_loaded and self._is_cache_valid():
                    # Content was already loaded, try immediate selection
                    if self.screenshots_gallery:
                        await self.screenshots_gallery.select_screenshot(pre_selected_screenshot_id)

                # Always do a background refresh with selection to catch any new files
                # This ensures we don't miss recently created screenshots
                asyncio.create_task(self._refresh_screenshots_directory_async(pre_selected_screenshot_id))
            else:
                # Just do a standard refresh without selection
                asyncio.create_task(self._refresh_screenshots_directory_async())

            logger.debug("Gallery window shown")

        except Exception as e:
            logger.error(f"Error showing gallery: {e}")

    async def _refresh_screenshots_directory_async(self, pre_selected_screenshot_id: Optional[str] = None):
        """Asynchronously refresh the screenshots directory to catch any new files."""
        try:
            # Small delay to let the UI settle after showing
            await asyncio.sleep(0.1)

            if self.screenshots_gallery and self.screenshot_manager:
                # Force a fresh scan of the screenshot directory to catch potential new files
                logger.debug("Triggering background screenshot directory refresh with force scan")

                # Use force_directory_refresh to ensure we catch any new files
                # that might have been created while the gallery was hidden
                if hasattr(self.screenshots_gallery, 'force_directory_refresh'):
                    await self.screenshots_gallery.force_directory_refresh()
                else:
                    # Fallback to regular refresh
                    await self.screenshots_gallery.refresh_screenshots()

                # Try to select the pre-selected screenshot after refresh
                # This is crucial for cases where the gallery was hidden and a new screenshot
                # was captured - the initial selection might fail if the screenshot wasn't loaded yet
                if pre_selected_screenshot_id and self.screenshots_gallery:
                    logger.debug(f"Attempting to select screenshot after refresh: {pre_selected_screenshot_id[:8]}")
                    await self.screenshots_gallery.select_screenshot(pre_selected_screenshot_id)

                # Update cache with fresh data
                await self._update_cache()

                logger.debug("Background screenshot directory refresh completed")

        except Exception as e:
            logger.error(f"Error during background screenshot directory refresh: {e}")

    async def _load_content_with_cache(self):
        """Load gallery content with intelligent caching."""
        try:
            # Check if cache is still valid
            if self._is_cache_valid():
                logger.debug("Using cached gallery content")
                await self._restore_from_cache()
            else:
                logger.debug("Cache expired or invalid, reloading content")
                await self._load_fresh_content()
                await self._update_cache()

        except Exception as e:
            logger.error(f"Error loading gallery content with cache: {e}")
            # Fallback to direct loading if cache fails
            await self._load_content()

    def _is_cache_valid(self) -> bool:
        """Check if the current cache is still valid."""
        if not self._cache_timestamp:
            return False

        import time
        current_time = time.time()
        return (current_time - self._cache_timestamp) < self._cache_expiry_seconds

    async def _restore_from_cache(self):
        """Restore gallery content from cache."""
        try:
            # If content is already loaded and cache is valid, don't reload
            if self._content_loaded and self._is_cache_valid():
                logger.debug("Content already loaded and cache valid, skipping reload")
                return

            # Load screenshots only if not already loaded
            if self.screenshots_gallery and not self.screenshots_gallery.screenshot_items:
                await self.screenshots_gallery.load_screenshots()

            # Load presets only if not already loaded
            if self.presets_panel:
                await self.presets_panel.refresh_presets()

            # Restore UI state
            if self._ui_state_cache:
                await self._restore_ui_state(self._ui_state_cache)

            logger.debug("Gallery content loaded (cache-aware)")

        except Exception as e:
            logger.error(f"Error restoring from cache: {e}")
            # Fallback to fresh load
            await self._load_fresh_content()

    async def _load_fresh_content(self):
        """Load fresh content from data sources."""
        try:
            # Load screenshots
            if self.screenshots_gallery:
                await self.screenshots_gallery.load_screenshots()

            # Load presets
            if self.presets_panel:
                await self.presets_panel.refresh_presets()

            logger.debug("Fresh gallery content loaded")

        except Exception as e:
            logger.error(f"Error loading fresh gallery content: {e}")

    async def _update_cache(self):
        """Update the cache with current data."""
        try:
            import time

            # Cache screenshot metadata
            if self.screenshots_gallery:
                screenshots = await self.screenshot_manager.get_recent_screenshots(limit=50)
                self._screenshot_cache = {
                    'screenshots': [
                        {
                            'hash': s.hash or s.unique_id,
                            'filename': s.filename,
                            'timestamp': s.timestamp,
                            'full_path': s.full_path
                        }
                        for s in screenshots if s.hash or s.unique_id
                    ]
                }

            # Cache preset data
            if self.presets_panel:
                # We don't have direct access to preset list, so we'll cache later when events update
                pass

            # Cache UI state
            self._ui_state_cache = {
                'selected_screenshot_id': self.gallery_state.selected_screenshot_id,
                'window_geometry': self.geometry(),
                'splitter_sizes': None  # We'll add this if we can access splitter
            }

            # Update cache timestamp
            self._cache_timestamp = time.time()

            logger.debug("Gallery cache updated")

        except Exception as e:
            logger.error(f"Error updating cache: {e}")

    async def _restore_ui_state(self, ui_state: dict):
        """Restore UI state from cache."""
        try:
            # Restore selected screenshot
            if ui_state.get('selected_screenshot_id') and self.screenshots_gallery:
                await self.screenshots_gallery.select_screenshot(ui_state['selected_screenshot_id'])

            # Restore window geometry
            if ui_state.get('window_geometry'):
                self.setGeometry(ui_state['window_geometry'])

            logger.debug("UI state restored from cache")

        except Exception as e:
            logger.error(f"Error restoring UI state: {e}")

    def invalidate_cache(self, cache_type: Optional[str] = None):
        """Invalidate specific cache or all caches."""
        if cache_type == 'screenshots':
            self._screenshot_cache.clear()
        elif cache_type == 'presets':
            self._preset_cache.clear()
        elif cache_type == 'thumbnails':
            self._thumbnail_cache.clear()
        elif cache_type == 'ui_state':
            self._ui_state_cache.clear()
        else:
            # Invalidate all caches
            self._screenshot_cache.clear()
            self._preset_cache.clear()
            self._thumbnail_cache.clear()
            self._ui_state_cache.clear()
            self._cache_timestamp = None
            # Reset content loaded flag when invalidating all caches
            self._content_loaded = False

        logger.info(f"Cache invalidated: {cache_type or 'all'}")

    async def _load_content(self):
        """Load all gallery content."""
        try:
            # Load screenshots
            if self.screenshots_gallery:
                await self.screenshots_gallery.load_screenshots()

            # Load presets (refresh from disk first to catch manually added files)
            if self.presets_panel:
                await self.presets_panel.refresh_presets()

            logger.debug("Gallery content loaded")

        except Exception as e:
            logger.error(f"Error loading gallery content: {e}")

    def _on_screenshot_selected(self, screenshot_id: str):
        """Handle screenshot selection."""
        # Store the selected screenshot ID
        self.gallery_state.selected_screenshot_id = screenshot_id

        # Clear chat UI immediately when switching screenshots
        if self.chat_interface:
            self.chat_interface.clear_chat()

        # Get and store screenshot metadata for context, then load chat history
        asyncio.create_task(self._load_selected_screenshot_data(screenshot_id))

        self.screenshot_selected.emit(screenshot_id)
        logger.debug(f"Screenshot selected: {screenshot_id}")

    async def _load_selected_screenshot_data(self, screenshot_hash: str):
        """Load metadata and chat history for the selected screenshot."""
        try:
            # Get all screenshots and find the one with matching hash
            screenshots = await self.screenshot_manager.scan_screenshot_directory()
            for screenshot in screenshots:
                if screenshot.hash == screenshot_hash or screenshot.unique_id == screenshot_hash:
                    self.gallery_state.selected_screenshot_metadata = screenshot
                    logger.debug(f"Loaded metadata for selected screenshot: {screenshot_hash}")

                    # Load chat history for this screenshot
                    await self._load_chat_history_for_screenshot(screenshot_hash)
                    break
        except Exception as e:
            logger.error(f"Failed to load screenshot data for {screenshot_hash}: {e}")

    async def _load_chat_history_for_screenshot(self, screenshot_hash: str):
        """Load and display chat history for the selected screenshot."""
        try:
            # Import ChatHistoryManager here to avoid circular imports
            from src.models.chat_history_manager import ChatHistoryManager

            # Get chat history directory from settings
            if not self.settings_manager:
                logger.warning("No settings manager available for chat history loading")
                return

            settings = await self.settings_manager.load_settings()
            chat_dir = settings.chat.chat_history_directory

            if not chat_dir:
                logger.warning("Chat history directory not configured")
                return

            # Create ChatHistoryManager instance
            chat_manager = ChatHistoryManager(chat_dir)

            # Load conversation for this screenshot
            messages = await chat_manager.load_conversation(screenshot_hash)

            if messages and self.chat_interface:
                # Check if this screenshot is still selected before displaying messages
                # This prevents mixing chat histories when switching screenshots quickly
                if self.gallery_state.selected_screenshot_id != screenshot_hash:
                    logger.debug(f"Screenshot {screenshot_hash[:8]}... deselected before chat history could be displayed, skipping")
                    return

                # Display each message in the UI
                for message in messages:
                    if message.role == "user":
                        self.chat_interface.add_user_message(message.content)
                    elif message.role == "assistant":
                        self.chat_interface.add_ai_message(message.content)
                    elif message.role == "system":
                        self.chat_interface.add_system_message(message.content)

                logger.debug(f"Loaded {len(messages)} chat messages for screenshot {screenshot_hash[:8]}...")

                # Set status to show conversation loaded
                if self.chat_interface:
                    self.chat_interface.set_status(f"Loaded {len(messages)} messages")
            else:
                logger.debug(f"No chat history found for screenshot {screenshot_hash[:8]}...")
                if self.chat_interface:
                    self.chat_interface.set_status("No previous conversation")

        except Exception as e:
            logger.error(f"Failed to load chat history for {screenshot_hash}: {e}")
            if self.chat_interface:
                self.chat_interface.set_status("Error loading chat history")
            # Don't show error to user - just log it

    def _on_screenshot_deselected(self):
        """Handle screenshot deselection."""
        self.gallery_state.selected_screenshot_id = None
        self.gallery_state.selected_screenshot_metadata = None

        # Clear chat UI when no screenshot is selected
        if self.chat_interface:
            self.chat_interface.clear_chat()

        logger.debug("Screenshot deselected")

    def _on_preset_run(self, preset_id: str):
        """Handle preset run button clicks."""
        if self.gallery_state.selected_screenshot_id is None:
            if self.chat_interface:
                self.chat_interface.add_system_message("Please select a screenshot first")
            return

        # Run async preset execution
        asyncio.create_task(self._run_preset_async(preset_id))

    def _on_preset_paste(self, preset_id: str):
        """Handle preset paste button clicks."""
        # Run async preset paste
        asyncio.create_task(self._paste_preset_async(preset_id))

    async def _run_preset_async(self, preset_id: str):
        """Handle preset run asynchronously."""
        try:
            preset_data = await self._get_preset_by_id(preset_id)
            if preset_data and self.chat_interface:
                # Add user message showing preset execution
                self.chat_interface.add_user_message(preset_data.prompt)
                self.chat_interface.set_status("Processing...")

                # Save user message to chat history immediately
                asyncio.create_task(self._save_user_message_to_history(preset_data.prompt))

                # Create context for the preset execution
                context = {
                    "selected_screenshot": self.gallery_state.selected_screenshot_id,
                    "preset_id": preset_id,
                    "timestamp": datetime.now().isoformat()
                }

                # Add image path if we have screenshot metadata
                if self.gallery_state.selected_screenshot_metadata:
                    context["image_path"] = self.gallery_state.selected_screenshot_metadata.full_path
                    context["screenshot_metadata"] = self.gallery_state.selected_screenshot_metadata

                # Emit preset execution event
                self.preset_executed.emit(preset_id, context)

                logger.info(f"Preset executed: {preset_id}")

        except Exception as e:
            logger.error(f"Error running preset {preset_id}: {e}")
            if self.chat_interface:
                self.chat_interface.add_system_message(f"Error running preset: {e}")

    async def _paste_preset_async(self, preset_id: str):
        """Handle preset paste asynchronously."""
        try:
            preset_data = await self._get_preset_by_id(preset_id)
            if preset_data and self.chat_interface:
                self.chat_interface.set_prompt_text(preset_data.prompt)
                logger.info(f"Preset pasted: {preset_id}")

        except Exception as e:
            logger.error(f"Error pasting preset {preset_id}: {e}")

    def _on_chat_message_sent(self, message: str):
        """Handle chat message sending."""
        # Check if screenshot is selected
        if not self.gallery_state.selected_screenshot_id:
            if self.chat_interface:
                self.chat_interface.add_system_message("Please select a screenshot first")
            return

        # Add user message to chat UI
        if self.chat_interface:
            self.chat_interface.add_user_message(message)
            self.chat_interface.set_status("Processing...")

        # Save user message to chat history immediately
        asyncio.create_task(self._save_user_message_to_history(message))

        # Create context with screenshot information
        context = {
            "selected_screenshot": self.gallery_state.selected_screenshot_id,
            "timestamp": datetime.now().isoformat()
        }

        # Add image path if we have screenshot metadata
        if self.gallery_state.selected_screenshot_metadata:
            context["image_path"] = self.gallery_state.selected_screenshot_metadata.full_path
            context["screenshot_metadata"] = self.gallery_state.selected_screenshot_metadata

        # Emit chat event through EventBus
        asyncio.create_task(
            self.event_bus.emit(
                EventTypes.GALLERY_CHAT_MESSAGE_SENT,
                {
                    "message": message,
                    "context": context
                },
                source="GalleryWindow"
            )
        )

        logger.debug(f"Chat message sent: {message}")

    async def _save_user_message_to_history(self, message: str):
        """Save user message to chat history immediately."""
        try:
            if not self.gallery_state.selected_screenshot_id:
                return

            from src.models.chat_history_manager import ChatHistoryManager, ChatMessage

            # Get chat history directory from settings
            if not self.settings_manager:
                return

            settings = await self.settings_manager.load_settings()
            chat_dir = settings.chat.chat_history_directory

            if not chat_dir:
                return

            # Create ChatHistoryManager instance
            chat_manager = ChatHistoryManager(chat_dir)

            # Load existing conversation to get next message ID
            existing_messages = await chat_manager.load_conversation(self.gallery_state.selected_screenshot_id)
            next_id = len(existing_messages) + 1

            # Create user message
            user_message = ChatMessage(
                message_id=next_id,
                role="user",
                content=message,
                timestamp=datetime.now()
            )

            # Save user message
            await chat_manager.save_message(
                self.gallery_state.selected_screenshot_id,
                user_message,
                self.gallery_state.selected_screenshot_metadata
            )

            logger.debug(f"Saved user message to chat history: {message[:50]}...")

        except Exception as e:
            logger.error(f"Failed to save user message to chat history: {e}")

    async def _get_preset_by_id(self, preset_id: str) -> Optional[PresetData]:
        """Get preset data by ID."""
        try:
            preset = await self.preset_manager.get_preset_by_id(preset_id)
            if preset:
                return PresetData(
                    id=preset_id,
                    name=preset.name,
                    prompt=preset.prompt,
                    description=preset.description,
                    usage_count=preset.usage_count,
                    created_at=preset.created_at
                )
            return None

        except Exception as e:
            logger.error(f"Error getting preset {preset_id}: {e}")
            return None

    def _update_translucent_background(self, opacity: float):
        """Update the WA_TranslucentBackground attribute based on opacity."""
        if opacity >= 1.0:
            if self.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground):
                self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        else:
            if not self.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground):
                self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def _apply_theme(self):
        """Apply theme styling."""
        if self._style_manager:
            stylesheet = self._style_manager.load_base_styles()
            if stylesheet:
                self.setStyleSheet(stylesheet)
                logger.debug("Theme applied to gallery window")
        else:
            logger.warning("No style manager available for theme application")

    # Optimization setting handlers
    async def _handle_thumbnail_cache_enabled_change(self, enabled: bool):
        """Handle thumbnail cache enabled setting change."""
        try:
            if hasattr(self, 'screenshots_gallery') and self.screenshots_gallery:
                # Notify screenshots gallery component about cache setting change
                await self.screenshots_gallery.update_thumbnail_cache_setting(enabled)
            logger.debug(f"Thumbnail cache enabled changed to: {enabled}")
        except Exception as e:
            logger.error(f"Error handling thumbnail cache enabled change: {e}")

    async def _handle_thumbnail_cache_size_change(self, size: int):
        """Handle thumbnail cache size setting change."""
        try:
            if hasattr(self, 'screenshots_gallery') and self.screenshots_gallery:
                # Notify screenshots gallery component about cache size change
                await self.screenshots_gallery.update_thumbnail_cache_size(size)
            logger.debug(f"Thumbnail cache size changed to: {size}")
        except Exception as e:
            logger.error(f"Error handling thumbnail cache size change: {e}")

    async def _handle_thumbnail_quality_change(self, quality: int):
        """Handle thumbnail quality setting change."""
        try:
            if hasattr(self, 'screenshots_gallery') and self.screenshots_gallery:
                # Notify screenshots gallery component about quality change
                await self.screenshots_gallery.update_thumbnail_quality(quality)
            logger.debug(f"Thumbnail quality changed to: {quality}")
        except Exception as e:
            logger.error(f"Error handling thumbnail quality change: {e}")

    async def _handle_storage_management_change(self, enabled: bool):
        """Handle storage management enabled setting change."""
        try:
            # This could trigger storage manager reconfiguration
            logger.debug(f"Storage management enabled changed to: {enabled}")
        except Exception as e:
            logger.error(f"Error handling storage management change: {e}")

    async def _handle_storage_limit_change(self, limit_gb: float):
        """Handle storage limit setting change."""
        try:
            # This could trigger storage manager reconfiguration
            logger.debug(f"Storage limit changed to: {limit_gb} GB")
        except Exception as e:
            logger.error(f"Error handling storage limit change: {e}")

    async def _handle_file_count_limit_change(self, limit: int):
        """Handle file count limit setting change."""
        try:
            # This could trigger storage manager reconfiguration
            logger.debug(f"File count limit changed to: {limit}")
        except Exception as e:
            logger.error(f"Error handling file count limit change: {e}")

    async def _handle_auto_cleanup_change(self, enabled: bool):
        """Handle auto cleanup enabled setting change."""
        try:
            # This could trigger storage manager reconfiguration
            logger.debug(f"Auto cleanup enabled changed to: {enabled}")
        except Exception as e:
            logger.error(f"Error handling auto cleanup change: {e}")

    async def _handle_request_pooling_change(self, enabled: bool):
        """Handle request pooling enabled setting change."""
        try:
            if hasattr(self, 'chat_interface') and self.chat_interface:
                # Notify chat interface about request pooling change
                await self.chat_interface.update_request_pooling_setting(enabled)
            logger.debug(f"Request pooling enabled changed to: {enabled}")
        except Exception as e:
            logger.error(f"Error handling request pooling change: {e}")

    async def _handle_max_concurrent_change(self, max_concurrent: int):
        """Handle max concurrent requests setting change."""
        try:
            if hasattr(self, 'chat_interface') and self.chat_interface:
                # Notify chat interface about max concurrent change
                await self.chat_interface.update_max_concurrent_setting(max_concurrent)
            logger.debug(f"Max concurrent requests changed to: {max_concurrent}")
        except Exception as e:
            logger.error(f"Error handling max concurrent change: {e}")

    async def _handle_request_timeout_change(self, timeout: float):
        """Handle request timeout setting change."""
        try:
            if hasattr(self, 'chat_interface') and self.chat_interface:
                # Notify chat interface about timeout change
                await self.chat_interface.update_request_timeout_setting(timeout)
            logger.debug(f"Request timeout changed to: {timeout} seconds")
        except Exception as e:
            logger.error(f"Error handling request timeout change: {e}")

    def closeEvent(self, a0):
        """Handle window close event - hide instead of close to preserve state."""
        # Hide the window instead of closing it
        if a0:
            a0.ignore()  # Ignore the close event
        self.hide()  # Hide instead of closing

        # Emit gallery closed event
        self.gallery_closed.emit()
        logger.debug("Gallery window hidden (not closed)")

    def keyPressEvent(self, a0):
        """Handle key press events for shortcuts."""
        try:
            if not a0:
                return

            from PyQt6.QtCore import Qt

            # F5 or Ctrl+R for manual refresh
            if (a0.key() == Qt.Key.Key_F5 or
                (a0.modifiers() == Qt.KeyboardModifier.ControlModifier and a0.key() == Qt.Key.Key_R)):

                logger.debug("Manual refresh triggered by user")
                if self.screenshots_gallery:
                    asyncio.create_task(self.screenshots_gallery.force_directory_refresh())

                a0.accept()
                return

            # Escape to hide window
            elif a0.key() == Qt.Key.Key_Escape:
                self.hide()
                a0.accept()
                return

        except Exception as e:
            logger.error(f"Error handling key press event: {e}")

        # Pass to parent for unhandled keys
        super().keyPressEvent(a0)

    def force_close(self):
        """Force close the gallery window (used only during app shutdown)."""
        logger.info("Force closing gallery window")
        super().close()
