"""
Gallery Components Module

Exports all gallery component classes for easy importing.
"""

from .custom_title_bar import CustomTitleBar
from .chat_interface import ChatInterface, ChatWidget
from .screenshots_gallery import ScreenshotGallery, ScreenshotItem, ThumbnailLoader
from .presets_panel import PresetsPanel, PresetItem
from .gallery_widgets import (
    PresetData, ChatMessage, GalleryState, GalleryEventTypes,
    THUMBNAIL_SIZE, THUMBNAIL_DISPLAY_SIZE, PRESET_ITEM_HEIGHT,
    GRID_COLS_PER_ROW, MAX_FILENAME_LENGTH, MAX_PROMPT_PREVIEW_LENGTH,
    MAX_INDICATOR_LENGTH
)

__all__ = [
    # Title bar
    'CustomTitleBar',

    # Chat interface
    'ChatInterface',
    'ChatWidget',

    # Screenshots gallery
    'ScreenshotGallery',
    'ScreenshotItem',
    'ThumbnailLoader',

    # Presets panel
    'PresetsPanel',
    'PresetItem',

    # Data structures
    'PresetData',
    'ChatMessage',
    'GalleryState',
    'GalleryEventTypes',

    # Constants
    'THUMBNAIL_SIZE',
    'THUMBNAIL_DISPLAY_SIZE',
    'PRESET_ITEM_HEIGHT',
    'GRID_COLS_PER_ROW',
    'MAX_FILENAME_LENGTH',
    'MAX_PROMPT_PREVIEW_LENGTH',
    'MAX_INDICATOR_LENGTH',
]
