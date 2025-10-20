"""
Screenshots Gallery Module

Manages screenshot display, thumbnail loading, and selection in the gallery's left column.
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import Optional, Dict, TYPE_CHECKING

from PyQt6.QtCore import (
    Qt, QObject, pyqtSignal, QSize, QBuffer
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QLabel, QGridLayout
)
from PyQt6.QtGui import (
    QPixmap, QFont, QColor, QPainter
)

from src.utils.style_loader import ScreenshotItemStyleManager

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    Image = None
    PIL_AVAILABLE = False

if TYPE_CHECKING:
    from src.models.screenshot_manager import ScreenshotManager

from .gallery_widgets import (
    THUMBNAIL_SIZE, THUMBNAIL_DISPLAY_SIZE,
    GRID_COLS_PER_ROW, MAX_FILENAME_LENGTH
)

logger = logging.getLogger(__name__)


class ThumbnailLoader(QObject):
    """Asynchronous thumbnail loading with caching and progressive loading."""

    thumbnail_loaded = pyqtSignal(str, bytes, str)  # screenshot_id (now string), image_bytes, format
    loading_failed = pyqtSignal(str, str)  # screenshot_id (now string), error_message
    loading_started = pyqtSignal(str)  # screenshot_id (now string) - emitted when loading begins

    def __init__(self, screenshot_manager: 'ScreenshotManager'):
        super().__init__()
        self.screenshot_manager = screenshot_manager
        self._cache: Dict[str, tuple[bytes, str]] = {}  # Now uses string keys
        self._loading_queue: list = []
        self._is_processing = False
        self._loading_set: set = set()  # Track what's currently being loaded
        self._max_concurrent_loads = 3  # Limit concurrent thumbnail generation

    async def load_thumbnail(self, screenshot_id: str, file_path: str, size: QSize = QSize(*THUMBNAIL_SIZE)):
        """Queue thumbnail loading with immediate placeholder emission."""
        # Check cache first
        if screenshot_id in self._cache:
            self.thumbnail_loaded.emit(screenshot_id, self._cache[screenshot_id][0], self._cache[screenshot_id][1])
            return

        # Check if already loading
        if screenshot_id in self._loading_set:
            return

        # Add to loading set and emit loading started signal
        self._loading_set.add(screenshot_id)
        self.loading_started.emit(screenshot_id)

        # Queue for processing
        self._loading_queue.append((screenshot_id, file_path, size))

        # Start processing if not already running
        if not self._is_processing:
            asyncio.create_task(self._process_queue())

    async def _process_queue(self):
        """Process the thumbnail loading queue with concurrency control."""
        if self._is_processing:
            return

        self._is_processing = True
        concurrent_tasks = []

        try:
            while self._loading_queue or concurrent_tasks:
                # Start new tasks up to the limit
                while len(concurrent_tasks) < self._max_concurrent_loads and self._loading_queue:
                    screenshot_id, file_path, size = self._loading_queue.pop(0)
                    task = asyncio.create_task(self._generate_thumbnail(screenshot_id, file_path, size))
                    concurrent_tasks.append(task)

                # Wait for at least one task to complete
                if concurrent_tasks:
                    done, pending = await asyncio.wait(concurrent_tasks, return_when=asyncio.FIRST_COMPLETED)
                    concurrent_tasks = list(pending)

                    # Process completed tasks
                    for task in done:
                        try:
                            await task
                        except Exception as e:
                            logger.warning(f"Thumbnail generation task failed: {e}")

                # Small delay to prevent overwhelming the UI
                await asyncio.sleep(0.001)

        finally:
            self._is_processing = False

    async def _generate_thumbnail(self, screenshot_id: str, file_path: str, size: QSize):
        """Generate thumbnail for a screenshot."""
        try:
            if not PIL_AVAILABLE:
                placeholder = self._create_placeholder(size, "No PIL")
                self.thumbnail_loaded.emit(screenshot_id, self._pixmap_to_bytes(placeholder), "PNG")
                return

            try:
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

        finally:
            # Remove from loading set when done (success or failure)
            self._loading_set.discard(screenshot_id)

    def _pil_thumbnail_bytes(self, file_path: str, size: QSize) -> Optional[tuple[bytes, str]]:
        """Generate thumbnail using PIL and return as bytes."""
        try:
            with Image.open(file_path) as img:  # type: ignore
                img_ratio = img.width / img.height
                target_ratio = size.width() / size.height()

                if img_ratio > target_ratio:
                    new_width = size.width()
                    new_height = int(size.width() / img_ratio)
                else:
                    new_height = size.height()
                    new_width = int(size.height() * img_ratio)

                img_resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)  # type: ignore

                if img_resized.mode not in ('RGB', 'RGBA'):
                    img_resized = img_resized.convert('RGB')

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
        """Convert QPixmap to bytes."""
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

    clicked = pyqtSignal(str)  # screenshot_id (now hash-based string)

    def __init__(self, screenshot_id: str, filename: str, timestamp: datetime, parent=None):
        super().__init__(parent)
        self.screenshot_id = screenshot_id
        self.filename = filename
        self.timestamp = timestamp
        self._is_selected = False
        self._is_hovered = False
        self._is_loading = False
        self._style_manager = None

        self.setFixedSize(140, 160)
        self.setObjectName("ScreenshotItem")
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

        # Main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # Thumbnail label
        self.thumbnail_label = QLabel()
        self.thumbnail_label.setFixedSize(120, 120)
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail_label.setObjectName("thumbnail_label")
        layout.addWidget(self.thumbnail_label)

        # Filename label (overlay)
        self.filename_label = QLabel(self._truncate_filename(filename))
        self.filename_label.setParent(self.thumbnail_label)
        self.filename_label.setGeometry(0, 100, 120, 20)
        self.filename_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.filename_label.setObjectName("filename_label")

        # Timestamp label
        self.timestamp_label = QLabel(timestamp.strftime("%H:%M:%S"))
        self.timestamp_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.timestamp_label.setObjectName("timestamp_label")
        layout.addWidget(self.timestamp_label)

        # Set initial loading placeholder
        self._show_loading_placeholder()

    def _show_loading_placeholder(self):
        """Show a loading placeholder thumbnail."""
        self._is_loading = True
        placeholder = self._create_loading_placeholder()
        self.thumbnail_label.setPixmap(placeholder)

    def _create_loading_placeholder(self) -> QPixmap:
        """Create a loading placeholder pixmap with animation-ready styling."""
        pixmap = QPixmap(120, 120)
        pixmap.fill(QColor(50, 50, 50))  # Dark gray background

        painter = QPainter(pixmap)
        painter.setPen(QColor(150, 150, 150))
        painter.setFont(QFont("Arial", 9))

        # Draw loading text
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "Loading...")

        # Draw a simple border
        painter.setPen(QColor(80, 80, 80))
        painter.drawRect(pixmap.rect().adjusted(1, 1, -2, -2))

        painter.end()
        return pixmap

    def set_style_manager(self, style_manager: 'ScreenshotItemStyleManager') -> None:
        """Set the style manager for this item."""
        self._style_manager = style_manager
        self._apply_current_state()

    def _apply_current_state(self) -> None:
        """Apply the current state CSS to the item."""
        if self._style_manager:
            self._style_manager.apply_state(self, self._is_selected, self._is_hovered)

    def _truncate_filename(self, filename: str, max_length: int = MAX_FILENAME_LENGTH) -> str:
        """Truncate filename for display."""
        name_without_ext = os.path.splitext(filename)[0]
        if len(name_without_ext) <= max_length:
            return name_without_ext
        return name_without_ext[:max_length - 3] + "..."

    def set_thumbnail(self, pixmap: QPixmap):
        """Set the thumbnail pixmap and mark loading as complete."""
        self._is_loading = False
        scaled = pixmap.scaled(
            *THUMBNAIL_DISPLAY_SIZE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self.thumbnail_label.setPixmap(scaled)

    def set_selected(self, selected: bool):
        """Set selection state."""
        if self._is_selected != selected:
            self._is_selected = selected
            self._apply_current_state()

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


class ScreenshotGallery(QWidget):
    """Screenshots column widget with grid gallery and selection indicator."""

    # Signals
    screenshot_selected = pyqtSignal(str)  # screenshot_id (now hash-based string)
    screenshot_deselected = pyqtSignal()

    def __init__(self, screenshot_manager: 'ScreenshotManager', parent=None):
        super().__init__(parent)
        self.screenshot_manager = screenshot_manager
        self.thumbnail_loader: Optional[ThumbnailLoader] = None
        self.screenshot_items: Dict[str, ScreenshotItem] = {}  # Now uses string keys
        self._screenshot_item_style_manager: Optional[ScreenshotItemStyleManager] = None
        self._selected_screenshot_id: Optional[str] = None  # Now string-based

        self.setObjectName("ScreenshotGallery")
        self._setup_ui()

    def _setup_ui(self):
        """Setup the UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # Column header with selection indicator
        header_layout = QHBoxLayout()
        header = QLabel("Screenshots")
        header.setObjectName("column_header")
        header_layout.addWidget(header)

        self.selection_indicator = QLabel("None selected")
        self.selection_indicator.setObjectName("selection_indicator")
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

    def set_style_manager(self, style_manager: 'ScreenshotItemStyleManager') -> None:
        """Set the style manager for screenshot items."""
        self._screenshot_item_style_manager = style_manager
        for item in self.screenshot_items.values():
            item.set_style_manager(style_manager)

    def initialize_thumbnail_loader(self, screenshot_manager: 'ScreenshotManager'):
        """Initialize the thumbnail loader."""
        self.thumbnail_loader = ThumbnailLoader(screenshot_manager)
        self.thumbnail_loader.thumbnail_loaded.connect(self._on_thumbnail_loaded)
        self.thumbnail_loader.loading_failed.connect(self._on_thumbnail_failed)
        self.thumbnail_loader.loading_started.connect(self._on_thumbnail_loading_started)

    async def load_screenshots(self, limit: int = 50):
        """Load screenshots from the screenshot manager."""
        try:
            screenshots = await self.screenshot_manager.get_recent_screenshots(limit=limit)

            self._clear_screenshot_items()

            row, col = 0, 0

            # Sort screenshots by timestamp, newest first
            screenshots_sorted = sorted(screenshots, key=lambda s: s.timestamp, reverse=True)

            for screenshot in screenshots_sorted:
                # Use hash as unique identifier instead of database ID
                screenshot_hash = screenshot.hash or screenshot.unique_id
                if screenshot_hash:
                    item = ScreenshotItem(
                        screenshot_hash,
                        screenshot.filename,
                        screenshot.timestamp
                    )
                    item.clicked.connect(self._on_screenshot_clicked)

                    if self._screenshot_item_style_manager:
                        item.set_style_manager(self._screenshot_item_style_manager)

                    self.screenshots_layout.addWidget(item, row, col)
                    self.screenshot_items[screenshot_hash] = item

                    # Queue thumbnail loading (this will show placeholder immediately)
                    if self.thumbnail_loader:
                        await self.thumbnail_loader.load_thumbnail(
                            screenshot_hash,
                            screenshot.full_path
                        )

                col += 1
                if col >= GRID_COLS_PER_ROW:
                    col = 0
                    row += 1

            logger.info(f"Loaded {len(screenshots)} screenshots (newest first)")

        except Exception as e:
            logger.error(f"Failed to load screenshots: {e}")

    async def refresh_screenshots(self, limit: int = 50, force_scan: bool = False):
        """Refresh screenshots - optimized for incremental updates."""
        try:
            # Get current screenshots
            if force_scan:
                # Force a fresh directory scan to catch any new files
                logger.debug("Forcing fresh directory scan for screenshots")
                screenshots = await self.screenshot_manager.scan_screenshot_directory()
                screenshots = screenshots[:limit]  # Limit the results
            else:
                screenshots = await self.screenshot_manager.get_recent_screenshots(limit=limit)

            # Build set of current screenshot hashes for comparison
            current_hashes = {screenshot.hash or screenshot.unique_id for screenshot in screenshots if screenshot.hash or screenshot.unique_id}
            existing_hashes = set(self.screenshot_items.keys())

            # Find screenshots to add and remove
            to_add = current_hashes - existing_hashes
            to_remove = existing_hashes - current_hashes

            # Remove screenshots that are no longer present
            for hash_to_remove in to_remove:
                if hash_to_remove in self.screenshot_items:
                    item = self.screenshot_items[hash_to_remove]
                    self.screenshots_layout.removeWidget(item)
                    item.deleteLater()
                    del self.screenshot_items[hash_to_remove]

            # If we have new screenshots to add, reorganize the entire grid to maintain newest-first order
            if to_add:
                # Get all screenshots with their timestamps for sorting
                all_current_screenshots = []
                for screenshot in screenshots:
                    screenshot_hash = screenshot.hash or screenshot.unique_id
                    if screenshot_hash:
                        all_current_screenshots.append(screenshot)

                # Sort by timestamp, newest first
                all_current_screenshots.sort(key=lambda s: s.timestamp, reverse=True)

                # Clear the layout but keep the items
                for hash_id, item in self.screenshot_items.items():
                    self.screenshots_layout.removeWidget(item)

                # Create new screenshot items for those that need to be added
                for screenshot in all_current_screenshots:
                    screenshot_hash = screenshot.hash or screenshot.unique_id
                    if screenshot_hash and screenshot_hash in to_add:
                        item = ScreenshotItem(
                            screenshot_hash,
                            screenshot.filename,
                            screenshot.timestamp
                        )
                        item.clicked.connect(self._on_screenshot_clicked)

                        if self._screenshot_item_style_manager:
                            item.set_style_manager(self._screenshot_item_style_manager)

                        self.screenshot_items[screenshot_hash] = item

                        # Queue thumbnail loading
                        if self.thumbnail_loader:
                            await self.thumbnail_loader.load_thumbnail(
                                screenshot_hash,
                                screenshot.full_path
                            )

                # Re-add all items to layout in correct order (newest first)
                row, col = 0, 0
                for screenshot in all_current_screenshots:
                    screenshot_hash = screenshot.hash or screenshot.unique_id
                    if screenshot_hash and screenshot_hash in self.screenshot_items:
                        item = self.screenshot_items[screenshot_hash]
                        self.screenshots_layout.addWidget(item, row, col)

                        col += 1
                        if col >= GRID_COLS_PER_ROW:
                            col = 0
                            row += 1

            logger.info(f"Refreshed screenshots: {len(to_add)} added, {len(to_remove)} removed")

        except Exception as e:
            logger.error(f"Failed to refresh screenshots: {e}")

    async def force_directory_refresh(self, limit: int = 50):
        """Force a fresh directory scan and full refresh of screenshots."""
        try:
            logger.info("Forcing complete directory refresh")
            await self.refresh_screenshots(limit=limit, force_scan=True)
        except Exception as e:
            logger.error(f"Failed to force directory refresh: {e}")

    def _find_next_grid_position(self) -> tuple[int, int]:
        """Find the next available grid position."""
        # Simple strategy: find the maximum row and add to it
        max_row = 0
        items_in_last_row = 0

        for i in range(self.screenshots_layout.count()):
            item = self.screenshots_layout.itemAt(i)
            if item:
                # getItemPosition returns (row, col, rowspan, colspan)
                position = self.screenshots_layout.getItemPosition(i)
                if position and len(position) >= 2:
                    row = position[0]
                    if row is not None and row > max_row:
                        max_row = row
                        items_in_last_row = 1
                    elif row is not None and row == max_row:
                        items_in_last_row += 1

        # Calculate next position
        if items_in_last_row < GRID_COLS_PER_ROW:
            return max_row, items_in_last_row
        else:
            return max_row + 1, 0

    def _clear_screenshot_items(self):
        """Clear all screenshot items."""
        for item in self.screenshot_items.values():
            item.deleteLater()
        self.screenshot_items.clear()

    async def select_screenshot(self, screenshot_id: str):
        """Select a screenshot and update UI state."""
        for item in self.screenshot_items.values():
            item.set_selected(False)

        if screenshot_id in self.screenshot_items:
            self.screenshot_items[screenshot_id].set_selected(True)
            self._selected_screenshot_id = screenshot_id

            if self.selection_indicator:
                item = self.screenshot_items[screenshot_id]
                filename = item.filename
                truncated = self._truncate_filename_for_indicator(filename)
                self.selection_indicator.setText(truncated)
                self.selection_indicator.setProperty("selected", True)
                style = self.selection_indicator.style()
                if style:
                    style.polish(self.selection_indicator)

            self.screenshot_selected.emit(screenshot_id)
            logger.info(f"Screenshot selected: {screenshot_id}")
        else:
            self._selected_screenshot_id = None
            if self.selection_indicator:
                self.selection_indicator.setText("None selected")
                self.selection_indicator.setProperty("selected", False)
                style = self.selection_indicator.style()
                if style:
                    style.polish(self.selection_indicator)

    def _on_screenshot_clicked(self, screenshot_id: str):
        """Handle screenshot item clicks."""
        asyncio.create_task(self.select_screenshot(screenshot_id))

    def _on_thumbnail_loaded(self, screenshot_id: str, image_bytes: bytes, format_str: str):
        """Handle thumbnail loading completion."""
        if screenshot_id in self.screenshot_items:
            pixmap = QPixmap()
            pixmap.loadFromData(image_bytes, format_str.upper())
            self.screenshot_items[screenshot_id].set_thumbnail(pixmap)

    def _on_thumbnail_loading_started(self, screenshot_id: str):
        """Handle thumbnail loading start."""
        # The item already shows a loading placeholder, but we could add additional UI feedback here
        logger.debug(f"Started loading thumbnail for screenshot: {screenshot_id[:8]}")

    def _on_thumbnail_failed(self, screenshot_id: str, error_message: str):
        """Handle thumbnail loading failure."""
        logger.warning(f"Thumbnail loading failed for {screenshot_id}: {error_message}")
        # The item will keep showing the error placeholder created by ThumbnailLoader

    def _truncate_filename_for_indicator(self, filename: str, max_length: int = 36) -> str:
        """Truncate filename for the selection indicator."""
        if len(filename) <= max_length:
            return filename
        return filename[:max_length - 3] + "..."

    def get_selected_screenshot_id(self) -> Optional[str]:
        """Get the currently selected screenshot ID."""
        return self._selected_screenshot_id
