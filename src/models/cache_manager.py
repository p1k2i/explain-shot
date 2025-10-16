"""
Enhanced Cache Manager for AI Response Caching

This module provides SQLite-backed response caching with prompt hashing,
memory-efficient session management, and cache optimization for AI interactions.
"""

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Optional, Any

logger = logging.getLogger(__name__)


@dataclass
class CachedResponse:
    """Represents a cached AI response."""
    id: Optional[int]
    screenshot_id: int
    prompt_hash: str
    prompt_text: str
    response_content: str
    model_name: str
    processing_time: float
    created_at: datetime
    last_accessed: datetime
    access_count: int
    expires_at: Optional[datetime] = None


@dataclass
class CacheConfig:
    """Configuration for cache management."""
    max_entries: int = 1000
    max_memory_mb: int = 100
    ttl_hours: int = 168  # 7 days
    cleanup_interval_hours: int = 24
    enable_compression: bool = True
    hash_algorithm: str = "sha256"
    session_cache_size: int = 50


@dataclass
class CacheStatistics:
    """Cache performance statistics."""
    total_entries: int = 0
    memory_usage_bytes: int = 0
    hit_count: int = 0
    miss_count: int = 0
    expired_count: int = 0
    evicted_count: int = 0
    compression_ratio: float = 0.0
    average_response_size: float = 0.0

    @property
    def hit_ratio(self) -> float:
        """Calculate cache hit ratio."""
        total = self.hit_count + self.miss_count
        return self.hit_count / total if total > 0 else 0.0


