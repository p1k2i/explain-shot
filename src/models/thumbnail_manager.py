"""
Enhanced Thumbnail Manager for Optimized Image Loading

This module provides LRU cache-based thumbnail management with background processing,
virtual scrolling support, and memory-efficient operations.
"""

import asyncio
import logging
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Set, Any
from pathlib import Path
from io import BytesIO

logger = logging.getLogger(__name__)

# Check for dependencies
PIL_AVAILABLE = False
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    pass


@dataclass
class ThumbnailCacheEntry:
    """Cache entry for storing thumbnail data with metadata."""
    image_bytes: bytes
    format: str
    size_bytes: int
    created_at: datetime
    last_accessed: datetime
    access_count: int = 0


@dataclass
class CacheStatistics:
    """Statistics for cache performance monitoring."""
    total_entries: int = 0
    memory_usage_bytes: int = 0
    hit_count: int = 0
    miss_count: int = 0
    eviction_count: int = 0
    generation_time_total: float = 0.0
    generation_count: int = 0

    @property
    def hit_ratio(self) -> float:
        """Calculate cache hit ratio."""
        total = self.hit_count + self.miss_count
        return self.hit_count / total if total > 0 else 0.0

    @property
    def average_generation_time(self) -> float:
        """Calculate average thumbnail generation time."""
        return self.generation_time_total / self.generation_count if self.generation_count > 0 else 0.0


@dataclass
class ViewportInfo:
    """Information about current viewport for virtual scrolling."""
    start_index: int
    end_index: int
    total_items: int
    visible_count: int


