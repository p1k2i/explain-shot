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
    load_stylesheets, DynamicStyleManager,
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
    from src.models.settings_manager import SettingsManager

logger = logging.getLogger(__name__)


class GalleryWindow(QWidget):
    """Main gallery window with three-column layout using coordinated components."""

    # Signals for communication with the EventBus
    screenshot_selected = pyqtSignal(int)  # screenshot_id
    preset_executed = pyqtSignal(int, str)  # preset_id, screenshot_context
    chat_message_sent = pyqtSignal(str, dict)  # message, context
    gallery_closed = pyqtSignal()

    def __init__(
        self,
        event_bus: 'EventBus',
        screenshot_manager: 'ScreenshotManager',
        database_manager: 'DatabaseManager',
        settings_manager: 'SettingsManager',
        parent=None
    ):
        super().__init__(parent)

        self.event_bus = event_bus
        self.screenshot_manager = screenshot_manager
        self.database_manager = database_manager
        self.settings_manager = settings_manager

        self.setObjectName("GalleryWindow")

        # State management
        self.gallery_state = GalleryState()
        self._initialized = False
        self._current_theme = "dark"  # Default theme, will be loaded from settings

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

        logger.info("GalleryWindow created with component-based architecture")

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

    def _handle_ollama_response(self, event_data) -> None:
        """Handle Ollama response events."""
        try:
            if self.chat_interface and event_data.data and 'response' in event_data.data:
                response = event_data.data['response']
                self.chat_interface.add_ai_message(response)
                self.chat_interface.set_status("Response received")
                logger.info("AI response added to chat")

        except Exception as e:
            logger.error(f"Error handling Ollama response: {e}")

    def _handle_streaming_update(self, event_data) -> None:
        """Handle streaming update events."""
        try:
            if self.chat_interface and event_data.data and 'content' in event_data.data:
                # For streaming, we might want to update the last AI message
                # This is a simplified implementation
                content = event_data.data['content']
                self.chat_interface.set_status(f"Streaming: {content[:50]}...")

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

                if key == 'ui.theme' and value != self._current_theme:
                    self._current_theme = value
                    asyncio.create_task(self._apply_theme_change())
                elif key == 'ui.opacity':
                    opacity = float(value)
                    self.setWindowOpacity(opacity)
                    self._update_translucent_background(opacity)

            # Handle full settings save (if it contains all settings)
            elif 'settings' in data:
                settings = data['settings']

                # Check for theme changes
                if 'ui.theme' in settings and settings['ui.theme'] != self._current_theme:
                    self._current_theme = settings['ui.theme']
                    asyncio.create_task(self._apply_theme_change())

                # Check for opacity changes
                if 'ui.opacity' in settings:
                    opacity = float(settings['ui.opacity'])
                    self.setWindowOpacity(opacity)
                    self._update_translucent_background(opacity)

        except Exception as e:
            logger.error(f"Error handling settings update: {e}")

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

    async def initialize(self) -> bool:
        """Initialize the gallery window."""
        try:
            # Load settings
            self._current_theme = await self.settings_manager.get_setting("ui.theme", "dark")
            opacity = await self.settings_manager.get_setting("ui.opacity", 1.0)

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
            logger.info("GalleryWindow initialized successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize GalleryWindow: {e}")
            return False

    async def _initialize_style_managers(self):
        """Initialize style managers."""
        try:
            # Load base stylesheets
            stylesheets = load_stylesheets("gallery", self._current_theme, ["base", "components"])

            if stylesheets:
                self._style_manager = DynamicStyleManager("gallery", self._current_theme)

                self._screenshot_item_style_manager = ScreenshotItemStyleManager(
                    self._style_manager
                )

                self._preset_item_style_manager = PresetItemStyleManager(
                    self._style_manager
                )

                logger.info("Style managers initialized")
            else:
                logger.warning("Failed to load stylesheets")

        except Exception as e:
            logger.error(f"Failed to initialize style managers: {e}")

    async def _initialize_components(self):
        """Initialize all gallery components."""
        try:
            # Initialize screenshot gallery thumbnail loader
            if self.screenshots_gallery:
                self.screenshots_gallery.initialize_thumbnail_loader(self.screenshot_manager)

                # Set style manager
                if self._screenshot_item_style_manager:
                    self.screenshots_gallery.set_style_manager(self._screenshot_item_style_manager)

            # Set style manager for presets panel
            if self.presets_panel and self._preset_item_style_manager:
                self.presets_panel.set_style_manager(self._preset_item_style_manager)

            logger.info("Components initialized")

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
        self.presets_panel = PresetsPanel(self.database_manager, self)
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

    async def show_gallery(self, pre_selected_screenshot_id: Optional[int] = None):
        """Show the gallery window with optional pre-selection."""
        try:
            if not self._initialized:
                success = await self.initialize()
                if not success:
                    logger.error("Failed to initialize gallery")
                    return

            # Load content
            await self._load_content()

            # Pre-select screenshot if specified
            if pre_selected_screenshot_id and self.screenshots_gallery:
                await self.screenshots_gallery.select_screenshot(pre_selected_screenshot_id)

            # Show the window
            self.show()
            self.raise_()
            self.activateWindow()

            logger.info("Gallery window shown")

        except Exception as e:
            logger.error(f"Error showing gallery: {e}")

    async def _load_content(self):
        """Load all gallery content."""
        try:
            # Load screenshots
            if self.screenshots_gallery:
                await self.screenshots_gallery.load_screenshots()

            # Load presets
            if self.presets_panel:
                await self.presets_panel.load_presets()

            logger.info("Gallery content loaded")

        except Exception as e:
            logger.error(f"Error loading gallery content: {e}")

    def _on_screenshot_selected(self, screenshot_id: int):
        """Handle screenshot selection."""
        self.gallery_state.selected_screenshot_id = screenshot_id
        self.screenshot_selected.emit(screenshot_id)
        logger.info(f"Screenshot selected: {screenshot_id}")

    def _on_screenshot_deselected(self):
        """Handle screenshot deselection."""
        self.gallery_state.selected_screenshot_id = None
        logger.info("Screenshot deselected")

    def _on_preset_run(self, preset_id: int):
        """Handle preset run button clicks."""
        if self.gallery_state.selected_screenshot_id is None:
            if self.chat_interface:
                self.chat_interface.add_system_message("Please select a screenshot first")
            return

        # Run async preset execution
        asyncio.create_task(self._run_preset_async(preset_id))

    def _on_preset_paste(self, preset_id: int):
        """Handle preset paste button clicks."""
        # Run async preset paste
        asyncio.create_task(self._paste_preset_async(preset_id))

    async def _run_preset_async(self, preset_id: int):
        """Handle preset run asynchronously."""
        try:
            preset_data = await self._get_preset_by_id(preset_id)
            if preset_data and self.chat_interface:
                # Add user message showing preset execution
                self.chat_interface.add_user_message(f"Running preset: {preset_data.name}")

                # Create context for the preset execution
                context = {
                    "selected_screenshot": self.gallery_state.selected_screenshot_id,
                    "preset_id": preset_id,
                    "timestamp": datetime.now().isoformat()
                }

                # Emit preset execution event
                self.preset_executed.emit(preset_id, str(context))

                logger.info(f"Preset executed: {preset_id}")

        except Exception as e:
            logger.error(f"Error running preset {preset_id}: {e}")
            if self.chat_interface:
                self.chat_interface.add_system_message(f"Error running preset: {e}")

    async def _paste_preset_async(self, preset_id: int):
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
        # Add user message to chat
        if self.chat_interface:
            self.chat_interface.add_user_message(message)

        # Create context
        context = {
            "selected_screenshot": self.gallery_state.selected_screenshot_id,
            "timestamp": datetime.now().isoformat()
        }

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

    async def _get_preset_by_id(self, preset_id: int) -> Optional[PresetData]:
        """Get preset data by ID."""
        try:
            preset = await self.database_manager.get_preset_by_id(preset_id)
            if preset and preset.id is not None:
                return PresetData(
                    id=preset.id,
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
                logger.info("Theme applied to gallery window")
        else:
            logger.warning("No style manager available for theme application")

    def closeEvent(self, a0):
        """Handle window close event."""
        self.gallery_closed.emit()
        logger.info("Gallery window closed")
        super().closeEvent(a0)
