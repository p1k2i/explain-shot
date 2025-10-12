"""
Database Manager for screenshot application.

This module provides database operations for screenshots, chat history,
presets, and settings with SQLite backend and async operations.
"""

import asyncio
import logging
import json
import sqlite3
from datetime import datetime
from typing import Optional, List, Dict, Any
import os

from .screenshot_models import ScreenshotMetadata


class DatabaseError(Exception):
    """Base exception for database operations."""
    pass


class DatabaseManager:
    """
    Manages SQLite database operations for the application.

    Provides async interface for screenshot metadata, chat history,
    presets, and settings storage.
    """

    def __init__(self, db_path: Optional[str] = None, logger=None):
        """
        Initialize DatabaseManager.

        Args:
            db_path: Path to SQLite database file
            logger: Optional logger instance
        """
        self.db_path = db_path or "app_data.db"
        self.logger = logger or logging.getLogger(__name__)
        self._connection_lock = asyncio.Lock()
        self._initialized = False

        # Ensure directory exists
        db_dir = os.path.dirname(os.path.abspath(self.db_path))
        os.makedirs(db_dir, exist_ok=True)

    async def initialize_database(self) -> None:
        """Initialize database with required tables."""
        if self._initialized:
            return

        try:
            async with self._get_connection() as conn:
                # Screenshots table
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS screenshots (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        filename TEXT NOT NULL,
                        path TEXT NOT NULL UNIQUE,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                        file_size INTEGER,
                        thumbnail_path TEXT,
                        metadata TEXT,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # Chat history table
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS chat_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        screenshot_id INTEGER,
                        prompt TEXT NOT NULL,
                        response TEXT,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                        model_name TEXT,
                        processing_time REAL,
                        FOREIGN KEY (screenshot_id) REFERENCES screenshots(id) ON DELETE CASCADE
                    )
                """)

                # Presets table
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS presets (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        preset_name TEXT NOT NULL UNIQUE,
                        prompt_text TEXT NOT NULL,
                        description TEXT,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        usage_count INTEGER DEFAULT 0
                    )
                """)

                # Settings table
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS settings (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        type TEXT DEFAULT 'string',
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # Create indexes for performance
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_screenshots_timestamp ON screenshots(timestamp)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_screenshot_id ON chat_history(screenshot_id)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_presets_usage ON presets(usage_count DESC)")

                await conn.commit()

            self._initialized = True
            self.logger.info(f"Database initialized: {self.db_path}")

        except Exception as e:
            self.logger.error(f"Failed to initialize database: {e}")
            raise DatabaseError(f"Database initialization failed: {e}") from e

    def _get_connection(self):
        """Get async database connection wrapper."""
        class AsyncConnection:
            def __init__(self, db_path, logger):
                self.db_path = db_path
                self.logger = logger
                self.conn = None

            async def __aenter__(self):
                try:
                    self.conn = sqlite3.connect(self.db_path)
                    self.conn.row_factory = sqlite3.Row
                    # Enable foreign keys
                    self.conn.execute("PRAGMA foreign_keys = ON")
                    return self
                except Exception as e:
                    self.logger.error(f"Failed to connect to database: {e}")
                    raise DatabaseError(f"Database connection failed: {e}") from e

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                if self.conn:
                    try:
                        if exc_type is None:
                            self.conn.commit()
                        else:
                            self.conn.rollback()
                    finally:
                        self.conn.close()

            async def execute(self, sql: str, params=None):
                """Execute SQL statement."""
                try:
                    if self.conn is None:
                        raise DatabaseError("No database connection")
                    return self.conn.execute(sql, params or ())
                except Exception as e:
                    self.logger.error(f"SQL execution failed: {sql}, params: {params}, error: {e}")
                    raise DatabaseError(f"SQL execution failed: {e}") from e

            async def commit(self):
                """Commit transaction."""
                if self.conn is None:
                    raise DatabaseError("No database connection")
                return self.conn.commit()

            async def rollback(self):
                """Rollback transaction."""
                if self.conn is None:
                    raise DatabaseError("No database connection")
                return self.conn.rollback()

        return AsyncConnection(self.db_path, self.logger)

    # Screenshot operations

    async def create_screenshot(self, metadata: ScreenshotMetadata) -> int:
        """
        Create a new screenshot record.

        Args:
            metadata: ScreenshotMetadata instance

        Returns:
            Database ID of created record
        """
        if not self._initialized:
            await self.initialize_database()

        try:
            async with self._get_connection() as conn:
                cursor = await conn.execute("""
                    INSERT INTO screenshots (filename, path, timestamp, file_size, thumbnail_path, metadata)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    metadata.filename,
                    metadata.full_path,
                    metadata.timestamp.isoformat(),
                    metadata.file_size,
                    metadata.thumbnail_path,
                    json.dumps({
                        'resolution': metadata.resolution,
                        'format': metadata.format,
                        'checksum': metadata.checksum
                    })
                ))

                result_id = cursor.lastrowid
                if result_id is None:
                    raise DatabaseError("Failed to get inserted record ID")
                return result_id

        except Exception as e:
            self.logger.error(f"Failed to create screenshot record: {e}")
            raise DatabaseError(f"Failed to create screenshot: {e}") from e

    async def get_screenshots(self, limit: int = 10, offset: int = 0) -> List[ScreenshotMetadata]:
        """
        Get screenshots ordered by timestamp descending.

        Args:
            limit: Maximum number of screenshots to return
            offset: Number of screenshots to skip

        Returns:
            List of ScreenshotMetadata objects
        """
        if not self._initialized:
            await self.initialize_database()

        try:
            async with self._get_connection() as conn:
                cursor = await conn.execute("""
                    SELECT id, filename, path, timestamp, file_size, thumbnail_path, metadata
                    FROM screenshots
                    ORDER BY timestamp DESC
                    LIMIT ? OFFSET ?
                """, (limit, offset))

                rows = cursor.fetchall()
                screenshots = []

                for row in rows:
                    try:
                        metadata_json = json.loads(row['metadata'] or '{}')

                        screenshots.append(ScreenshotMetadata(
                            id=row['id'],
                            filename=row['filename'],
                            full_path=row['path'],
                            timestamp=datetime.fromisoformat(row['timestamp']),
                            file_size=row['file_size'],
                            thumbnail_path=row['thumbnail_path'],
                            resolution=tuple(metadata_json.get('resolution', [0, 0])),
                            format=metadata_json.get('format', 'PNG'),
                            checksum=metadata_json.get('checksum')
                        ))
                    except (ValueError, KeyError) as e:
                        self.logger.warning(f"Invalid screenshot record {row['id']}: {e}")
                        continue

                return screenshots

        except Exception as e:
            self.logger.error(f"Failed to get screenshots: {e}")
            return []

    async def get_screenshots_before_date(self, cutoff_date: datetime) -> List[ScreenshotMetadata]:
        """
        Get screenshots older than the specified date.

        Args:
            cutoff_date: Date cutoff for old screenshots

        Returns:
            List of old ScreenshotMetadata objects
        """
        if not self._initialized:
            await self.initialize_database()

        try:
            async with self._get_connection() as conn:
                cursor = await conn.execute("""
                    SELECT id, filename, path, timestamp, file_size, thumbnail_path, metadata
                    FROM screenshots
                    WHERE timestamp < ?
                    ORDER BY timestamp ASC
                """, (cutoff_date.isoformat(),))

                rows = cursor.fetchall()
                screenshots = []

                for row in rows:
                    try:
                        metadata_json = json.loads(row['metadata'] or '{}')

                        screenshots.append(ScreenshotMetadata(
                            id=row['id'],
                            filename=row['filename'],
                            full_path=row['path'],
                            timestamp=datetime.fromisoformat(row['timestamp']),
                            file_size=row['file_size'],
                            thumbnail_path=row['thumbnail_path'],
                            resolution=tuple(metadata_json.get('resolution', [0, 0])),
                            format=metadata_json.get('format', 'PNG'),
                            checksum=metadata_json.get('checksum')
                        ))
                    except (ValueError, KeyError) as e:
                        self.logger.warning(f"Invalid screenshot record {row['id']}: {e}")
                        continue

                return screenshots

        except Exception as e:
            self.logger.error(f"Failed to get old screenshots: {e}")
            return []

    async def delete_screenshot(self, screenshot_id: int) -> bool:
        """
        Delete a screenshot record and associated chat history.

        Args:
            screenshot_id: ID of screenshot to delete

        Returns:
            True if deleted successfully
        """
        if not self._initialized:
            await self.initialize_database()

        try:
            async with self._get_connection() as conn:
                # Delete chat history first (foreign key constraint)
                await conn.execute("DELETE FROM chat_history WHERE screenshot_id = ?", (screenshot_id,))

                # Delete screenshot
                cursor = await conn.execute("DELETE FROM screenshots WHERE id = ?", (screenshot_id,))

                return cursor.rowcount > 0

        except Exception as e:
            self.logger.error(f"Failed to delete screenshot {screenshot_id}: {e}")
            return False

    async def get_screenshot_count(self) -> int:
        """
        Get total number of screenshots.

        Returns:
            Total screenshot count
        """
        if not self._initialized:
            await self.initialize_database()

        try:
            async with self._get_connection() as conn:
                cursor = await conn.execute("SELECT COUNT(*) FROM screenshots")
                row = cursor.fetchone()
                return row[0] if row else 0

        except Exception as e:
            self.logger.error(f"Failed to get screenshot count: {e}")
            return 0

    async def get_total_screenshot_size(self) -> int:
        """
        Get total file size of all screenshots.

        Returns:
            Total size in bytes
        """
        if not self._initialized:
            await self.initialize_database()

        try:
            async with self._get_connection() as conn:
                cursor = await conn.execute("SELECT SUM(file_size) FROM screenshots")
                row = cursor.fetchone()
                return row[0] if row and row[0] else 0

        except Exception as e:
            self.logger.error(f"Failed to get total screenshot size: {e}")
            return 0

    async def get_oldest_screenshot_date(self) -> Optional[datetime]:
        """
        Get timestamp of oldest screenshot.

        Returns:
            Oldest screenshot timestamp or None
        """
        if not self._initialized:
            await self.initialize_database()

        try:
            async with self._get_connection() as conn:
                cursor = await conn.execute("SELECT MIN(timestamp) FROM screenshots")
                row = cursor.fetchone()

                if row and row[0]:
                    return datetime.fromisoformat(row[0])
                return None

        except Exception as e:
            self.logger.error(f"Failed to get oldest screenshot date: {e}")
            return None

    async def get_newest_screenshot_date(self) -> Optional[datetime]:
        """
        Get timestamp of newest screenshot.

        Returns:
            Newest screenshot timestamp or None
        """
        if not self._initialized:
            await self.initialize_database()

        try:
            async with self._get_connection() as conn:
                cursor = await conn.execute("SELECT MAX(timestamp) FROM screenshots")
                row = cursor.fetchone()

                if row and row[0]:
                    return datetime.fromisoformat(row[0])
                return None

        except Exception as e:
            self.logger.error(f"Failed to get newest screenshot date: {e}")
            return None

    # Settings operations

    async def get_setting(self, key: str, default: Any = None) -> Any:
        """
        Get a setting value.

        Args:
            key: Setting key
            default: Default value if not found

        Returns:
            Setting value or default
        """
        if not self._initialized:
            await self.initialize_database()

        try:
            async with self._get_connection() as conn:
                cursor = await conn.execute("SELECT value, type FROM settings WHERE key = ?", (key,))
                row = cursor.fetchone()

                if not row:
                    return default

                value_str, value_type = row

                # Parse value based on type
                if value_type == 'json':
                    return json.loads(value_str)
                elif value_type == 'bool':
                    return value_str.lower() == 'true'
                elif value_type == 'int':
                    return int(value_str)
                elif value_type == 'float':
                    return float(value_str)
                else:
                    return value_str

        except Exception as e:
            self.logger.error(f"Failed to get setting {key}: {e}")
            return default

    async def set_setting(self, key: str, value: Any) -> bool:
        """
        Set a setting value.

        Args:
            key: Setting key
            value: Setting value

        Returns:
            True if set successfully
        """
        if not self._initialized:
            await self.initialize_database()

        try:
            # Determine value type and string representation
            if isinstance(value, bool):
                value_str = str(value).lower()
                value_type = 'bool'
            elif isinstance(value, int):
                value_str = str(value)
                value_type = 'int'
            elif isinstance(value, float):
                value_str = str(value)
                value_type = 'float'
            elif isinstance(value, (dict, list)):
                value_str = json.dumps(value)
                value_type = 'json'
            else:
                value_str = str(value)
                value_type = 'string'

            async with self._get_connection() as conn:
                await conn.execute("""
                    INSERT OR REPLACE INTO settings (key, value, type, updated_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                """, (key, value_str, value_type))

                return True

        except Exception as e:
            self.logger.error(f"Failed to set setting {key}: {e}")
            return False

    # Utility operations

    async def cleanup_database(self) -> None:
        """Perform database maintenance operations."""
        if not self._initialized:
            return

        try:
            async with self._get_connection() as conn:
                # Remove orphaned chat history
                await conn.execute("""
                    DELETE FROM chat_history
                    WHERE screenshot_id NOT IN (SELECT id FROM screenshots)
                """)

                # Vacuum database to reclaim space
                await conn.execute("VACUUM")

            self.logger.info("Database cleanup completed")

        except Exception as e:
            self.logger.error(f"Database cleanup failed: {e}")

    async def get_database_stats(self) -> Dict[str, Any]:
        """
        Get database statistics.

        Returns:
            Dictionary with database statistics
        """
        if not self._initialized:
            await self.initialize_database()

        try:
            stats = {}

            async with self._get_connection() as conn:
                # Screenshot count
                cursor = await conn.execute("SELECT COUNT(*) FROM screenshots")
                stats['screenshot_count'] = cursor.fetchone()[0]

                # Chat history count
                cursor = await conn.execute("SELECT COUNT(*) FROM chat_history")
                stats['chat_count'] = cursor.fetchone()[0]

                # Presets count
                cursor = await conn.execute("SELECT COUNT(*) FROM presets")
                stats['preset_count'] = cursor.fetchone()[0]

                # Settings count
                cursor = await conn.execute("SELECT COUNT(*) FROM settings")
                stats['setting_count'] = cursor.fetchone()[0]

                # Database file size
                if os.path.exists(self.db_path):
                    stats['file_size_bytes'] = os.path.getsize(self.db_path)
                else:
                    stats['file_size_bytes'] = 0

            return stats

        except Exception as e:
            self.logger.error(f"Failed to get database stats: {e}")
            return {}

    async def close(self) -> None:
        """Close database connections and cleanup."""
        # In this implementation, connections are managed per-operation
        # so no persistent connections to close
        self._initialized = False
        self.logger.info("Database manager closed")
