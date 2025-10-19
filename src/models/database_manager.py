"""
Database Manager for screenshot application.

This module provides database operations for presets and settings
with SQLite backend and async operations.
"""

import asyncio
import logging
import json
import sqlite3
from typing import Optional, List, Dict, Any, TYPE_CHECKING
import os

from src import DEFAULT_DATABASE_NAME

if TYPE_CHECKING:
    from .preset_models import PresetMetadata


class DatabaseError(Exception):
    """Base exception for database operations."""
    pass


class DatabaseManager:
    """
    Manages SQLite database operations for the application.

    Provides async interface for presets and settings storage.
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
                # Presets table
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS presets (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL UNIQUE,
                        prompt TEXT NOT NULL,
                        description TEXT DEFAULT '',
                        category TEXT DEFAULT 'general',
                        tags TEXT DEFAULT '[]',
                        usage_count INTEGER DEFAULT 0,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        is_favorite BOOLEAN DEFAULT 0,
                        is_builtin BOOLEAN DEFAULT 0
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
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_presets_usage ON presets(usage_count DESC)")

                await conn.commit()

            self._initialized = True
            self.logger.info(f"Database initialized: {self.db_path}")

            # Initialize builtin presets
            await self.initialize_builtin_presets()

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

    # Preset management methods

    async def create_preset(self, preset: 'PresetMetadata') -> int:
        """
        Create a new preset in the database.

        Args:
            preset: PresetMetadata object to store

        Returns:
            The ID of the created preset

        Raises:
            DatabaseError: If preset creation fails
        """
        if not self._initialized:
            await self.initialize_database()

        try:
            async with self._get_connection() as conn:
                preset_data = preset.to_dict()
                cursor = await conn.execute("""
                    INSERT INTO presets (
                        name, prompt, description, category, tags,
                        usage_count, created_at, updated_at, is_favorite, is_builtin
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    preset_data['name'],
                    preset_data['prompt'],
                    preset_data['description'],
                    preset_data['category'],
                    preset_data['tags'],
                    preset_data['usage_count'],
                    preset_data['created_at'],
                    preset_data['updated_at'],
                    preset_data['is_favorite'],
                    preset_data['is_builtin']
                ))

                preset_id = cursor.lastrowid
                await conn.commit()

                if preset_id is None:
                    raise DatabaseError("Failed to get preset ID after creation")

                self.logger.info(f"Created preset: {preset.name} (ID: {preset_id})")
                return preset_id

        except sqlite3.IntegrityError as e:
            error_msg = f"Preset name already exists: {preset.name}"
            self.logger.error(error_msg)
            raise DatabaseError(error_msg) from e
        except Exception as e:
            error_msg = f"Failed to create preset: {e}"
            self.logger.error(error_msg)
            raise DatabaseError(error_msg) from e

    async def get_presets(self, category: Optional[str] = None, limit: int = 50, offset: int = 0) -> List['PresetMetadata']:
        """
        Retrieve presets from the database.

        Args:
            category: Optional category filter
            limit: Maximum number of presets to return
            offset: Number of presets to skip

        Returns:
            List of PresetMetadata objects
        """
        if not self._initialized:
            await self.initialize_database()

        try:
            async with self._get_connection() as conn:
                if category:
                    query = """
                        SELECT * FROM presets
                        WHERE category = ?
                        ORDER BY usage_count DESC, name ASC
                        LIMIT ? OFFSET ?
                    """
                    params = (category, limit, offset)
                else:
                    query = """
                        SELECT * FROM presets
                        ORDER BY usage_count DESC, name ASC
                        LIMIT ? OFFSET ?
                    """
                    params = (limit, offset)

                cursor = await conn.execute(query, params)
                rows = cursor.fetchall()

                # Import here to avoid circular import
                from .preset_models import PresetMetadata

                presets = []
                for row in rows:
                    preset_dict = {
                        'id': row[0],
                        'name': row[1],
                        'prompt': row[2],
                        'description': row[3],
                        'category': row[4],
                        'tags': row[5],
                        'usage_count': row[6],
                        'created_at': row[7],
                        'updated_at': row[8],
                        'is_favorite': bool(row[9]),
                        'is_builtin': bool(row[10])
                    }
                    presets.append(PresetMetadata.from_dict(preset_dict))

                return presets

        except Exception as e:
            self.logger.error(f"Failed to get presets: {e}")
            return []

    async def get_preset_by_id(self, preset_id: int) -> Optional['PresetMetadata']:
        """
        Get a specific preset by ID.

        Args:
            preset_id: The preset ID to retrieve

        Returns:
            PresetMetadata object or None if not found
        """
        if not self._initialized:
            await self.initialize_database()

        try:
            async with self._get_connection() as conn:
                cursor = await conn.execute("SELECT * FROM presets WHERE id = ?", (preset_id,))
                row = cursor.fetchone()

                if not row:
                    return None

                # Import here to avoid circular import
                from .preset_models import PresetMetadata

                preset_dict = {
                    'id': row[0],
                    'name': row[1],
                    'prompt': row[2],
                    'description': row[3],
                    'category': row[4],
                    'tags': row[5],
                    'usage_count': row[6],
                    'created_at': row[7],
                    'updated_at': row[8],
                    'is_favorite': bool(row[9]),
                    'is_builtin': bool(row[10])
                }
                return PresetMetadata.from_dict(preset_dict)

        except Exception as e:
            self.logger.error(f"Failed to get preset {preset_id}: {e}")
            return None

    async def update_preset(self, preset: 'PresetMetadata') -> bool:
        """
        Update an existing preset.

        Args:
            preset: PresetMetadata object with updated data

        Returns:
            True if update successful
        """
        if not self._initialized:
            await self.initialize_database()

        try:
            async with self._get_connection() as conn:
                preset_data = preset.to_dict()
                await conn.execute("""
                    UPDATE presets SET
                        name = ?, prompt = ?, description = ?, category = ?,
                        tags = ?, usage_count = ?, updated_at = ?,
                        is_favorite = ?, is_builtin = ?
                    WHERE id = ?
                """, (
                    preset_data['name'],
                    preset_data['prompt'],
                    preset_data['description'],
                    preset_data['category'],
                    preset_data['tags'],
                    preset_data['usage_count'],
                    preset_data['updated_at'],
                    preset_data['is_favorite'],
                    preset_data['is_builtin'],
                    preset.id
                ))

                await conn.commit()
                self.logger.info(f"Updated preset: {preset.name}")
                return True

        except Exception as e:
            self.logger.error(f"Failed to update preset {preset.id}: {e}")
            return False

    async def delete_preset(self, preset_id: int) -> bool:
        """
        Delete a preset from the database.

        Args:
            preset_id: The ID of the preset to delete

        Returns:
            True if deletion successful
        """
        if not self._initialized:
            await self.initialize_database()

        try:
            async with self._get_connection() as conn:
                # Check if preset is builtin (cannot be deleted)
                cursor = await conn.execute("SELECT is_builtin FROM presets WHERE id = ?", (preset_id,))
                row = cursor.fetchone()

                if not row:
                    return False

                if row[0]:  # is_builtin is True
                    self.logger.warning(f"Cannot delete builtin preset {preset_id}")
                    return False

                await conn.execute("DELETE FROM presets WHERE id = ?", (preset_id,))
                await conn.commit()

                self.logger.info(f"Deleted preset: {preset_id}")
                return True

        except Exception as e:
            self.logger.error(f"Failed to delete preset {preset_id}: {e}")
            return False

    async def increment_preset_usage(self, preset_id: int) -> bool:
        """
        Increment the usage count for a preset.

        Args:
            preset_id: The ID of the preset

        Returns:
            True if increment successful
        """
        if not self._initialized:
            await self.initialize_database()

        try:
            async with self._get_connection() as conn:
                await conn.execute("""
                    UPDATE presets SET
                        usage_count = usage_count + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (preset_id,))

                await conn.commit()
                return True

        except Exception as e:
            self.logger.error(f"Failed to increment preset usage {preset_id}: {e}")
            return False

    async def initialize_builtin_presets(self) -> None:
        """Initialize built-in presets if they don't exist."""
        try:
            # Import here to avoid circular import
            from .preset_models import BUILTIN_PRESETS

            async with self._get_connection() as conn:
                for preset_def in BUILTIN_PRESETS:
                    # Check if preset already exists
                    cursor = await conn.execute(
                        "SELECT id FROM presets WHERE name = ? AND is_builtin = 1",
                        (preset_def.name,)
                    )

                    if cursor.fetchone() is None:
                        # Create the builtin preset
                        preset_data = preset_def.to_dict()
                        await conn.execute("""
                            INSERT INTO presets (
                                name, prompt, description, category, tags,
                                usage_count, created_at, updated_at, is_favorite, is_builtin
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            preset_data['name'],
                            preset_data['prompt'],
                            preset_data['description'],
                            preset_data['category'],
                            preset_data['tags'],
                            preset_data['usage_count'],
                            preset_data['created_at'],
                            preset_data['updated_at'],
                            preset_data['is_favorite'],
                            preset_data['is_builtin']
                        ))

                await conn.commit()
                self.logger.info("Initialized builtin presets")

        except Exception as e:
            self.logger.error(f"Failed to initialize builtin presets: {e}")

    async def close(self) -> None:
        """Close database connections and cleanup."""
        # In this implementation, connections are managed per-operation
        # so no persistent connections to close
        self._initialized = False
        self.logger.info("Database manager closed")
