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

    Provides operations for caching and storage cleanup tracking.
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