class CacheManager:
    """
    Enhanced cache manager for AI responses.

    Provides:
    - SQLite-backed persistent caching
    - Prompt hashing for deduplication
    - Memory-efficient session management
    - TTL-based expiration
    - Automatic cleanup and optimization
    - Compression for large responses
    - Performance monitoring
    """

    def __init__(self, database_manager, settings_manager, event_bus):
        """
        Initialize the cache manager.

        Args:
            database_manager: DatabaseManager for persistence
            settings_manager: SettingsManager for configuration
            event_bus: EventBus for communication
        """
        self.database_manager = database_manager
        self.settings_manager = settings_manager
        self.event_bus = event_bus

        # Configuration
        self._config = CacheConfig()
        self._initialized = False

        # Session cache for frequently accessed items
        self._session_cache: Dict[str, CachedResponse] = {}
        self._session_cache_lock = asyncio.Lock()

        # Statistics
        self._stats = CacheStatistics()

        # Background tasks
        self._cleanup_task: Optional[asyncio.Task] = None
        self._optimization_task: Optional[asyncio.Task] = None

        # Performance tracking
        self._last_stats_update = datetime.now()
        self._stats_update_interval = timedelta(minutes=5)

        logger.info("CacheManager initialized")

    async def initialize(self) -> None:
        """Initialize the cache manager."""
        try:
            # Load configuration
            await self._load_settings()

            # Initialize database schema
            await self._initialize_schema()

            # Load initial statistics
            await self._update_statistics()

            # Subscribe to events
            if self.event_bus:
                self.event_bus.subscribe("settings.changed", self._handle_settings_changed)
                self.event_bus.subscribe("ollama.response_received", self._handle_ollama_response)
                self.event_bus.subscribe("cache.optimization_requested", self._handle_optimization_requested)

            # Start background tasks
            await self._start_background_tasks()

            self._initialized = True
            logger.info("CacheManager initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize CacheManager: {e}")
            raise

    async def _load_settings(self) -> None:
        """Load cache configuration from settings."""
        try:
            if not self.settings_manager:
                return

            settings = await self.settings_manager.load_settings()

            # Load cache configuration if available
            if hasattr(settings, 'cache'):
                cache_config = settings.cache
                self._config.max_entries = getattr(cache_config, 'max_entries', 1000)
                self._config.max_memory_mb = getattr(cache_config, 'max_memory_mb', 100)
                self._config.ttl_hours = getattr(cache_config, 'ttl_hours', 168)
                self._config.cleanup_interval_hours = getattr(cache_config, 'cleanup_interval_hours', 24)
                self._config.enable_compression = getattr(cache_config, 'enable_compression', True)
                self._config.session_cache_size = getattr(cache_config, 'session_cache_size', 50)

            logger.debug(f"Loaded cache settings - Max entries: {self._config.max_entries}, "
                        f"TTL: {self._config.ttl_hours}h")

        except Exception as e:
            logger.warning(f"Failed to load cache settings: {e}")

    async def _initialize_schema(self) -> None:
        """Initialize cache database schema."""
        try:
            # Create cached_responses table if it doesn't exist
            create_table_query = """
            CREATE TABLE IF NOT EXISTS cached_responses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                screenshot_id INTEGER NOT NULL,
                prompt_hash TEXT NOT NULL,
                prompt_text TEXT NOT NULL,
                response_content TEXT NOT NULL,
                model_name TEXT NOT NULL,
                processing_time REAL NOT NULL,
                created_at TEXT NOT NULL,
                last_accessed TEXT NOT NULL,
                access_count INTEGER DEFAULT 0,
                expires_at TEXT,
                UNIQUE(screenshot_id, prompt_hash)
            )
            """

            # Create indexes for performance
            create_indexes_queries = [
                "CREATE INDEX IF NOT EXISTS idx_cached_responses_lookup ON cached_responses (screenshot_id, prompt_hash)",
                "CREATE INDEX IF NOT EXISTS idx_cached_responses_expires ON cached_responses (expires_at)",
                "CREATE INDEX IF NOT EXISTS idx_cached_responses_access ON cached_responses (last_accessed DESC)",
                "CREATE INDEX IF NOT EXISTS idx_cached_responses_created ON cached_responses (created_at DESC)"
            ]

            # Execute schema creation
            async with self.database_manager._get_connection() as conn:
                await conn.execute(create_table_query)

                for index_query in create_indexes_queries:
                    await conn.execute(index_query)

                await conn.commit()

            logger.debug("Cache database schema initialized")

        except Exception as e:
            logger.error(f"Failed to initialize cache schema: {e}")
            raise

    def _generate_prompt_hash(self, prompt: str, screenshot_id: int, model_name: str) -> str:
        """Generate hash for prompt deduplication."""
        try:
            # Include screenshot_id and model in hash for specificity
            hash_input = f"{screenshot_id}:{model_name}:{prompt}"

            if self._config.hash_algorithm == "sha256":
                return hashlib.sha256(hash_input.encode('utf-8')).hexdigest()
            elif self._config.hash_algorithm == "md5":
                return hashlib.md5(hash_input.encode('utf-8')).hexdigest()
            else:
                # Fallback to sha256
                return hashlib.sha256(hash_input.encode('utf-8')).hexdigest()

        except Exception as e:
            logger.error(f"Failed to generate prompt hash: {e}")
            return hashlib.sha256(f"{screenshot_id}:{prompt}".encode('utf-8')).hexdigest()

    async def get_cached_response(self, screenshot_id: int, prompt: str, model_name: str) -> Optional[CachedResponse]:
        """
        Get cached response if available and not expired.

        Args:
            screenshot_id: Screenshot ID
            prompt: User prompt
            model_name: AI model name

        Returns:
            CachedResponse if found and valid, None otherwise
        """
        try:
            prompt_hash = self._generate_prompt_hash(prompt, screenshot_id, model_name)
            cache_key = f"{screenshot_id}:{prompt_hash}"

            # Check session cache first
            async with self._session_cache_lock:
                if cache_key in self._session_cache:
                    cached = self._session_cache[cache_key]

                    # Check if expired
                    if cached.expires_at and datetime.now() > cached.expires_at:
                        del self._session_cache[cache_key]
                    else:
                        # Update access info
                        cached.last_accessed = datetime.now()
                        cached.access_count += 1
                        self._stats.hit_count += 1

                        # Update in database
                        asyncio.create_task(self._update_access_info(cached.id, cached.last_accessed, cached.access_count))

                        return cached

            # Check database cache
            cached = await self._get_cached_from_db(screenshot_id, prompt_hash)
            if cached:
                # Check if expired
                if cached.expires_at and datetime.now() > cached.expires_at:
                    # Mark as expired and remove
                    await self._remove_expired_entry(cached.id)
                    self._stats.expired_count += 1
                    self._stats.miss_count += 1
                    return None

                # Update access info
                cached.last_accessed = datetime.now()
                cached.access_count += 1
                await self._update_access_info(cached.id, cached.last_accessed, cached.access_count)

                # Add to session cache
                await self._add_to_session_cache(cache_key, cached)

                self._stats.hit_count += 1
                return cached

            self._stats.miss_count += 1
            return None

        except Exception as e:
            logger.error(f"Failed to get cached response: {e}")
            self._stats.miss_count += 1
            return None

    async def _get_cached_from_db(self, screenshot_id: int, prompt_hash: str) -> Optional[CachedResponse]:
        """Get cached response from database."""
        try:
            query = """
            SELECT id, screenshot_id, prompt_hash, prompt_text, response_content,
                   model_name, processing_time, created_at, last_accessed,
                   access_count, expires_at
            FROM cached_responses
            WHERE screenshot_id = ? AND prompt_hash = ?
            """

            async with self.database_manager._get_connection() as conn:
                cursor = await conn.execute(query, (screenshot_id, prompt_hash))
                row = await cursor.fetchone()

                if row:
                    return CachedResponse(
                        id=row['id'],
                        screenshot_id=row['screenshot_id'],
                        prompt_hash=row['prompt_hash'],
                        prompt_text=row['prompt_text'],
                        response_content=row['response_content'],
                        model_name=row['model_name'],
                        processing_time=row['processing_time'],
                        created_at=datetime.fromisoformat(row['created_at']),
                        last_accessed=datetime.fromisoformat(row['last_accessed']),
                        access_count=row['access_count'],
                        expires_at=datetime.fromisoformat(row['expires_at']) if row['expires_at'] else None
                    )

            return None

        except Exception as e:
            logger.error(f"Failed to get cached response from database: {e}")
            return None

    async def store_response(self, screenshot_id: int, prompt: str, response: Dict[str, Any]) -> None:
        """
        Store AI response in cache.

        Args:
            screenshot_id: Screenshot ID
            prompt: User prompt
            response: AI response data
        """
        try:
            model_name = response.get('model', 'unknown')
            prompt_hash = self._generate_prompt_hash(prompt, screenshot_id, model_name)

            # Create cache entry
            now = datetime.now()
            expires_at = now + timedelta(hours=self._config.ttl_hours) if self._config.ttl_hours > 0 else None

            cached_response = CachedResponse(
                id=None,
                screenshot_id=screenshot_id,
                prompt_hash=prompt_hash,
                prompt_text=prompt,
                response_content=response.get('content', ''),
                model_name=model_name,
                processing_time=response.get('processing_time', 0.0),
                created_at=now,
                last_accessed=now,
                access_count=1,
                expires_at=expires_at
            )

            # Store in database
            cached_id = await self._store_in_db(cached_response)
            if cached_id:
                cached_response.id = cached_id

                # Add to session cache
                cache_key = f"{screenshot_id}:{prompt_hash}"
                await self._add_to_session_cache(cache_key, cached_response)

                # Check if cleanup is needed
                await self._check_cleanup_needed()

                logger.debug(f"Stored response in cache for screenshot {screenshot_id}")

        except Exception as e:
            logger.error(f"Failed to store response in cache: {e}")

    async def _store_in_db(self, cached_response: CachedResponse) -> Optional[int]:
        """Store cached response in database."""
        try:
            query = """
            INSERT OR REPLACE INTO cached_responses
            (screenshot_id, prompt_hash, prompt_text, response_content, model_name,
             processing_time, created_at, last_accessed, access_count, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """

            values = (
                cached_response.screenshot_id,
                cached_response.prompt_hash,
                cached_response.prompt_text,
                cached_response.response_content,
                cached_response.model_name,
                cached_response.processing_time,
                cached_response.created_at.isoformat(),
                cached_response.last_accessed.isoformat(),
                cached_response.access_count,
                cached_response.expires_at.isoformat() if cached_response.expires_at else None
            )

            async with self.database_manager._get_connection() as conn:
                cursor = await conn.execute(query, values)
                await conn.commit()
                return cursor.lastrowid

        except Exception as e:
            logger.error(f"Failed to store cached response in database: {e}")
            return None

    async def _add_to_session_cache(self, cache_key: str, cached_response: CachedResponse) -> None:
        """Add entry to session cache with LRU eviction."""
        try:
            async with self._session_cache_lock:
                # Remove if already exists (for LRU update)
                if cache_key in self._session_cache:
                    del self._session_cache[cache_key]

                # Add new entry
                self._session_cache[cache_key] = cached_response

                # Enforce size limit with LRU eviction
                while len(self._session_cache) > self._config.session_cache_size:
                    # Remove oldest entry
                    oldest_key = next(iter(self._session_cache))
                    del self._session_cache[oldest_key]

        except Exception as e:
            logger.error(f"Failed to add to session cache: {e}")

    async def _update_access_info(self, cached_id: Optional[int], last_accessed: datetime, access_count: int) -> None:
        """Update access information in database."""
        try:
            if not cached_id:
                return

            query = """
            UPDATE cached_responses
            SET last_accessed = ?, access_count = ?
            WHERE id = ?
            """

            async with self.database_manager._get_connection() as conn:
                await conn.execute(query, (last_accessed.isoformat(), access_count, cached_id))
                await conn.commit()

        except Exception as e:
            logger.error(f"Failed to update access info: {e}")

    async def invalidate_screenshot_cache(self, screenshot_id: int) -> None:
        """
        Invalidate all cached responses for a screenshot.

        Args:
            screenshot_id: Screenshot ID to invalidate
        """
        try:
            # Remove from session cache
            async with self._session_cache_lock:
                keys_to_remove = [key for key in self._session_cache.keys()
                                if key.startswith(f"{screenshot_id}:")]
                for key in keys_to_remove:
                    del self._session_cache[key]

            # Remove from database
            query = "DELETE FROM cached_responses WHERE screenshot_id = ?"
            async with self.database_manager._get_connection() as conn:
                cursor = await conn.execute(query, (screenshot_id,))
                deleted_count = cursor.rowcount
                await conn.commit()

            logger.debug(f"Invalidated {deleted_count} cached responses for screenshot {screenshot_id}")

            # Emit invalidation event
            if self.event_bus:
                await self.event_bus.emit("cache.invalidation_complete", {
                    'screenshot_id': screenshot_id,
                    'deleted_count': deleted_count,
                    'timestamp': datetime.now().isoformat()
                })

        except Exception as e:
            logger.error(f"Failed to invalidate screenshot cache: {e}")

    async def flush_session_cache(self) -> None:
        """Flush the session cache."""
        try:
            async with self._session_cache_lock:
                cleared_count = len(self._session_cache)
                self._session_cache.clear()

            logger.debug(f"Flushed session cache: {cleared_count} entries")

        except Exception as e:
            logger.error(f"Failed to flush session cache: {e}")

    async def optimize_cache_database(self) -> None:
        """Optimize the cache database."""
        try:
            start_time = time.time()

            # Clean up expired entries
            expired_cleaned = await self._cleanup_expired_entries()

            # Enforce size limits
            size_cleaned = await self._enforce_cache_limits()

            # Vacuum database
            async with self.database_manager._get_connection() as conn:
                await conn.execute("VACUUM")
                await conn.commit()

            optimization_time = time.time() - start_time
            total_cleaned = expired_cleaned + size_cleaned

            logger.info(f"Cache optimization completed: {total_cleaned} entries cleaned, "
                       f"{optimization_time:.2f}s duration")

            # Emit optimization event
            if self.event_bus:
                await self.event_bus.emit("cache.optimization_complete", {
                    'expired_cleaned': expired_cleaned,
                    'size_cleaned': size_cleaned,
                    'optimization_time': optimization_time,
                    'timestamp': datetime.now().isoformat()
                })

        except Exception as e:
            logger.error(f"Failed to optimize cache database: {e}")

    async def _cleanup_expired_entries(self) -> int:
        """Clean up expired cache entries."""
        try:
            now = datetime.now()
            query = "DELETE FROM cached_responses WHERE expires_at IS NOT NULL AND expires_at < ?"

            async with self.database_manager._get_connection() as conn:
                cursor = await conn.execute(query, (now.isoformat(),))
                deleted_count = cursor.rowcount
                await conn.commit()

            self._stats.expired_count += deleted_count
            return deleted_count

        except Exception as e:
            logger.error(f"Failed to cleanup expired entries: {e}")
            return 0

    async def _enforce_cache_limits(self) -> int:
        """Enforce cache size limits by removing oldest entries."""
        try:
            # Check current count
            count_query = "SELECT COUNT(*) as count FROM cached_responses"
            async with self.database_manager._get_connection() as conn:
                cursor = await conn.execute(count_query)
                row = await cursor.fetchone()
                current_count = row['count'] if row else 0

            if current_count <= self._config.max_entries:
                return 0

            # Calculate how many to remove
            excess_count = current_count - self._config.max_entries

            # Remove oldest entries
            delete_query = """
            DELETE FROM cached_responses
            WHERE id IN (
                SELECT id FROM cached_responses
                ORDER BY last_accessed ASC
                LIMIT ?
            )
            """

            async with self.database_manager._get_connection() as conn:
                cursor = await conn.execute(delete_query, (excess_count,))
                deleted_count = cursor.rowcount
                await conn.commit()

            self._stats.evicted_count += deleted_count
            return deleted_count

        except Exception as e:
            logger.error(f"Failed to enforce cache limits: {e}")
            return 0

    async def _check_cleanup_needed(self) -> None:
        """Check if cleanup is needed and trigger if necessary."""
        try:
            # Simple check based on entry count
            count_query = "SELECT COUNT(*) as count FROM cached_responses"
            async with self.database_manager._get_connection() as conn:
                cursor = await conn.execute(count_query)
                row = await cursor.fetchone()
                current_count = row['count'] if row else 0

            # Trigger cleanup if we're over limit
            if current_count > self._config.max_entries * 1.1:  # 10% buffer
                asyncio.create_task(self.optimize_cache_database())

        except Exception as e:
            logger.error(f"Failed to check cleanup needed: {e}")

    async def _remove_expired_entry(self, cached_id: Optional[int]) -> None:
        """Remove specific expired entry."""
        try:
            if not cached_id:
                return

            query = "DELETE FROM cached_responses WHERE id = ?"
            async with self.database_manager._get_connection() as conn:
                await conn.execute(query, (cached_id,))
                await conn.commit()

        except Exception as e:
            logger.error(f"Failed to remove expired entry: {e}")

    async def _update_statistics(self) -> None:
        """Update cache statistics."""
        try:
            # Get database statistics
            stats_query = """
            SELECT
                COUNT(*) as total_entries,
                SUM(LENGTH(response_content)) as total_size,
                AVG(LENGTH(response_content)) as avg_size
            FROM cached_responses
            """

            async with self.database_manager._get_connection() as conn:
                cursor = await conn.execute(stats_query)
                row = await cursor.fetchone()

                if row:
                    self._stats.total_entries = row['total_entries'] or 0
                    self._stats.memory_usage_bytes = row['total_size'] or 0
                    self._stats.average_response_size = row['avg_size'] or 0.0

        except Exception as e:
            logger.error(f"Failed to update statistics: {e}")

    def get_cache_statistics(self) -> Dict[str, Any]:
        """Get current cache statistics."""
        return {
            'total_entries': self._stats.total_entries,
            'memory_usage_bytes': self._stats.memory_usage_bytes,
            'memory_usage_mb': round(self._stats.memory_usage_bytes / (1024 * 1024), 2),
            'session_cache_entries': len(self._session_cache),
            'hit_count': self._stats.hit_count,
            'miss_count': self._stats.miss_count,
            'hit_ratio': round(self._stats.hit_ratio * 100, 1),
            'expired_count': self._stats.expired_count,
            'evicted_count': self._stats.evicted_count,
            'average_response_size_bytes': round(self._stats.average_response_size, 1),
            'configuration': {
                'max_entries': self._config.max_entries,
                'ttl_hours': self._config.ttl_hours,
                'session_cache_size': self._config.session_cache_size
            }
        }

    async def _start_background_tasks(self) -> None:
        """Start background maintenance tasks."""
        try:
            # Start cleanup task
            cleanup_interval = self._config.cleanup_interval_hours * 3600
            self._cleanup_task = asyncio.create_task(
                self._periodic_cleanup_loop(cleanup_interval)
            )

            logger.info("Cache background tasks started")

        except Exception as e:
            logger.error(f"Failed to start background tasks: {e}")

    async def _periodic_cleanup_loop(self, interval_seconds: int) -> None:
        """Periodic cleanup loop."""
        try:
            while True:
                await asyncio.sleep(interval_seconds)

                try:
                    await self.optimize_cache_database()
                    await self._update_statistics()

                except Exception as e:
                    logger.error(f"Error in periodic cleanup: {e}")

        except asyncio.CancelledError:
            logger.info("Periodic cleanup task cancelled")
        except Exception as e:
            logger.error(f"Periodic cleanup loop failed: {e}")

    async def _handle_settings_changed(self, event_data) -> None:
        """Handle settings change events."""
        try:
            data = event_data.get('data', {})
            key = data.get('key', '')

            if key.startswith('cache.'):
                await self._load_settings()
                logger.info("Reloaded cache settings")

        except Exception as e:
            logger.error(f"Failed to handle settings change: {e}")

    async def _handle_ollama_response(self, event_data) -> None:
        """Handle Ollama response events for automatic caching."""
        try:
            data = event_data.get('data', {})
            screenshot_id = data.get('screenshot_id')
            prompt = data.get('prompt')
            response = data.get('response')

            if screenshot_id and prompt and response:
                await self.store_response(screenshot_id, prompt, response)

        except Exception as e:
            logger.error(f"Failed to handle Ollama response: {e}")

    async def _handle_optimization_requested(self, event_data) -> None:
        """Handle manual optimization requests."""
        try:
            await self.optimize_cache_database()

        except Exception as e:
            logger.error(f"Failed to handle optimization request: {e}")

    async def shutdown(self) -> None:
        """Shutdown the cache manager."""
        try:
            logger.info("Shutting down CacheManager")

            # Cancel background tasks
            if self._cleanup_task and not self._cleanup_task.done():
                self._cleanup_task.cancel()
                try:
                    await self._cleanup_task
                except asyncio.CancelledError:
                    pass

            if self._optimization_task and not self._optimization_task.done():
                self._optimization_task.cancel()
                try:
                    await self._optimization_task
                except asyncio.CancelledError:
                    pass

            # Clear session cache
            await self.flush_session_cache()

            logger.info("CacheManager shutdown complete")

        except Exception as e:
            logger.error(f"Error during CacheManager shutdown: {e}")
