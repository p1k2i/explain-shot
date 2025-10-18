"""
Gallery Window Optimization Module.

This module provides optimized thumbnail loading and caching
for the gallery window to improve performance and user experience.
"""

import logging
from typing import Optional, Dict, Any, List, TYPE_CHECKING
from PyQt6.QtCore import QObject, pyqtSignal, QSize
from PyQt6.QtGui import QPixmap

if TYPE_CHECKING:
    from .gallery_window import GalleryWindow
    from src.models.thumbnail_manager import ThumbnailManager
    from src.models.screenshot_models import ScreenshotMetadata

logger = logging.getLogger(__name__)


class OptimizedThumbnailLoader(QObject):
    """
    Optimized thumbnail loader with LRU caching and background processing.

    Enhances the gallery thumbnail loading with intelligent caching,
    priority loading, and memory management.
    """

    thumbnail_ready = pyqtSignal(int, QPixmap)  # screenshot_id, pixmap
    loading_progress = pyqtSignal(int, int)     # loaded, total
    cache_stats_changed = pyqtSignal(dict)      # cache statistics

    def __init__(
        self,
        thumbnail_manager: 'ThumbnailManager',
        thumbnail_size: QSize = QSize(120, 120)
    ):
        """
        Initialize optimized thumbnail loader.

        Args:
            thumbnail_manager: Enhanced thumbnail manager
            thumbnail_size: Size for thumbnails
        """
        super().__init__()
        self.thumbnail_manager = thumbnail_manager
        self.thumbnail_size = thumbnail_size
        self.logger = logger

        # Loading state
        self._loading_queue: List[int] = []
        self._loaded_count = 0
        self._total_count = 0
        self._is_loading = False

    async def load_visible_thumbnails(
        self,
        screenshot_metadata: List['ScreenshotMetadata'],
        visible_start: int = 0,
        visible_count: int = 10
    ) -> None:
        """
        Load thumbnails for visible screenshots with priority.

        Args:
            screenshot_metadata: List of screenshot metadata
            visible_start: Index of first visible item
            visible_count: Number of visible items
        """
        try:
            # Calculate visible range
            visible_end = min(visible_start + visible_count, len(screenshot_metadata))

            # Prioritize visible items
            priority_items = screenshot_metadata[visible_start:visible_end]
            remaining_items = (
                screenshot_metadata[:visible_start] +
                screenshot_metadata[visible_end:]
            )

            # Load priority items first
            await self._load_thumbnails_batch(priority_items, high_priority=True)

            # Load remaining items
            await self._load_thumbnails_batch(remaining_items, high_priority=False)

        except Exception as e:
            self.logger.error(f"Error loading visible thumbnails: {e}")

    async def _load_thumbnails_batch(
        self,
        screenshots: List['ScreenshotMetadata'],
        high_priority: bool = False
    ) -> None:
        """
        Load a batch of thumbnails.

        Args:
            screenshots: Screenshots to load
            high_priority: Whether this is high priority loading
        """
        try:
            self._total_count = len(screenshots)
            self._loaded_count = 0
            self._is_loading = True

            for screenshot in screenshots:
                if screenshot.id is None:
                    self.logger.warning(f"Skipping thumbnail load for screenshot without ID: {screenshot.filename}")
                    self._loaded_count += 1
                    continue

                # Check if already cached
                thumbnail = await self.thumbnail_manager.get_thumbnail(
                    screenshot.id,
                    screenshot.full_path,
                    size=(self.thumbnail_size.width(), self.thumbnail_size.height())
                )

                if thumbnail:
                    # Convert PIL image to QPixmap
                    pixmap = self._pil_to_qpixmap(thumbnail)
                    if pixmap:
                        self.thumbnail_ready.emit(screenshot.id, pixmap)

                self._loaded_count += 1
                self.loading_progress.emit(self._loaded_count, self._total_count)

                # Emit cache stats periodically
                if self._loaded_count % 10 == 0:
                    stats = self.thumbnail_manager.get_cache_statistics()
                    self.cache_stats_changed.emit(stats)

            self._is_loading = False

        except Exception as e:
            self.logger.error(f"Error in thumbnail batch loading: {e}")
            self._is_loading = False

    def _pil_to_qpixmap(self, pil_image) -> Optional[QPixmap]:
        """
        Convert PIL image to QPixmap.

        Args:
            pil_image: PIL Image object

        Returns:
            QPixmap or None if conversion failed
        """
        try:
            # Try to import ImageQt for conversion
            try:
                from PIL import ImageQt
                qimage = ImageQt.ImageQt(pil_image)
                return QPixmap.fromImage(qimage)
            except ImportError:
                # Fallback: save to bytes and load
                import io
                buffer = io.BytesIO()
                pil_image.save(buffer, format='PNG')
                buffer.seek(0)
                pixmap = QPixmap()
                pixmap.loadFromData(buffer.getvalue())
                return pixmap

        except Exception as e:
            self.logger.error(f"Error converting PIL image to QPixmap: {e}")
            return None

    async def preload_adjacent_thumbnails(
        self,
        current_index: int,
        screenshot_metadata: List['ScreenshotMetadata'],
        preload_count: int = 5
    ) -> None:
        """
        Preload thumbnails adjacent to current selection.

        Args:
            current_index: Index of currently selected item
            screenshot_metadata: List of all screenshot metadata
            preload_count: Number of items to preload in each direction
        """
        try:
            # Calculate preload range
            start_index = max(0, current_index - preload_count)
            end_index = min(len(screenshot_metadata), current_index + preload_count + 1)

            preload_items = screenshot_metadata[start_index:end_index]

            # Preload in background
            await self._load_thumbnails_batch(preload_items, high_priority=False)

        except Exception as e:
            self.logger.error(f"Error preloading adjacent thumbnails: {e}")

    async def clear_cache(self) -> None:
        """Clear thumbnail cache."""
        try:
            await self.thumbnail_manager.invalidate_cache()
            self.logger.info("Thumbnail cache cleared")

        except Exception as e:
            self.logger.error(f"Error clearing cache: {e}")

    def is_loading(self) -> bool:
        """Check if currently loading thumbnails."""
        return self._is_loading

    async def get_cache_statistics(self) -> Dict[str, Any]:
        """Get cache statistics."""
        try:
            return self.thumbnail_manager.get_cache_statistics()
        except Exception as e:
            self.logger.error(f"Error getting cache stats: {e}")
            return {}


