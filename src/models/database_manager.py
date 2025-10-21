"""
Database Manager for screenshot application.

This module provides database operations for application settings
with SQLite backend and async operations.
"""

import asyncio
import logging
import json
import sqlite3
from typing import Optional, Dict, Any
import os

from src import DEFAULT_DATABASE_NAME




class DatabaseError(Exception):
    """Base exception for database operations."""
    pass


class DatabaseManager:
    """
    Manages SQLite database operations for the application.

    Provides async interface for settings storage and database management.
    """

    def __init__(self, db_path: Optional[str] = None, logger=None):
        """
        Initialize DatabaseManager.

        Args:
            db_path: Path to SQLite database file
            logger: Optional logger instance
        """
        self.db_path = db_path or DEFAULT_DATABASE_NAME
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
                # Settings table
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS settings (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        type TEXT DEFAULT 'string',
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # Schema version table for database migrations
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS schema_version (
                        version INTEGER PRIMARY KEY,
                        applied_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """)

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

    async def get_all_settings(self) -> Dict[str, Any]:
        """
        Get all settings as a dictionary.

        Returns:
            Dictionary of all settings
        """
        if not self._initialized:
            await self.initialize_database()

        try:
            settings = {}
            async with self._get_connection() as conn:
                cursor = await conn.execute("SELECT key, value, type FROM settings")
                rows = cursor.fetchall()

                for row in rows:
                    key, value_str, value_type = row

                    # Parse value based on type
                    if value_type == 'json':
                        value = json.loads(value_str)
                    elif value_type == 'bool':
                        value = value_str.lower() == 'true'
                    elif value_type == 'int':
                        value = int(value_str)
                    elif value_type == 'float':
                        value = float(value_str)
                    else:
                        value = value_str

                    settings[key] = value

            return settings

        except Exception as e:
            self.logger.error(f"Failed to get all settings: {e}")
            return {}

    async def delete_setting(self, key: str) -> bool:
        """
        Delete a setting.

        Args:
            key: Setting key to delete

        Returns:
            True if deleted successfully
        """
        if not self._initialized:
            await self.initialize_database()

        try:
            async with self._get_connection() as conn:
                await conn.execute("DELETE FROM settings WHERE key = ?", (key,))
                return True

        except Exception as e:
            self.logger.error(f"Failed to delete setting {key}: {e}")
            return False

    async def clear_all_settings(self) -> bool:
        """
        Clear all settings from the database.

        Returns:
            True if cleared successfully
        """
        if not self._initialized:
            await self.initialize_database()

        try:
            async with self._get_connection() as conn:
                await conn.execute("DELETE FROM settings")
                return True

        except Exception as e:
            self.logger.error(f"Failed to clear all settings: {e}")
            return False

    # Utility operations

    async def cleanup_database(self) -> None:
        """Perform database maintenance operations."""
        if not self._initialized:
            return

        try:
            async with self._get_connection() as conn:
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
        self.logger.debug("Database manager closed")