class ThumbnailManager:
    """
    Enhanced thumbnail manager with LRU caching and optimization.

    Provides:
    - LRU cache with configurable memory limits
    - Background thumbnail generation using ThreadPoolExecutor
    - Virtual scrolling support with viewport-aware loading
    - Performance monitoring and statistics
    - Prefetching for smooth scrolling experience
    """

    def __init__(self, event_bus, settings_manager=None, cache_size: int = 50, max_memory_mb: int = 100):
        """
        Initialize the enhanced thumbnail manager.

        Args:
            event_bus: EventBus instance for communication
            settings_manager: Optional settings manager for configuration
            cache_size: Maximum number of thumbnails to cache
            max_memory_mb: Maximum memory usage in MB
        """
        self.event_bus = event_bus
        self.settings_manager = settings_manager

        # Cache configuration
        self._cache_size_limit = cache_size
        self._memory_limit_bytes = max_memory_mb * 1024 * 1024
        self._memory_soft_limit_bytes = int(self._memory_limit_bytes * 0.8)

        # LRU cache implementation
        self._cache: OrderedDict[int, ThumbnailCacheEntry] = OrderedDict()
        self._cache_lock = asyncio.Lock()

        # Statistics tracking
        self._stats = CacheStatistics()

        # Background processing
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="thumbnail_gen")
        self._prefetch_queue: Set[int] = set()
        self._loading_in_progress: Set[int] = set()

        # Virtual scrolling
        self._current_viewport: Optional[ViewportInfo] = None
        self._prefetch_count = 10

        # Performance monitoring
        self._last_stats_emit = datetime.now()
        self._stats_emit_interval = timedelta(seconds=5)

        logger.info(f"ThumbnailManager initialized - Cache: {cache_size}, Memory: {max_memory_mb}MB")

    async def initialize(self) -> None:
        """Initialize the thumbnail manager."""
        try:
            # Load configuration from settings if available
            if self.settings_manager:
                await self._load_settings()

            # Subscribe to events
            if self.event_bus:
                self.event_bus.subscribe("gallery.viewport_changed", self._handle_viewport_changed)
                self.event_bus.subscribe("settings.changed", self._handle_settings_changed)

            logger.debug("ThumbnailManager initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize ThumbnailManager: {e}")
            raise

    async def _load_settings(self) -> None:
        """Load configuration from settings manager."""
        try:
            if not self.settings_manager:
                return

            settings = await self.settings_manager.load_settings()

            # Update cache configuration if available
            if hasattr(settings, 'optimization'):
                opt_config = settings.optimization
                self._cache_size_limit = getattr(opt_config, 'thumbnail_cache_size', self._cache_size_limit)
                max_memory_mb = getattr(opt_config, 'thumbnail_memory_limit_mb', 100)
                self._memory_limit_bytes = max_memory_mb * 1024 * 1024
                self._memory_soft_limit_bytes = int(self._memory_limit_bytes * 0.8)
                self._prefetch_count = getattr(opt_config, 'thumbnail_prefetch_count', 10)

            logger.debug(f"Loaded thumbnail settings - Cache: {self._cache_size_limit}, "
                        f"Memory: {self._memory_limit_bytes // (1024*1024)}MB")

        except Exception as e:
            logger.warning(f"Failed to load thumbnail settings: {e}")

    async def load_visible_thumbnails(self, screenshot_ids: List[int],
                                    screenshot_paths: Dict[int, str],
                                    viewport_range: Tuple[int, int]) -> None:
        """
        Load thumbnails for visible screenshots with viewport awareness.

        Args:
            screenshot_ids: List of screenshot IDs to load
            screenshot_paths: Mapping of screenshot ID to file path
            viewport_range: Tuple of (start_index, end_index) for viewport
        """
        try:
            start_index, end_index = viewport_range
            visible_ids = screenshot_ids[start_index:end_index + 1]

            # Update viewport info
            self._current_viewport = ViewportInfo(
                start_index=start_index,
                end_index=end_index,
                total_items=len(screenshot_ids),
                visible_count=len(visible_ids)
            )

            # Process visible thumbnails first
            ready_thumbnails = []
            missing_thumbnails = []

            async with self._cache_lock:
                for screenshot_id in visible_ids:
                    if screenshot_id in self._cache:
                        # Cache hit
                        entry = self._cache[screenshot_id]
                        entry.last_accessed = datetime.now()
                        entry.access_count += 1

                        # Move to end (most recently used)
                        self._cache.move_to_end(screenshot_id)

                        ready_thumbnails.append((screenshot_id, entry.image_bytes, entry.format))
                        self._stats.hit_count += 1

                    else:
                        # Cache miss
                        if screenshot_id not in self._loading_in_progress:
                            missing_thumbnails.append(screenshot_id)
                        self._stats.miss_count += 1

            # Queue missing thumbnails for generation
            for screenshot_id in missing_thumbnails:
                if screenshot_id in screenshot_paths:
                    self._loading_in_progress.add(screenshot_id)
                    asyncio.create_task(self._generate_thumbnail_async(
                        screenshot_id,
                        screenshot_paths[screenshot_id]
                    ))

            # Schedule prefetching for smooth scrolling
            await self._schedule_prefetch(screenshot_ids, screenshot_paths, viewport_range)

            # Update statistics
            await self._update_statistics()

        except Exception as e:
            logger.error(f"Failed to load visible thumbnails: {e}")

    async def _generate_thumbnail_async(self, screenshot_id: int, file_path: str):
        """Generate thumbnail asynchronously using thread pool."""
        try:
            start_time = time.time()

            # Run thumbnail generation in thread pool
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                self._executor,
                self._generate_thumbnail_sync,
                file_path,
                None  # Use default size
            )

            generation_time = time.time() - start_time

            if result:
                image_bytes, format_str = result
                await self._store_thumbnail(screenshot_id, image_bytes, format_str, generation_time)

            else:
                logger.warning(f"Failed to generate thumbnail for {screenshot_id}")

        except Exception as e:
            logger.error(f"Failed to generate thumbnail for {screenshot_id}: {e}")
        finally:
            self._loading_in_progress.discard(screenshot_id)

    def _generate_thumbnail_sync(self, file_path: str, size: Optional[Tuple[int, int]] = None) -> Optional[Tuple[bytes, str]]:
        """Generate thumbnail synchronously (runs in thread pool)."""
        try:
            if not PIL_AVAILABLE:
                logger.warning("PIL not available for thumbnail generation")
                return None

            if not Path(file_path).exists():
                logger.warning(f"File not found: {file_path}")
                return None

            with Image.open(file_path) as img:  # type: ignore
                # Convert to RGB if necessary
                if img.mode != 'RGB':
                    img = img.convert('RGB')

                # Create thumbnail with high-quality resampling
                thumbnail_size = size if size else (120, 120)
                img.thumbnail(thumbnail_size, Image.Resampling.LANCZOS)  # type: ignore

                # Save as JPEG with optimized quality
                buffer = BytesIO()
                img.save(buffer, format='JPEG', quality=80, optimize=True)

                return buffer.getvalue(), 'JPEG'

        except Exception as e:
            logger.warning(f"PIL thumbnail generation failed for {file_path}: {e}")
            return None

    async def _store_thumbnail(self, screenshot_id: int, image_bytes: bytes,
                             format_str: str, generation_time: float):
        """Store thumbnail in cache with proper memory management."""
        try:
            async with self._cache_lock:
                # Create cache entry
                entry = ThumbnailCacheEntry(
                    image_bytes=image_bytes,
                    format=format_str,
                    size_bytes=len(image_bytes),
                    created_at=datetime.now(),
                    last_accessed=datetime.now(),
                    access_count=1
                )

                # Add to cache
                self._cache[screenshot_id] = entry

                # Update statistics
                self._stats.generation_time_total += generation_time
                self._stats.generation_count += 1

                # Check memory usage and evict if necessary
                await self._enforce_memory_limits()

        except Exception as e:
            logger.error(f"Failed to store thumbnail: {e}")

    async def _schedule_prefetch(self, screenshot_ids: List[int],
                               screenshot_paths: Dict[int, str],
                               viewport_range: Tuple[int, int]) -> None:
        """Schedule prefetching for thumbnails outside viewport."""
        try:
            start_index, end_index = viewport_range

            # Calculate prefetch range
            prefetch_start = max(0, start_index - self._prefetch_count // 2)
            prefetch_end = min(len(screenshot_ids), end_index + self._prefetch_count // 2)

            # Identify prefetch candidates
            prefetch_candidates = []
            for i in range(prefetch_start, prefetch_end):
                if i < start_index or i > end_index:  # Outside visible range
                    screenshot_id = screenshot_ids[i]
                    if (screenshot_id not in self._cache and
                        screenshot_id not in self._loading_in_progress and
                        screenshot_id not in self._prefetch_queue):
                        prefetch_candidates.append(screenshot_id)

            # Limit prefetch queue size
            max_prefetch = min(len(prefetch_candidates), self._prefetch_count)
            prefetch_candidates = prefetch_candidates[:max_prefetch]

            # Queue prefetch items with delay
            for screenshot_id in prefetch_candidates:
                if screenshot_id in screenshot_paths:
                    self._prefetch_queue.add(screenshot_id)
                    asyncio.create_task(self._delayed_prefetch(
                        screenshot_id,
                        screenshot_paths[screenshot_id],
                        delay=0.1
                    ))

        except Exception as e:
            logger.error(f"Failed to schedule prefetch: {e}")

    async def _delayed_prefetch(self, screenshot_id: int, file_path: str, delay: float = 0.1):
        """Execute prefetch with delay to avoid interfering with visible items."""
        try:
            await asyncio.sleep(delay)

            # Check if still needed
            if (screenshot_id not in self._cache and
                screenshot_id not in self._loading_in_progress):

                await self._generate_thumbnail_async(screenshot_id, file_path)

            # Remove from prefetch queue
            self._prefetch_queue.discard(screenshot_id)

        except Exception as e:
            logger.error(f"Failed to execute delayed prefetch: {e}")

    async def _enforce_memory_limits(self):
        """Enforce memory limits by evicting old entries."""
        try:
            current_memory = self._calculate_memory_usage()

            # Check if we exceed soft limit
            if current_memory > self._memory_soft_limit_bytes:
                logger.debug(f"Memory threshold reached: {current_memory} bytes")

                # Evict oldest entries until under soft limit
                while (len(self._cache) > 0 and
                       self._calculate_memory_usage() > self._memory_soft_limit_bytes):

                    # Remove oldest entry
                    oldest_id, oldest_entry = self._cache.popitem(last=False)
                    self._stats.eviction_count += 1

                    logger.debug(f"Evicted thumbnail {oldest_id} to free memory")

            # Also enforce size limit
            while len(self._cache) > self._cache_size_limit:
                oldest_id, oldest_entry = self._cache.popitem(last=False)
                self._stats.eviction_count += 1

        except Exception as e:
            logger.error(f"Failed to enforce memory limits: {e}")

    def _calculate_memory_usage(self) -> int:
        """Calculate current memory usage in bytes."""
        return sum(entry.size_bytes for entry in self._cache.values())

    async def get_cached_thumbnail(self, screenshot_id: int) -> Optional[Tuple[bytes, str]]:
        """
        Get cached thumbnail if available.

        Returns:
            Tuple of (image_bytes, format) or None if not cached
        """
        try:
            async with self._cache_lock:
                if screenshot_id in self._cache:
                    entry = self._cache[screenshot_id]
                    entry.last_accessed = datetime.now()
                    entry.access_count += 1

                    # Move to end (most recently used)
                    self._cache.move_to_end(screenshot_id)

                    return (entry.image_bytes, entry.format)

            return None

        except Exception as e:
            logger.error(f"Failed to get cached thumbnail: {e}")
            return None

    async def get_thumbnail(self, screenshot_id: int, file_path: str, size: Optional[Tuple[int, int]] = None) -> Optional[Any]:
        """
        Get thumbnail for a screenshot, either from cache or by generating it.

        Args:
            screenshot_id: ID of the screenshot
            file_path: Path to the screenshot file
            size: Optional size tuple (width, height) for the thumbnail

        Returns:
            PIL Image object or None if failed
        """
        try:
            # First check cache
            cached = await self.get_cached_thumbnail(screenshot_id)
            if cached and PIL_AVAILABLE:
                image_bytes, format_str = cached
                # Convert bytes back to PIL Image
                from io import BytesIO
                buffer = BytesIO(image_bytes)
                pil_image = Image.open(buffer)  # type: ignore
                return pil_image

            # Not in cache, generate it
            if not PIL_AVAILABLE:
                logger.warning("PIL not available for thumbnail generation")
                return None

            if not Path(file_path).exists():
                logger.warning(f"File not found: {file_path}")
                return None

            # Generate thumbnail synchronously
            result = self._generate_thumbnail_sync(file_path, size)
            if result:
                image_bytes, format_str = result

                # Store in cache
                await self._store_thumbnail(screenshot_id, image_bytes, format_str, 0.0)

                # Convert to PIL Image for return
                from io import BytesIO
                buffer = BytesIO(image_bytes)
                pil_image = Image.open(buffer)  # type: ignore
                return pil_image

            return None

        except Exception as e:
            logger.error(f"Failed to get thumbnail for {screenshot_id}: {e}")
            return None

    async def invalidate_cache(self, screenshot_id: Optional[int] = None) -> None:
        """
        Invalidate cached thumbnails.

        Args:
            screenshot_id: Specific ID to invalidate, or None for all
        """
        try:
            async with self._cache_lock:
                if screenshot_id is not None:
                    if screenshot_id in self._cache:
                        del self._cache[screenshot_id]
                        logger.debug(f"Invalidated thumbnail cache for {screenshot_id}")
                else:
                    self._cache.clear()
                    logger.info("Invalidated entire thumbnail cache")

            await self._update_statistics()

        except Exception as e:
            logger.error(f"Failed to invalidate cache: {e}")

    def get_cache_statistics(self) -> Dict[str, Any]:
        """Get current cache statistics."""
        memory_usage = self._calculate_memory_usage()

        return {
            'total_entries': len(self._cache),
            'memory_usage_bytes': memory_usage,
            'memory_usage_mb': round(memory_usage / (1024 * 1024), 2),
            'memory_limit_mb': round(self._memory_limit_bytes / (1024 * 1024), 2),
            'hit_count': self._stats.hit_count,
            'miss_count': self._stats.miss_count,
            'hit_ratio': round(self._stats.hit_ratio * 100, 1),
            'eviction_count': self._stats.eviction_count,
            'average_generation_time_ms': round(self._stats.average_generation_time * 1000, 1),
            'loading_in_progress': len(self._loading_in_progress),
            'prefetch_queue_size': len(self._prefetch_queue)
        }

    async def _update_statistics(self):
        """Update and emit statistics if interval has passed."""
        try:
            now = datetime.now()
            if now - self._last_stats_emit >= self._stats_emit_interval:
                stats = self.get_cache_statistics()

                self._last_stats_emit = now

                # Emit performance event if available
                if self.event_bus:
                    await self.event_bus.emit(
                        "optimization.thumbnail_stats_updated",
                        stats
                    )

        except Exception as e:
            logger.error(f"Failed to update statistics: {e}")

    async def _handle_viewport_changed(self, event_data):
        """Handle viewport change events from gallery."""
        try:
            data = event_data.get('data', {})
            start_index = data.get('start_index', 0)
            end_index = data.get('end_index', 0)
            screenshot_ids = data.get('screenshot_ids', [])
            screenshot_paths = data.get('screenshot_paths', {})

            if screenshot_ids and screenshot_paths:
                await self.load_visible_thumbnails(
                    screenshot_ids,
                    screenshot_paths,
                    (start_index, end_index)
                )

        except Exception as e:
            logger.error(f"Failed to handle viewport change: {e}")

    async def _handle_settings_changed(self, event_data):
        """Handle settings changes."""
        try:
            data = event_data.get('data', {})
            key = data.get('key', '')

            if key.startswith('optimization.thumbnail'):
                await self._load_settings()
                logger.info("Reloaded thumbnail settings")

        except Exception as e:
            logger.error(f"Failed to handle settings change: {e}")

    async def shutdown(self) -> None:
        """Shutdown the thumbnail manager."""
        try:
            logger.debug("Shutting down ThumbnailManager")

            # Shutdown executor
            self._executor.shutdown(wait=True)

            # Clear cache
            async with self._cache_lock:
                self._cache.clear()

            # Clear queues
            self._loading_in_progress.clear()
            self._prefetch_queue.clear()

            logger.debug("ThumbnailManager shutdown complete")

        except Exception as e:
            logger.error(f"Error during ThumbnailManager shutdown: {e}")