class GalleryOptimizer:
    """
    Gallery window optimization coordinator.

    Provides optimized data loading, caching, and performance
    monitoring for the gallery window.
    """

    def __init__(
        self,
        gallery_window: 'GalleryWindow',
        thumbnail_manager: Optional['ThumbnailManager'] = None
    ):
        """
        Initialize gallery optimizer.

        Args:
            gallery_window: Gallery window to optimize
            thumbnail_manager: Optional thumbnail manager
        """
        self.gallery_window = gallery_window
        self.thumbnail_manager = thumbnail_manager
        self.logger = logger

        # Optimization components
        self.thumbnail_loader: Optional[OptimizedThumbnailLoader] = None

        # State tracking
        self._last_visible_range = (0, 0)
        self._optimization_enabled = False

    async def initialize(self) -> bool:
        """
        Initialize gallery optimization.

        Returns:
            True if initialization successful
        """
        try:
            if not self.thumbnail_manager:
                self.logger.warning("No thumbnail manager provided, optimization limited")
                return False

            # Initialize thumbnail loader
            self.thumbnail_loader = OptimizedThumbnailLoader(
                self.thumbnail_manager,
                thumbnail_size=QSize(120, 120)
            )

            # Connect signals
            if self.thumbnail_loader:
                self.thumbnail_loader.thumbnail_ready.connect(
                    self._on_thumbnail_ready
                )
                self.thumbnail_loader.loading_progress.connect(
                    self._on_loading_progress
                )
                self.thumbnail_loader.cache_stats_changed.connect(
                    self._on_cache_stats_changed
                )

            self._optimization_enabled = True
            self.logger.info("Gallery optimization initialized")
            return True

        except Exception as e:
            self.logger.error(f"Error initializing gallery optimization: {e}")
            return False

    def _on_thumbnail_ready(self, screenshot_id: int, pixmap: QPixmap) -> None:
        """Handle thumbnail ready signal."""
        try:
            # Update gallery window with loaded thumbnail
            # This would integrate with the gallery's thumbnail display
            self.logger.debug(f"Thumbnail ready for screenshot {screenshot_id}")

        except Exception as e:
            self.logger.error(f"Error handling thumbnail ready: {e}")

    def _on_loading_progress(self, loaded: int, total: int) -> None:
        """Handle loading progress updates."""
        try:
            progress_percent = (loaded / total * 100) if total > 0 else 0
            self.logger.debug(f"Thumbnail loading progress: {progress_percent:.1f}%")

        except Exception as e:
            self.logger.error(f"Error handling loading progress: {e}")

    def _on_cache_stats_changed(self, stats: Dict[str, Any]) -> None:
        """Handle cache statistics updates."""
        try:
            cache_hit_rate = stats.get('hit_rate', 0.0)
            memory_usage = stats.get('memory_usage_mb', 0.0)

            self.logger.debug(
                f"Cache stats - Hit rate: {cache_hit_rate:.1f}%, "
                f"Memory: {memory_usage:.1f}MB"
            )

        except Exception as e:
            self.logger.error(f"Error handling cache stats: {e}")

    async def optimize_viewport_loading(
        self,
        screenshot_metadata: List['ScreenshotMetadata'],
        visible_start: int,
        visible_count: int
    ) -> None:
        """
        Optimize loading for current viewport.

        Args:
            screenshot_metadata: All screenshot metadata
            visible_start: Index of first visible item
            visible_count: Number of visible items
        """
        try:
            if not self._optimization_enabled or not self.thumbnail_loader:
                return

            # Check if viewport has changed significantly
            current_range = (visible_start, visible_start + visible_count)
            if self._range_changed(current_range):
                self._last_visible_range = current_range

                # Load visible thumbnails with priority
                await self.thumbnail_loader.load_visible_thumbnails(
                    screenshot_metadata,
                    visible_start,
                    visible_count
                )

        except Exception as e:
            self.logger.error(f"Error optimizing viewport loading: {e}")

    def _range_changed(self, new_range: tuple) -> bool:
        """Check if visible range has changed significantly."""
        old_start, old_end = self._last_visible_range
        new_start, new_end = new_range

        # Consider changed if more than 50% of range is different
        overlap_start = max(old_start, new_start)
        overlap_end = min(old_end, new_end)
        overlap_size = max(0, overlap_end - overlap_start)

        old_size = old_end - old_start
        overlap_ratio = overlap_size / old_size if old_size > 0 else 0

        return overlap_ratio < 0.5

    async def preload_for_selection(
        self,
        selected_index: int,
        screenshot_metadata: List['ScreenshotMetadata']
    ) -> None:
        """
        Preload thumbnails around selected item.

        Args:
            selected_index: Index of selected item
            screenshot_metadata: All screenshot metadata
        """
        try:
            if not self._optimization_enabled or not self.thumbnail_loader:
                return

            await self.thumbnail_loader.preload_adjacent_thumbnails(
                selected_index,
                screenshot_metadata,
                preload_count=5
            )

        except Exception as e:
            self.logger.error(f"Error preloading for selection: {e}")

    async def get_optimization_stats(self) -> Dict[str, Any]:
        """
        Get optimization statistics.

        Returns:
            Dictionary with optimization statistics
        """
        try:
            stats = {
                'enabled': self._optimization_enabled,
                'thumbnail_cache': {},
                'loading_state': {
                    'is_loading': False
                }
            }

            if self.thumbnail_loader:
                stats['thumbnail_cache'] = await self.thumbnail_loader.get_cache_statistics()
                stats['loading_state']['is_loading'] = self.thumbnail_loader.is_loading()

            return stats

        except Exception as e:
            self.logger.error(f"Error getting optimization stats: {e}")
            return {'enabled': False, 'error': str(e)}

    async def cleanup(self) -> None:
        """Cleanup optimization resources."""
        try:
            if self.thumbnail_loader:
                await self.thumbnail_loader.clear_cache()

            self._optimization_enabled = False
            self.logger.info("Gallery optimization cleanup completed")

        except Exception as e:
            self.logger.error(f"Error during optimization cleanup: {e}")


def create_gallery_optimizer(
    gallery_window: 'GalleryWindow',
    thumbnail_manager: Optional['ThumbnailManager'] = None
) -> GalleryOptimizer:
    """
    Create gallery optimizer for a gallery window.

    Args:
        gallery_window: Gallery window to optimize
        thumbnail_manager: Optional thumbnail manager

    Returns:
        GalleryOptimizer instance
    """
    return GalleryOptimizer(gallery_window, thumbnail_manager)
