"""
Presets Panel Module

Manages prompt presets in the gallery's right column.
"""

import logging
from typing import Dict, TYPE_CHECKING, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QLabel, QPushButton
)

from src.utils.style_loader import PresetItemStyleManager

if TYPE_CHECKING:
    from src.models.preset_manager import PresetManager

from .gallery_widgets import PresetData, MAX_PROMPT_PREVIEW_LENGTH

logger = logging.getLogger(__name__)


class PresetItem(QWidget):
    """Individual preset item widget with name, preview, and action buttons."""

    run_clicked = pyqtSignal(str)  # preset_id
    paste_clicked = pyqtSignal(str)  # preset_id

    def __init__(self, preset: PresetData, parent=None):
        super().__init__(parent)
        self.preset = preset
        self._is_hovered = False
        self._style_manager = None

        self.setFixedHeight(80)
        self.setObjectName("PresetItem")
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

        # Main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # Top row: name and usage count
        top_layout = QHBoxLayout()

        self.name_label = QLabel(preset.name)
        self.name_label.setObjectName("preset_name")
        top_layout.addWidget(self.name_label)

        if preset.usage_count > 0:
            self.usage_label = QLabel(f"({preset.usage_count})")
            self.usage_label.setObjectName("preset_usage")
            top_layout.addWidget(self.usage_label)

        top_layout.addStretch()
        layout.addLayout(top_layout)

        # Prompt preview
        preview_text = self._truncate_prompt(preset.prompt)
        self.preview_label = QLabel(preview_text)
        self.preview_label.setObjectName("preset_preview")
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

    def set_style_manager(self, style_manager: 'PresetItemStyleManager') -> None:
        """Set the style manager for this item."""
        self._style_manager = style_manager
        self._apply_current_state()

    def _apply_current_state(self) -> None:
        """Apply the current state CSS to the item."""
        if self._style_manager:
            self._style_manager.apply_state(self, self._is_hovered)

    def _truncate_prompt(self, prompt: str, max_length: int = MAX_PROMPT_PREVIEW_LENGTH) -> str:
        """Truncate prompt for preview."""
        if len(prompt) <= max_length:
            return prompt
        return prompt[:max_length - 3] + "..."

    def enterEvent(self, event):
        """Handle mouse enter."""
        if not self._is_hovered:
            self._is_hovered = True
            self._apply_current_state()
        super().enterEvent(event)

    def leaveEvent(self, a0):
        """Handle mouse leave."""
        if self._is_hovered:
            self._is_hovered = False
            self._apply_current_state()
        super().leaveEvent(a0)


class PresetsPanel(QWidget):
    """Presets column widget with preset list and management."""

    # Signals
    preset_run_clicked = pyqtSignal(str)  # preset_id
    preset_paste_clicked = pyqtSignal(str)  # preset_id

    def __init__(self, preset_manager: 'PresetManager', parent=None):
        super().__init__(parent)
        self.preset_manager = preset_manager
        self.preset_items: Dict[str, PresetItem] = {}
        self._preset_item_style_manager: Optional[PresetItemStyleManager] = None

        self.setObjectName("PresetsPanel")
        self._setup_ui()

    def _setup_ui(self):
        """Setup the UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # Column header
        header = QLabel("Presets")
        header.setObjectName("column_header")
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
        self.presets_layout.addStretch()

        self.presets_scroll.setWidget(self.presets_container)
        layout.addWidget(self.presets_scroll)

    def set_style_manager(self, style_manager: 'PresetItemStyleManager') -> None:
        """Set the style manager for preset items."""
        self._preset_item_style_manager = style_manager
        for item in self.preset_items.values():
            item.set_style_manager(style_manager)

    async def load_presets(self, limit: int = 20):
        """Load presets from the preset manager."""
        try:
            self._clear_preset_items()

            # Since PresetManager stores presets by ID in its cache, we need to access them
            preset_cache = self.preset_manager._preset_cache

            # Sort presets: user presets first, then builtin presets
            sorted_presets = sorted(
                preset_cache.items(),
                key=lambda item: (item[1].is_builtin, item[0])  # False (user) before True (builtin), then by ID
            )

            for preset_id, preset in sorted_presets:
                if len(self.preset_items) >= limit:
                    break

                preset_data = PresetData(
                    id=preset_id,
                    name=preset.name,
                    prompt=preset.prompt,
                    description=preset.description,
                    usage_count=preset.usage_count,
                    created_at=preset.created_at
                )

                item = PresetItem(preset_data)
                item.run_clicked.connect(lambda pid: self.preset_run_clicked.emit(pid))
                item.paste_clicked.connect(lambda pid: self.preset_paste_clicked.emit(pid))

                if self._preset_item_style_manager:
                    item.set_style_manager(self._preset_item_style_manager)

                self.presets_layout.insertWidget(
                    self.presets_layout.count() - 1,
                    item
                )
                self.preset_items[preset_id] = item

            logger.debug(f"Loaded {len(self.preset_items)} presets from preset manager")

        except Exception as e:
            logger.error(f"Failed to load presets: {e}")

    def _clear_preset_items(self):
        """Clear all preset items."""
        for item in self.preset_items.values():
            item.deleteLater()
        self.preset_items.clear()

    async def refresh_presets(self) -> None:
        """Refresh presets from disk and reload the UI."""
        try:
            # Refresh presets from disk
            await self.preset_manager.refresh_presets()

            # Reload presets in UI
            await self.load_presets()

            logger.debug("Presets panel refreshed")

        except Exception as e:
            logger.error(f"Failed to refresh presets: {e}")
