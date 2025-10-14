"""
Gallery Window Module

Implements the main gallery interface for screenshot management, AI chat, and preset interactions.
This module provides a three-column layout with thumbnail display, chat interface, and preset management.
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING
from dataclasses import dataclass

from PyQt6.QtCore import (
    Qt, QObject, pyqtSignal, QSize, QBuffer, QFile
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QScrollArea, QTextBrowser,
    QLineEdit, QPushButton, QLabel, QFrame, QGridLayout
)
from PyQt6.QtGui import (
    QPixmap, QFont, QColor, QPainter
)

from src.utils.style_loader import load_stylesheet

try:
    from PIL import Image, ImageQt
    PIL_AVAILABLE = True
except ImportError:
    Image = None
    ImageQt = None
    PIL_AVAILABLE = False

if TYPE_CHECKING:
    from ..controllers.event_bus import EventBus
    from ..models.screenshot_manager import ScreenshotManager
    from ..models.database_manager import DatabaseManager
    from ..models.settings_manager import SettingsManager

from .. import EventTypes

logger = logging.getLogger(__name__)

# Gallery-specific data structures
@dataclass
class PresetData:
    """Represents a prompt preset for gallery display."""
    id: int
    name: str
    prompt: str
    description: str = ""
    usage_count: int = 0
    created_at: Optional[datetime] = None

@dataclass
class ChatMessage:
    """Represents a chat message in the gallery."""
    sender: str  # 'user', 'ai', 'system'
    content: str
    timestamp: datetime
    message_type: str = "text"  # 'text', 'image', 'error'

@dataclass
class GalleryState:
    """Tracks the current state of the gallery."""
    selected_screenshot_id: Optional[int] = None
    selected_preset_id: Optional[int] = None
    chat_messages: Optional[List[ChatMessage]] = None
    is_loading: bool = False

    def __post_init__(self):
        if self.chat_messages is None:
            self.chat_messages = []


class ThumbnailLoader(QObject):
    """Background thumbnail loader to prevent UI blocking."""

    thumbnail_loaded = pyqtSignal(int, bytes, str)  # screenshot_id, image_bytes, format
    loading_failed = pyqtSignal(int, str)  # screenshot_id, error_message

    def __init__(self, screenshot_manager: 'ScreenshotManager'):
        super().__init__()
        self.screenshot_manager = screenshot_manager
        self._cache = {}  # Cache for loaded thumbnails
        self._loading_queue = []
        self._is_processing = False

    async def load_thumbnail(self, screenshot_id: int, file_path: str, size: QSize = QSize(120, 120)):
        """Queue thumbnail loading."""
        if screenshot_id in self._cache:
            self.thumbnail_loaded.emit(screenshot_id, self._cache[screenshot_id][0], self._cache[screenshot_id][1])
            return

        self._loading_queue.append((screenshot_id, file_path, size))
        if not self._is_processing:
            await self._process_queue()

    async def _process_queue(self):
        """Process the thumbnail loading queue."""
        self._is_processing = True

        while self._loading_queue:
            screenshot_id, file_path, size = self._loading_queue.pop(0)

            try:
                await self._generate_thumbnail(screenshot_id, file_path, size)
                # Small delay to prevent overwhelming the UI
                await asyncio.sleep(0.01)

            except Exception as e:
                logger.warning(f"Failed to load thumbnail for {file_path}: {e}")
                self.loading_failed.emit(screenshot_id, str(e))

        self._is_processing = False

    async def _generate_thumbnail(self, screenshot_id: int, file_path: str, size: QSize):
        """Generate thumbnail for a screenshot."""
        if not PIL_AVAILABLE:
            # Fallback to a placeholder
            placeholder = self._create_placeholder(size, "No PIL")
            self.thumbnail_loaded.emit(screenshot_id, self._pixmap_to_bytes(placeholder), "PNG")
            return

        try:
            # Run PIL operations in thread pool
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self._pil_thumbnail_bytes, file_path, size)

            if result:
                image_bytes, format_str = result
                self._cache[screenshot_id] = (image_bytes, format_str)
                self.thumbnail_loaded.emit(screenshot_id, image_bytes, format_str)
            else:
                raise Exception("Failed to create thumbnail")

        except Exception as e:
            placeholder = self._create_placeholder(size, "Error")
            self.thumbnail_loaded.emit(screenshot_id, self._pixmap_to_bytes(placeholder), "PNG")
            logger.warning(f"Thumbnail generation failed for {file_path}: {e}")
            raise

    def _pil_thumbnail_bytes(self, file_path: str, size: QSize) -> Optional[tuple[bytes, str]]:
        """Generate thumbnail using PIL and return as bytes."""
        try:
            with Image.open(file_path) as img:  # type: ignore
                # Calculate aspect ratio preserving size
                img_ratio = img.width / img.height
                target_ratio = size.width() / size.height()

                if img_ratio > target_ratio:
                    # Image is wider, fit to width
                    new_width = size.width()
                    new_height = int(size.width() / img_ratio)
                else:
                    # Image is taller, fit to height
                    new_height = size.height()
                    new_width = int(size.height() * img_ratio)

                # Resize image
                img_resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)  # type: ignore

                # Convert to RGB if necessary for JPEG, keep as is for PNG
                if img_resized.mode not in ('RGB', 'RGBA'):
                    img_resized = img_resized.convert('RGB')

                # Save to bytes
                from io import BytesIO
                buffer = BytesIO()
                if img_resized.mode == 'RGBA':
                    format_str = 'PNG'
                    img_resized.save(buffer, format=format_str)
                else:
                    format_str = 'JPEG'
                    img_resized.save(buffer, format=format_str, quality=85)

                return buffer.getvalue(), format_str

        except Exception:
            logger.warning(f"PIL thumbnail generation failed for {file_path}")
            return None

    def _pixmap_to_bytes(self, pixmap: QPixmap) -> bytes:
        """Convert QPixmap to bytes for fallback."""
        # Convert QPixmap to QImage and save to bytes
        image = pixmap.toImage()
        buffer = QBuffer()
        buffer.open(QBuffer.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        return buffer.data().data()

    def _create_placeholder(self, size: QSize, text: str = "Loading") -> QPixmap:
        """Create a placeholder pixmap."""
        pixmap = QPixmap(size)
        pixmap.fill(QColor(70, 70, 70))

        painter = QPainter(pixmap)
        painter.setPen(QColor(200, 200, 200))
        painter.setFont(QFont("Arial", 8))
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, text)
        painter.end()

        return pixmap


class ScreenshotItem(QWidget):
    """Individual screenshot item widget with thumbnail and metadata."""

    clicked = pyqtSignal(int)  # screenshot_id

    def __init__(self, screenshot_id: int, filename: str, timestamp: datetime, parent=None):
        super().__init__(parent)
        self.screenshot_id = screenshot_id
        self.filename = filename
        self.timestamp = timestamp
        self._is_selected = False
        self._is_hovered = False

        self.setFixedSize(140, 160)
        self.setObjectName("ScreenshotItem")

        # Main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # Thumbnail label
        self.thumbnail_label = QLabel()
        self.thumbnail_label.setFixedSize(120, 120)
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail_label.setStyleSheet("border: 1px solid #555; background-color: #404040;")
        layout.addWidget(self.thumbnail_label)

        # Filename label (overlay on thumbnail)
        self.filename_label = QLabel(self._truncate_filename(filename))
        self.filename_label.setParent(self.thumbnail_label)
        self.filename_label.setGeometry(0, 0, 120, 20)  # Top overlay
        self.filename_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.filename_label.setStyleSheet("""
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(0,0,0,0.8), stop:1 rgba(0,0,0,0.2));
            color: #FFFFFF;
            font-size: 10px;
            font-weight: bold;
            border-radius: 0;
        """)

        # Timestamp label
        self.timestamp_label = QLabel(timestamp.strftime("%H:%M:%S"))
        self.timestamp_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.timestamp_label.setStyleSheet("color: #999; font-size: 10px;")
        layout.addWidget(self.timestamp_label)

        self._apply_theme()
        self._setup_animations()

    def _truncate_filename(self, filename: str, max_length: int = 20) -> str:
        """Truncate filename for display."""
        # Remove extension
        name_without_ext = os.path.splitext(filename)[0]
        if len(name_without_ext) <= max_length:
            return name_without_ext
        return name_without_ext[:max_length - 3] + "..."

    def set_thumbnail(self, pixmap: QPixmap):
        """Set the thumbnail pixmap."""
        scaled = pixmap.scaled(
            118, 118,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self.thumbnail_label.setPixmap(scaled)

    def set_selected(self, selected: bool):
        """Set selection state."""
        if self._is_selected != selected:
            self._is_selected = selected
            self._update_appearance()

    def is_selected(self) -> bool:
        """Check if item is selected."""
        return self._is_selected

    def mousePressEvent(self, a0):
        """Handle mouse clicks."""
        if a0 and hasattr(a0, 'button') and a0.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.screenshot_id)
        super().mousePressEvent(a0)

    def enterEvent(self, event):
        """Handle mouse enter."""
        self._is_hovered = True
        self._update_appearance()
        super().enterEvent(event)

    def leaveEvent(self, a0):
        """Handle mouse leave."""
        self._is_hovered = False
        self._update_appearance()
        super().leaveEvent(a0)

    def _apply_theme(self):
        """Apply dark theme styling."""
        self.setStyleSheet("""
            ScreenshotItem {
                background-color: #3A3A3A;
                border: 2px solid transparent;
                border-radius: 8px;
            }
            ScreenshotItem:hover {
                border-color: #555555;
                background-color: #404040;
            }
        """)

        self.filename_label.setStyleSheet("""
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(0,0,0,0.8), stop:1 rgba(0,0,0,0.2));
            color: #FFFFFF;
            font-size: 10px;
            font-weight: bold;
            border-radius: 0;
        """)

    def _setup_animations(self):
        """Setup hover and selection animations."""
        pass  # Placeholder for future animations

    def _update_appearance(self):
        """Update visual appearance based on state."""
        if self._is_selected:
            border_color = "#00A0FF"
            border_width = "5px"
            bg_color = "#1E3A5F"
        elif self._is_hovered:
            border_color = "#555555"
            border_width = "2px"
            bg_color = "#404040"
        else:
            border_color = "transparent"
            border_width = "2px"
            bg_color = "#3A3A3A"

        self.setStyleSheet(f"""
            ScreenshotItem {{
                background-color: {bg_color};
                border: {border_width} solid {border_color};
                border-radius: 8px;
            }}
        """)

        # Update filename label styling based on selection
        if self._is_selected:
            self.filename_label.setStyleSheet("""
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(0,160,255,0.95), stop:1 rgba(0,160,255,0.4));
                color: #FFFFFF;
                font-size: 12px;
                font-weight: bold;
                border-radius: 0;
            """)
        else:
            self.filename_label.setStyleSheet("""
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(0,0,0,0.8), stop:1 rgba(0,0,0,0.2));
                color: #FFFFFF;
                font-size: 10px;
                font-weight: bold;
                border-radius: 0;
            """)


class PresetItem(QWidget):
    """Individual preset item widget with name, preview, and action buttons."""

    run_clicked = pyqtSignal(int)  # preset_id
    paste_clicked = pyqtSignal(int)  # preset_id

    def __init__(self, preset: PresetData, parent=None):
        super().__init__(parent)
        self.preset = preset

        self.setFixedHeight(80)
        self.setObjectName("PresetItem")

        # Main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # Top row: name and usage count
        top_layout = QHBoxLayout()

        self.name_label = QLabel(preset.name)
        self.name_label.setStyleSheet("font-weight: bold; color: #FFFFFF;")
        top_layout.addWidget(self.name_label)

        if preset.usage_count > 0:
            usage_label = QLabel(f"({preset.usage_count})")
            usage_label.setStyleSheet("color: #999; font-size: 10px;")
            top_layout.addWidget(usage_label)

        top_layout.addStretch()
        layout.addLayout(top_layout)

        # Prompt preview
        preview_text = self._truncate_prompt(preset.prompt)
        self.preview_label = QLabel(preview_text)
        self.preview_label.setStyleSheet("color: #CCC; font-size: 10px;")
        self.preview_label.setWordWrap(True)
        self.preview_label.setMaximumHeight(24)
        layout.addWidget(self.preview_label)

        # Button row
        button_layout = QHBoxLayout()

        self.run_button = QPushButton("Run")
        self.run_button.setFixedSize(50, 20)
        self.run_button.clicked.connect(lambda: self.run_clicked.emit(preset.id))

        self.paste_button = QPushButton("Paste")
        self.paste_button.setFixedSize(50, 20)
        self.paste_button.clicked.connect(lambda: self.paste_clicked.emit(preset.id))

        button_layout.addWidget(self.run_button)
        button_layout.addWidget(self.paste_button)
        button_layout.addStretch()

        layout.addLayout(button_layout)

        self._apply_theme()

    def _truncate_prompt(self, prompt: str, max_length: int = 80) -> str:
        """Truncate prompt for preview."""
        if len(prompt) <= max_length:
            return prompt
        return prompt[:max_length - 3] + "..."

    def _apply_theme(self):
        """Apply dark theme styling."""
        self.setStyleSheet("""
            PresetItem {
                background-color: #3A3A3A;
                border: 1px solid #555;
                border-radius: 4px;
                margin: 2px;
            }
            PresetItem:hover {
                background-color: #404040;
                border-color: #007ACC;
            }
        """)

        button_style = """
            QPushButton {
                background-color: #007ACC;
                color: white;
                border: none;
                border-radius: 3px;
                font-size: 9px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0099FF;
            }
            QPushButton:pressed {
                background-color: #0066CC;
            }
        """

        self.run_button.setStyleSheet(button_style)
        self.paste_button.setStyleSheet(button_style)


class ChatWidget(QWidget):
    """Chat interface widget for AI interactions."""

    message_sent = pyqtSignal(str)  # message content

    def __init__(self, parent=None):
        super().__init__(parent)
        self.chat_messages = []

        # Main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Chat history
        self.chat_history = QTextBrowser()
        self.chat_history.setMinimumHeight(400)
        layout.addWidget(self.chat_history)

        # Input area
        input_layout = QHBoxLayout()

        self.chat_input = QLineEdit()
        self.chat_input.setPlaceholderText("Type your message...")
        self.chat_input.returnPressed.connect(self._send_message)

        self.send_button = QPushButton("Send")
        self.send_button.setFixedSize(60, 30)
        self.send_button.clicked.connect(self._send_message)

        input_layout.addWidget(self.chat_input)
        input_layout.addWidget(self.send_button)

        layout.addLayout(input_layout)

        # Status bar
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #999; font-size: 10px; padding: 4px;")
        layout.addWidget(self.status_label)

        self._apply_theme()
        self._add_welcome_message()

    def _send_message(self):
        """Handle sending a message."""
        text = self.chat_input.text().strip()
        if text:
            self.message_sent.emit(text)
            self.add_user_message(text)
            self.chat_input.clear()

    def add_user_message(self, content: str):
        """Add a user message to the chat."""
        message = ChatMessage(
            sender="user",
            content=content,
            timestamp=datetime.now()
        )
        self.chat_messages.append(message)
        self._update_chat_display()

    def add_ai_message(self, content: str):
        """Add an AI response to the chat."""
        message = ChatMessage(
            sender="ai",
            content=content,
            timestamp=datetime.now()
        )
        self.chat_messages.append(message)
        self._update_chat_display()

    def add_system_message(self, content: str):
        """Add a system message to the chat."""
        message = ChatMessage(
            sender="system",
            content=content,
            timestamp=datetime.now()
        )
        self.chat_messages.append(message)
        self._update_chat_display()

    def set_prompt_text(self, prompt: str):
        """Set text in the input field."""
        self.chat_input.setText(prompt)
        self.chat_input.setFocus()

    def clear_chat(self):
        """Clear chat history."""
        self.chat_messages.clear()
        self._add_welcome_message()
        self._update_chat_display()

    def _add_welcome_message(self):
        """Add welcome message to chat."""
        welcome = ChatMessage(
            sender="system",
            content="Welcome to the AI Chat! Select a screenshot and use presets to get started.",
            timestamp=datetime.now()
        )
        self.chat_messages.append(welcome)

    def _update_chat_display(self):
        """Update the chat history display."""
        html_content = self._generate_chat_html()
        self.chat_history.setHtml(html_content)

        # Scroll to bottom
        scrollbar = self.chat_history.verticalScrollBar()
        if scrollbar:
            scrollbar.setValue(scrollbar.maximum())

    def _generate_chat_html(self) -> str:
        """Generate HTML for chat messages."""
        html = """
        <style>
            body {
                background-color: #2E2E2E;
                color: #FFFFFF;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                margin: 0;
                padding: 10px;
                line-height: 1.4;
            }
            .message {
                margin: 12px 0;
                padding: 12px 16px;
                border-radius: 16px;
                max-width: 80%;
                word-wrap: break-word;
                position: relative;
            }
            .user {
                background-color: #007ACC;
                margin-left: auto;
                margin-right: 0;
                text-align: left;
            }
            .ai {
                background-color: #404040;
                margin-left: 0;
                margin-right: auto;
                text-align: left;
            }
            .system {
                background-color: #555555;
                text-align: center;
                font-style: italic;
                margin: 12px auto;
                max-width: 70%;
            }
            .timestamp {
                font-size: 9px;
                color: #AAA;
                margin-top: 6px;
                opacity: 0.7;
            }
        </style>
        <body>
        """

        for message in self.chat_messages:
            css_class = message.sender
            timestamp_str = message.timestamp.strftime("%H:%M:%S")

            html += f'''
            <div class="message {css_class}">
                <div>{message.content}</div>
                <div class="timestamp">{timestamp_str}</div>
            </div>
            '''

        html += "</body>"
        return html

    def _apply_theme(self):
        """Apply dark theme styling."""
        self.setStyleSheet("""
            QTextBrowser {
                background-color: #2E2E2E;
                border: 1px solid #555;
                border-radius: 4px;
            }
            QLineEdit {
                background-color: #404040;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 8px;
                color: #FFFFFF;
            }
            QLineEdit:focus {
                border-color: #007ACC;
            }
        """)

        self.send_button.setStyleSheet("""
            QPushButton {
                background-color: #007ACC;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0099FF;
            }
            QPushButton:pressed {
                background-color: #0066CC;
            }
        """)


class GalleryWindow(QWidget):
    """Main gallery window with three-column layout."""

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

        # State management
        self.gallery_state = GalleryState()
        self._initialized = False
        self._current_theme = "dark"  # Default theme, will be loaded from settings

        # Components
        self.thumbnail_loader = None
        self.screenshot_items = {}  # screenshot_id -> ScreenshotItem
        self.preset_items = {}  # preset_id -> PresetItem
        self.selection_indicator = None  # Will be created in _setup_ui

        # Initialize UI
        self._setup_ui()

        logger.info("GalleryWindow created")

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

    def _handle_ollama_response(self, event_data) -> None:
        """Handle Ollama response events."""
        try:
            data = event_data.data
            response_content = data.get('response', '')

            if response_content:
                # Add AI response to chat
                self.chat_widget.add_ai_message(response_content)

        except Exception as e:
            logger.error(f"Error handling Ollama response: {e}")
            self.chat_widget.add_system_message("Error processing AI response")

    def _handle_streaming_update(self, event_data) -> None:
        """Handle streaming update events."""
        try:
            data = event_data.data
            content = data.get('content', '')

            # For now, we'll collect the full response and display it
            # In a full implementation, we'd update the current message incrementally
            if content:
                logger.debug(f"Streaming update: {content[:50]}...")

        except Exception as e:
            logger.error(f"Error handling streaming update: {e}")

    async def initialize(self) -> bool:
        """Initialize the gallery window."""
        try:
            logger.info("Initializing GalleryWindow...")

            # Load theme from settings
            self._current_theme = await self.settings_manager.get_setting("ui.theme", "dark")

            # Apply theme with loaded settings
            self._apply_theme()

            # Initialize thumbnail loader
            self.thumbnail_loader = ThumbnailLoader(self.screenshot_manager)
            self.thumbnail_loader.thumbnail_loaded.connect(self._on_thumbnail_loaded)
            self.thumbnail_loader.loading_failed.connect(self._on_thumbnail_failed)

            # Subscribe to Ollama events
            await self._subscribe_to_events()

            # Load initial data
            await self._load_screenshots()
            await self._load_presets()

            self._initialized = True
            logger.info("GalleryWindow initialization complete")
            return True

        except Exception as e:
            logger.error(f"GalleryWindow initialization failed: {e}")
            return False

    def _setup_ui(self):
        """Setup the user interface."""
        self.setWindowTitle("Screenshot Gallery")
        self.setGeometry(100, 100, 1200, 800)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowOpacity(0.9)

        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Custom title bar
        self._create_title_bar()
        main_layout.addWidget(self.title_bar)

        # Three-column splitter
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setSizes([400, 400, 400])  # Equal width columns

        # Left column - Screenshots
        self._create_screenshots_column()
        self.splitter.addWidget(self.screenshots_frame)

        # Middle column - Chat
        self._create_chat_column()
        self.splitter.addWidget(self.chat_frame)

        # Right column - Presets
        self._create_presets_column()
        self.splitter.addWidget(self.presets_frame)

        main_layout.addWidget(self.splitter)

        # Connect signals
        self._connect_signals()

    def _create_title_bar(self):
        """Create custom title bar with controls."""
        self.title_bar = QFrame()
        self.title_bar.setFixedHeight(40)
        self.title_bar.setObjectName("TitleBar")

        layout = QHBoxLayout(self.title_bar)
        layout.setContentsMargins(10, 0, 10, 0)

        # Title
        title_label = QLabel("Screenshot Gallery")
        title_label.setStyleSheet("color: #FFFFFF; font-weight: bold; font-size: 14px;")
        layout.addWidget(title_label)

        layout.addStretch()

        # Window controls
        self.minimize_button = QPushButton("−")
        self.minimize_button.setFixedSize(30, 30)
        self.minimize_button.clicked.connect(self.showMinimized)

        self.close_button = QPushButton("×")
        self.close_button.setFixedSize(30, 30)
        self.close_button.clicked.connect(self.close)

        layout.addWidget(self.minimize_button)
        layout.addWidget(self.close_button)

    def _create_screenshots_column(self):
        """Create the screenshots column."""
        self.screenshots_frame = QFrame()
        layout = QVBoxLayout(self.screenshots_frame)
        layout.setContentsMargins(8, 8, 8, 8)

        # Column header with selection indicator
        header_layout = QHBoxLayout()
        header = QLabel("Screenshots")
        header.setStyleSheet("font-size: 16px; font-weight: bold; color: #FFFFFF; padding: 8px;")
        header_layout.addWidget(header)

        self.selection_indicator = QLabel("None selected")
        self.selection_indicator.setStyleSheet("font-size: 12px; color: #999; padding: 8px; font-style: italic;")
        header_layout.addWidget(self.selection_indicator)
        header_layout.addStretch()

        layout.addLayout(header_layout)

        # Scroll area for screenshots
        self.screenshots_scroll = QScrollArea()
        self.screenshots_scroll.setWidgetResizable(True)
        self.screenshots_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # Container for screenshot items
        self.screenshots_container = QWidget()
        self.screenshots_layout = QGridLayout(self.screenshots_container)
        self.screenshots_layout.setContentsMargins(4, 4, 4, 4)
        self.screenshots_layout.setSpacing(8)

        self.screenshots_scroll.setWidget(self.screenshots_container)
        layout.addWidget(self.screenshots_scroll)

    def _create_chat_column(self):
        """Create the chat column."""
        self.chat_frame = QFrame()
        layout = QVBoxLayout(self.chat_frame)
        layout.setContentsMargins(8, 8, 8, 8)

        # Column header
        header = QLabel("AI Chat")
        header.setStyleSheet("font-size: 16px; font-weight: bold; color: #FFFFFF; padding: 8px;")
        layout.addWidget(header)

        # Chat widget
        self.chat_widget = ChatWidget()
        layout.addWidget(self.chat_widget)

    def _create_presets_column(self):
        """Create the presets column."""
        self.presets_frame = QFrame()
        layout = QVBoxLayout(self.presets_frame)
        layout.setContentsMargins(8, 8, 8, 8)

        # Column header
        header = QLabel("Presets")
        header.setStyleSheet("font-size: 16px; font-weight: bold; color: #FFFFFF; padding: 8px;")
        layout.addWidget(header)

        # Scroll area for presets
        self.presets_scroll = QScrollArea()
        self.presets_scroll.setWidgetResizable(True)
        self.presets_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # Container for preset items
        self.presets_container = QWidget()
        self.presets_layout = QVBoxLayout(self.presets_container)
        self.presets_layout.setContentsMargins(4, 4, 4, 4)
        self.presets_layout.setSpacing(4)
        self.presets_layout.addStretch()  # Push items to top

        self.presets_scroll.setWidget(self.presets_container)
        layout.addWidget(self.presets_scroll)

    def _connect_signals(self):
        """Connect internal signals."""
        # Chat signals
        self.chat_widget.message_sent.connect(self._on_chat_message_sent)

    async def show_gallery(self, pre_selected_screenshot_id: Optional[int] = None):
        """Show the gallery window with optional pre-selection."""
        try:
            if not self._initialized:
                await self.initialize()

            # Pre-select screenshot if provided
            if pre_selected_screenshot_id and pre_selected_screenshot_id in self.screenshot_items:
                await self._select_screenshot(pre_selected_screenshot_id)

            # Show window
            self.show()
            self.raise_()
            self.activateWindow()

            logger.info(f"Gallery shown with pre-selection: {pre_selected_screenshot_id}")

        except Exception as e:
            logger.error(f"Failed to show gallery: {e}")

    async def _load_screenshots(self):
        """Load screenshots from the screenshot manager."""
        try:
            screenshots = await self.screenshot_manager.get_recent_screenshots(limit=50)

            # Clear existing items
            self._clear_screenshot_items()

            # Add screenshot items in grid layout
            row, col = 0, 0
            cols_per_row = 2

            for screenshot in screenshots:
                if screenshot.id is not None:  # Ensure screenshot has valid ID
                    item = ScreenshotItem(
                        screenshot.id,
                        screenshot.filename,
                        screenshot.timestamp
                    )
                    item.clicked.connect(self._on_screenshot_clicked)

                    self.screenshots_layout.addWidget(item, row, col)
                    self.screenshot_items[screenshot.id] = item

                    # Load thumbnail asynchronously
                    if self.thumbnail_loader:
                        await self.thumbnail_loader.load_thumbnail(
                            screenshot.id,
                            screenshot.full_path
                        )

                # Update grid position
                col += 1
                if col >= cols_per_row:
                    col = 0
                    row += 1

            logger.info(f"Loaded {len(screenshots)} screenshots")

        except Exception as e:
            logger.error(f"Failed to load screenshots: {e}")
            self.chat_widget.add_system_message("Failed to load screenshots")

    async def _load_presets(self):
        """Load presets from the database manager."""
        try:
            # Load presets from database
            presets = await self.database_manager.get_presets(limit=20)

            # Clear existing items
            self._clear_preset_items()

            # Convert to PresetData objects and add to UI
            for preset in presets:
                if preset.id is not None:  # Ensure preset has valid ID
                    preset_data = PresetData(
                        id=preset.id,
                        name=preset.name,
                        prompt=preset.prompt,
                        description=preset.description,
                        usage_count=preset.usage_count,
                        created_at=preset.created_at
                    )

                    item = PresetItem(preset_data)
                    item.run_clicked.connect(self._on_preset_run)
                    item.paste_clicked.connect(self._on_preset_paste)

                    self.presets_layout.insertWidget(
                        self.presets_layout.count() - 1,  # Before stretch
                        item
                    )
                    self.preset_items[preset.id] = item

            logger.info(f"Loaded {len(presets)} presets from database")

        except Exception as e:
            logger.error(f"Failed to load presets: {e}")
            self.chat_widget.add_system_message("Failed to load presets")

    def _clear_screenshot_items(self):
        """Clear all screenshot items."""
        for item in self.screenshot_items.values():
            item.deleteLater()
        self.screenshot_items.clear()

    def _clear_preset_items(self):
        """Clear all preset items."""
        for item in self.preset_items.values():
            item.deleteLater()
        self.preset_items.clear()

    async def _select_screenshot(self, screenshot_id: int):
        """Select a screenshot and update UI state."""
        # Deselect all items
        for item in self.screenshot_items.values():
            item.set_selected(False)

        # Select the target item
        if screenshot_id in self.screenshot_items:
            self.screenshot_items[screenshot_id].set_selected(True)
            self.gallery_state.selected_screenshot_id = screenshot_id

            # Update selection indicator
            if self.selection_indicator:
                item = self.screenshot_items[screenshot_id]
                filename = item.filename
                truncated = self._truncate_filename_for_indicator(filename)
                self.selection_indicator.setText(f"{truncated}")
                self.selection_indicator.setStyleSheet("font-size: 12px; color: #00A0FF; padding: 8px; font-weight: bold;")

            # Emit selection event
            self.screenshot_selected.emit(screenshot_id)

            # Update chat context
            item = self.screenshot_items[screenshot_id]
            self.chat_widget.add_system_message(f"Selected screenshot: {item.filename}")

            logger.info(f"Screenshot selected: {screenshot_id}")
        else:
            # No selection
            self.gallery_state.selected_screenshot_id = None
            if self.selection_indicator:
                self.selection_indicator.setText("None selected")
                self.selection_indicator.setStyleSheet("font-size: 12px; color: #999; padding: 8px; font-style: italic;")

    def _on_screenshot_clicked(self, screenshot_id: int):
        """Handle screenshot item clicks."""
        asyncio.create_task(self._select_screenshot(screenshot_id))

    def _on_preset_run(self, preset_id: int):
        """Handle preset run button clicks."""
        if self.gallery_state.selected_screenshot_id is None:
            self.chat_widget.add_system_message("Please select a screenshot first")
            return

        # Run async preset retrieval
        asyncio.create_task(self._run_preset_async(preset_id))

    def _on_preset_paste(self, preset_id: int):
        """Handle preset paste button clicks."""
        # Run async preset retrieval
        asyncio.create_task(self._paste_preset_async(preset_id))

    async def _run_preset_async(self, preset_id: int):
        """Handle preset run asynchronously."""
        try:
            preset = await self._get_preset_by_id(preset_id)
            if preset:
                # Show user message
                self.chat_widget.add_user_message(f"Running preset: {preset.name}")

                # Emit preset execution event through EventBus
                await self.event_bus.emit(
                    EventTypes.GALLERY_PRESET_EXECUTED,
                    {
                        "preset_id": preset_id,
                        "screenshot_context": str(self.gallery_state.selected_screenshot_id)
                    },
                    source="GalleryWindow"
                )

                # Increment usage count in database
                await self.database_manager.increment_preset_usage(preset_id)

                logger.info(f"Preset run: {preset_id} on screenshot {self.gallery_state.selected_screenshot_id}")
        except Exception as e:
            logger.error(f"Failed to run preset {preset_id}: {e}")
            self.chat_widget.add_system_message("Failed to run preset")

    async def _paste_preset_async(self, preset_id: int):
        """Handle preset paste asynchronously."""
        try:
            preset = await self._get_preset_by_id(preset_id)
            if preset:
                self.chat_widget.set_prompt_text(preset.prompt)
                logger.info(f"Preset pasted: {preset_id}")
        except Exception as e:
            logger.error(f"Failed to paste preset {preset_id}: {e}")
            self.chat_widget.add_system_message("Failed to paste preset")

    def _on_chat_message_sent(self, message: str):
        """Handle chat message sending."""
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

        logger.info(f"Chat message sent: {message}")

    def _on_thumbnail_loaded(self, screenshot_id: int, image_bytes: bytes, format_str: str):
        """Handle thumbnail loading completion."""
        if screenshot_id in self.screenshot_items:
            # Create QPixmap from bytes in main thread
            pixmap = QPixmap()
            pixmap.loadFromData(image_bytes, format_str.upper())
            self.screenshot_items[screenshot_id].set_thumbnail(pixmap)

    def _on_thumbnail_failed(self, screenshot_id: int, error_message: str):
        """Handle thumbnail loading failure."""
        logger.warning(f"Thumbnail loading failed for {screenshot_id}: {error_message}")
        # Could show an error icon or placeholder here

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
            logger.error(f"Failed to get preset {preset_id}: {e}")
            return None

    def _apply_theme(self):
        """Apply theme styling."""
        theme = self._current_theme
        stylesheet = load_stylesheet("gallery", theme, "base")
        if stylesheet:
            self.setStyleSheet(stylesheet)
        else:
            logger.error(f"Failed to load stylesheet for gallery/{theme}/base")

    def _truncate_filename_for_indicator(self, filename: str, max_length: int = 36) -> str:
        """Truncate filename for the selection indicator."""
        if len(filename) <= max_length:
            return filename
        return filename[:max_length - 3] + "..."

    def closeEvent(self, a0):
        """Handle window close event."""
        self.gallery_closed.emit()
        logger.info("Gallery window closed")
        super().closeEvent(a0)

    def mousePressEvent(self, a0):
        """Handle mouse press for window dragging."""
        if a0 and hasattr(a0, 'button') and hasattr(a0, 'position'):
            if a0.button() == Qt.MouseButton.LeftButton and a0.position().y() < 40:
                self.drag_pos = a0.globalPosition().toPoint() - self.frameGeometry().topLeft()
                a0.accept()

    def mouseMoveEvent(self, a0):
        """Handle mouse move for window dragging."""
        if a0 and hasattr(self, 'drag_pos') and hasattr(a0, 'buttons') and hasattr(a0, 'globalPosition'):
            if a0.buttons() == Qt.MouseButton.LeftButton:
                self.move(a0.globalPosition().toPoint() - self.drag_pos)
                a0.accept()
