"""
Database Extensions for Performance Optimization.

This module extends the DatabaseManager with performance-related
operations for caching, metrics, and storage management.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from .database_manager import DatabaseManager


class CacheOperationError(Exception):
    """Exception raised for cache operation errors."""
    pass


class MetricsOperationError(Exception):
    """Exception raised for metrics operation errors."""
    pass


class DatabaseExtensions:
    """
    Extensions to DatabaseManager for performance optimization features.

    Provides operations for cached responses, performance metrics,
    and storage cleanup tracking.
    """

    def __init__(self, database_manager: DatabaseManager, logger=None):
        """
        Initialize database extensions.

        Args:
            database_manager: DatabaseManager instance
            logger: Optional logger instance
        """
        self.db_manager = database_manager
        self.logger = logger or logging.getLogger(__name__)

    # Cached Responses Operations

    async def store_cached_response(
        self,
        prompt_hash: str,
        original_prompt: str,
        response: str,
        model_name: str,
        processing_time: float = 0.0,
        ttl_hours: Optional[int] = None,
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Store a cached AI response.

        Args:
            prompt_hash: Hash of the prompt for quick lookup
            original_prompt: Original prompt text
            response: AI response text
            model_name: Name of AI model used
            processing_time: Time taken to generate response
            ttl_hours: Time-to-live in hours (None for no expiration)
            session_id: Session identifier
            metadata: Additional metadata dictionary

        Returns:
            True if stored successfully
        """
        if not self.db_manager._initialized:
            await self.db_manager.initialize_database()

        try:
            ttl_expires_at = None
            if ttl_hours is not None:
                ttl_expires_at = (datetime.now() + timedelta(hours=ttl_hours)).isoformat()

            metadata_json = json.dumps(metadata or {})
            response_size = len(response.encode('utf-8'))

            async with self.db_manager._get_connection() as conn:
                await conn.execute("""
                    INSERT OR REPLACE INTO cached_responses (
                        prompt_hash, original_prompt, response, model_name,
                        response_size, processing_time, ttl_expires_at,
                        session_id, metadata, cached_at, last_accessed, access_count
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1)
                """, (
                    prompt_hash, original_prompt, response, model_name,
                    response_size, processing_time, ttl_expires_at,
                    session_id, metadata_json
                ))

                await conn.commit()
                self.logger.debug(f"Cached response for prompt hash: {prompt_hash}")
                return True

        except Exception as e:
            self.logger.error(f"Failed to store cached response: {e}")
            raise CacheOperationError(f"Cache storage failed: {e}") from e

    async def get_cached_response(
        self,
        prompt_hash: str,
        model_name: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve a cached response by prompt hash.

        Args:
            prompt_hash: Hash of the prompt
            model_name: Optional model name filter

        Returns:
            Dictionary with cached response data or None
        """
        if not self.db_manager._initialized:
            await self.db_manager.initialize_database()

        try:
            async with self.db_manager._get_connection() as conn:
                # Build query with optional model filter
                query = """
                    SELECT * FROM cached_responses
                    WHERE prompt_hash = ?
                    AND (ttl_expires_at IS NULL OR ttl_expires_at > datetime('now'))
                """
                params = [prompt_hash]

                if model_name:
                    query += " AND model_name = ?"
                    params.append(model_name)

                query += " ORDER BY last_accessed DESC LIMIT 1"

                cursor = await conn.execute(query, params)
                row = cursor.fetchone()

                if row:
                    # Update access tracking
                    await conn.execute("""
                        UPDATE cached_responses
                        SET last_accessed = CURRENT_TIMESTAMP, access_count = access_count + 1
                        WHERE id = ?
                    """, (row['id'],))
                    await conn.commit()

                    # Return cached response data
                    return {
                        'id': row['id'],
                        'prompt_hash': row['prompt_hash'],
                        'original_prompt': row['original_prompt'],
                        'response': row['response'],
                        'model_name': row['model_name'],
                        'cached_at': row['cached_at'],
                        'last_accessed': row['last_accessed'],
                        'access_count': row['access_count'],
                        'response_size': row['response_size'],
                        'processing_time': row['processing_time'],
                        'session_id': row['session_id'],
                        'metadata': json.loads(row['metadata'] or '{}')
                    }

                return None

        except Exception as e:
            self.logger.error(f"Failed to get cached response: {e}")
            return None

    async def cleanup_expired_cache(self) -> int:
        """
        Remove expired cached responses.

        Returns:
            Number of expired entries removed
        """
        if not self.db_manager._initialized:
            await self.db_manager.initialize_database()

        try:
            async with self.db_manager._get_connection() as conn:
                cursor = await conn.execute("""
                    DELETE FROM cached_responses
                    WHERE ttl_expires_at IS NOT NULL
                    AND ttl_expires_at <= datetime('now')
                """)

                removed_count = cursor.rowcount
                await conn.commit()

                if removed_count > 0:
                    self.logger.info(f"Removed {removed_count} expired cache entries")

                return removed_count

        except Exception as e:
            self.logger.error(f"Failed to cleanup expired cache: {e}")
            return 0

    async def cleanup_lru_cache(self, max_entries: int) -> int:
        """
        Remove least recently used cache entries to stay under limit.

        Args:
            max_entries: Maximum number of cache entries to keep

        Returns:
            Number of entries removed
        """
        if not self.db_manager._initialized:
            await self.db_manager.initialize_database()

        try:
            async with self.db_manager._get_connection() as conn:
                # Count current entries
                cursor = await conn.execute("SELECT COUNT(*) FROM cached_responses")
                current_count = cursor.fetchone()[0]

                if current_count <= max_entries:
                    return 0

                # Remove oldest entries
                entries_to_remove = current_count - max_entries
                cursor = await conn.execute("""
                    DELETE FROM cached_responses
                    WHERE id IN (
                        SELECT id FROM cached_responses
                        ORDER BY last_accessed ASC
                        LIMIT ?
                    )
                """, (entries_to_remove,))

                removed_count = cursor.rowcount
                await conn.commit()

                if removed_count > 0:
                    self.logger.info(f"Removed {removed_count} LRU cache entries")

                return removed_count

        except Exception as e:
            self.logger.error(f"Failed to cleanup LRU cache: {e}")
            return 0

    async def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache statistics
        """
        if not self.db_manager._initialized:
            await self.db_manager.initialize_database()

        try:
            stats = {}

            async with self.db_manager._get_connection() as conn:
                # Total entries
                cursor = await conn.execute("SELECT COUNT(*) FROM cached_responses")
                stats['total_entries'] = cursor.fetchone()[0]

                # Total size
                cursor = await conn.execute("SELECT SUM(response_size) FROM cached_responses")
                result = cursor.fetchone()[0]
                stats['total_size_bytes'] = result if result else 0

                # Average access count
                cursor = await conn.execute("SELECT AVG(access_count) FROM cached_responses")
                result = cursor.fetchone()[0]
                stats['avg_access_count'] = round(result, 2) if result else 0.0

                # Entries by model
                cursor = await conn.execute("""
                    SELECT model_name, COUNT(*)
                    FROM cached_responses
                    GROUP BY model_name
                """)
                stats['entries_by_model'] = dict(cursor.fetchall())

                # Expired entries
                cursor = await conn.execute("""
                    SELECT COUNT(*) FROM cached_responses
                    WHERE ttl_expires_at IS NOT NULL
                    AND ttl_expires_at <= datetime('now')
                """)
                stats['expired_entries'] = cursor.fetchone()[0]

            return stats

        except Exception as e:
            self.logger.error(f"Failed to get cache stats: {e}")
            return {}

    # Performance Metrics Operations

    async def store_performance_metric(
        self,
        metric_type: str,
        component: str,
        value: float,
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Store a performance metric.

        Args:
            metric_type: Type of metric (e.g., 'memory_usage', 'response_time')
            component: Component being measured
            value: Metric value
            session_id: Session identifier
            metadata: Additional metadata dictionary

        Returns:
            True if stored successfully
        """
        if not self.db_manager._initialized:
            await self.db_manager.initialize_database()

        try:
            metadata_json = json.dumps(metadata or {})

            async with self.db_manager._get_connection() as conn:
                await conn.execute("""
                    INSERT INTO performance_metrics (
                        metric_type, component, value, session_id, metadata
                    ) VALUES (?, ?, ?, ?, ?)
                """, (metric_type, component, value, session_id, metadata_json))

                await conn.commit()
                return True

        except Exception as e:
            self.logger.error(f"Failed to store performance metric: {e}")
            raise MetricsOperationError(f"Metrics storage failed: {e}") from e

    async def get_performance_metrics(
        self,
        metric_type: Optional[str] = None,
        component: Optional[str] = None,
        hours_back: int = 24,
        limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """
        Retrieve performance metrics.

        Args:
            metric_type: Optional metric type filter
            component: Optional component filter
            hours_back: Number of hours to look back
            limit: Maximum number of metrics to return

        Returns:
            List of metric dictionaries
        """
        if not self.db_manager._initialized:
            await self.db_manager.initialize_database()

        try:
            # Build query with filters
            query = """
                SELECT * FROM performance_metrics
                WHERE timestamp >= datetime('now', '-{} hours')
            """.format(hours_back)
            params = []

            if metric_type:
                query += " AND metric_type = ?"
                params.append(metric_type)

            if component:
                query += " AND component = ?"
                params.append(component)

            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)

            async with self.db_manager._get_connection() as conn:
                cursor = await conn.execute(query, params)
                rows = cursor.fetchall()

                metrics = []
                for row in rows:
                    metrics.append({
                        'id': row['id'],
                        'metric_type': row['metric_type'],
                        'component': row['component'],
                        'value': row['value'],
                        'timestamp': row['timestamp'],
                        'session_id': row['session_id'],
                        'metadata': json.loads(row['metadata'] or '{}')
                    })

                return metrics

        except Exception as e:
            self.logger.error(f"Failed to get performance metrics: {e}")
            return []

    async def get_metric_aggregates(
        self,
        metric_type: str,
        component: Optional[str] = None,
        hours_back: int = 24
    ) -> Dict[str, float]:
        """
        Get aggregate statistics for a metric.

        Args:
            metric_type: Type of metric to aggregate
            component: Optional component filter
            hours_back: Number of hours to look back

        Returns:
            Dictionary with min, max, avg, count statistics
        """
        if not self.db_manager._initialized:
            await self.db_manager.initialize_database()

        try:
            query = """
                SELECT
                    MIN(value) as min_value,
                    MAX(value) as max_value,
                    AVG(value) as avg_value,
                    COUNT(*) as count
                FROM performance_metrics
                WHERE metric_type = ?
                AND timestamp >= datetime('now', '-{} hours')
            """.format(hours_back)
            params = [metric_type]

            if component:
                query += " AND component = ?"
                params.append(component)

            async with self.db_manager._get_connection() as conn:
                cursor = await conn.execute(query, params)
                row = cursor.fetchone()

                if row and row['count'] > 0:
                    return {
                        'min': float(row['min_value']),
                        'max': float(row['max_value']),
                        'avg': round(float(row['avg_value']), 2),
                        'count': int(row['count'])
                    }
                else:
                    return {'min': 0.0, 'max': 0.0, 'avg': 0.0, 'count': 0}

        except Exception as e:
            self.logger.error(f"Failed to get metric aggregates: {e}")
            return {'min': 0.0, 'max': 0.0, 'avg': 0.0, 'count': 0}

    async def cleanup_old_metrics(self, days_to_keep: int = 30) -> int:
        """
        Remove old performance metrics.

        Args:
            days_to_keep: Number of days of metrics to keep

        Returns:
            Number of metrics removed
        """
        if not self.db_manager._initialized:
            await self.db_manager.initialize_database()

        try:
            async with self.db_manager._get_connection() as conn:
                cursor = await conn.execute("""
                    DELETE FROM performance_metrics
                    WHERE timestamp < datetime('now', '-{} days')
                """.format(days_to_keep))

                removed_count = cursor.rowcount
                await conn.commit()

                if removed_count > 0:
                    self.logger.info(f"Removed {removed_count} old metric entries")

                return removed_count

        except Exception as e:
            self.logger.error(f"Failed to cleanup old metrics: {e}")
            return 0

    # Storage Cleanup Operations

    async def log_storage_cleanup(
        self,
        cleanup_type: str,
        files_removed: int = 0,
        bytes_freed: int = 0,
        duration_seconds: float = 0.0,
        triggered_by: str = "system",
        details: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Log a storage cleanup operation.

        Args:
            cleanup_type: Type of cleanup performed
            files_removed: Number of files removed
            bytes_freed: Bytes of storage freed
            duration_seconds: Time taken for cleanup
            triggered_by: What triggered the cleanup
            details: Additional details dictionary

        Returns:
            True if logged successfully
        """
        if not self.db_manager._initialized:
            await self.db_manager.initialize_database()

        try:
            details_json = json.dumps(details or {})

            async with self.db_manager._get_connection() as conn:
                await conn.execute("""
                    INSERT INTO storage_cleanup_log (
                        cleanup_type, files_removed, bytes_freed,
                        duration_seconds, triggered_by, details
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    cleanup_type, files_removed, bytes_freed,
                    duration_seconds, triggered_by, details_json
                ))

                await conn.commit()
                self.logger.debug(f"Logged cleanup: {cleanup_type} - {files_removed} files, {bytes_freed} bytes")
                return True

        except Exception as e:
            self.logger.error(f"Failed to log storage cleanup: {e}")
            return False

    async def get_cleanup_history(
        self,
        cleanup_type: Optional[str] = None,
        days_back: int = 30,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get storage cleanup history.

        Args:
            cleanup_type: Optional cleanup type filter
            days_back: Number of days to look back
            limit: Maximum number of entries to return

        Returns:
            List of cleanup log dictionaries
        """
        if not self.db_manager._initialized:
            await self.db_manager.initialize_database()

        try:
            query = """
                SELECT * FROM storage_cleanup_log
                WHERE cleanup_at >= datetime('now', '-{} days')
            """.format(days_back)
            params = []

            if cleanup_type:
                query += " AND cleanup_type = ?"
                params.append(cleanup_type)

            query += " ORDER BY cleanup_at DESC LIMIT ?"
            params.append(limit)

            async with self.db_manager._get_connection() as conn:
                cursor = await conn.execute(query, params)
                rows = cursor.fetchall()

                cleanup_logs = []
                for row in rows:
                    cleanup_logs.append({
                        'id': row['id'],
                        'cleanup_type': row['cleanup_type'],
                        'files_removed': row['files_removed'],
                        'bytes_freed': row['bytes_freed'],
                        'duration_seconds': row['duration_seconds'],
                        'triggered_by': row['triggered_by'],
                        'cleanup_at': row['cleanup_at'],
                        'details': json.loads(row['details'] or '{}')
                    })

                return cleanup_logs

        except Exception as e:
            self.logger.error(f"Failed to get cleanup history: {e}")
            return []

    async def get_cleanup_stats(self, days_back: int = 30) -> Dict[str, Any]:
        """
        Get storage cleanup statistics.

        Args:
            days_back: Number of days to analyze

        Returns:
            Dictionary with cleanup statistics
        """
        if not self.db_manager._initialized:
            await self.db_manager.initialize_database()

        try:
            stats = {}

            async with self.db_manager._get_connection() as conn:
                # Total cleanups
                cursor = await conn.execute("""
                    SELECT COUNT(*) FROM storage_cleanup_log
                    WHERE cleanup_at >= datetime('now', '-{} days')
                """.format(days_back))
                stats['total_cleanups'] = cursor.fetchone()[0]

                # Total files removed
                cursor = await conn.execute("""
                    SELECT SUM(files_removed) FROM storage_cleanup_log
                    WHERE cleanup_at >= datetime('now', '-{} days')
                """.format(days_back))
                result = cursor.fetchone()[0]
                stats['total_files_removed'] = result if result else 0

                # Total bytes freed
                cursor = await conn.execute("""
                    SELECT SUM(bytes_freed) FROM storage_cleanup_log
                    WHERE cleanup_at >= datetime('now', '-{} days')
                """.format(days_back))
                result = cursor.fetchone()[0]
                stats['total_bytes_freed'] = result if result else 0

                # Cleanups by type
                cursor = await conn.execute("""
                    SELECT cleanup_type, COUNT(*), SUM(files_removed), SUM(bytes_freed)
                    FROM storage_cleanup_log
                    WHERE cleanup_at >= datetime('now', '-{} days')
                    GROUP BY cleanup_type
                """.format(days_back))
                stats['by_type'] = {}
                for row in cursor.fetchall():
                    stats['by_type'][row[0]] = {
                        'count': row[1],
                        'files_removed': row[2] or 0,
                        'bytes_freed': row[3] or 0
                    }

            return stats

        except Exception as e:
            self.logger.error(f"Failed to get cleanup stats: {e}")
            return {}
