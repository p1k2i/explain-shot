"""
Shared Gallery Widget Components

Data structures and utilities shared across gallery modules.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Any


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
    selected_screenshot_id: Optional[str] = None  # Now uses hash-based string ID
    selected_screenshot_metadata: Optional[Any] = None  # ScreenshotMetadata object
    selected_preset_id: Optional[int] = None
    chat_messages: Optional[List[ChatMessage]] = None
    is_loading: bool = False

    def __post_init__(self):
        if self.chat_messages is None:
            self.chat_messages = []


class GalleryEventTypes:
    """Event constants for gallery modules."""

    # Screenshot events
    SCREENSHOT_SELECTED = "gallery.screenshot.selected"
    SCREENSHOT_DESELECTED = "gallery.screenshot.deselected"

    # Preset events
    PRESET_RUN_CLICKED = "gallery.preset.run"
    PRESET_PASTE_CLICKED = "gallery.preset.paste"

    # Chat events
    CHAT_MESSAGE_SENT = "gallery.chat.message_sent"
    CHAT_MESSAGE_RECEIVED = "gallery.chat.message_received"

    # Gallery lifecycle
    GALLERY_INITIALIZED = "gallery.initialized"
    GALLERY_CLOSED = "gallery.closed"


# Gallery configuration constants
THUMBNAIL_SIZE = (120, 120)
THUMBNAIL_DISPLAY_SIZE = (118, 118)
PRESET_ITEM_HEIGHT = 80
GRID_COLS_PER_ROW = 2
MAX_FILENAME_LENGTH = 20
MAX_PROMPT_PREVIEW_LENGTH = 80
MAX_INDICATOR_LENGTH = 36
