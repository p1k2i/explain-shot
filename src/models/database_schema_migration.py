"""
Database Schema Migration Manager.

This module handles database schema updates and migrations
for performance optimization features.
"""

import logging
import sqlite3
from typing import List, Dict, Any


class SchemaMigrationError(Exception):
    """Exception raised for schema migration errors."""
    pass


class DatabaseSchemaMigration:
    """
    Manages database schema migrations for performance optimization.

    Handles adding new tables, indexes, and schema changes while
    maintaining data integrity and backwards compatibility.
    """

    def __init__(self, database_manager, logger=None):
        """
        Initialize schema migration manager.

        Args:
            database_manager: DatabaseManager instance
            logger: Optional logger instance
        """
        self.db_manager = database_manager
        self.logger = logger or logging.getLogger(__name__)
        self.current_version = 1  # Base schema version
        self.target_version = 3   # File-based storage version (v2 removed)

    async def get_schema_version(self) -> int:
        """
        Get current database schema version.

        Returns:
            Current schema version number
        """
        try:
            # Check if schema_version table exists
            async with self.db_manager._get_connection() as conn:
                cursor = await conn.execute("""
                    SELECT name FROM sqlite_master
                    WHERE type='table' AND name='schema_version'
                """)

                if not cursor.fetchone():
                    # No version table - this is version 1 (base schema)
                    await self._create_schema_version_table()
                    await self._set_schema_version(1)
                    return 1

                # Get current version
                cursor = await conn.execute("SELECT version FROM schema_version ORDER BY id DESC LIMIT 1")
                row = cursor.fetchone()
                return row[0] if row else 1

        except Exception as e:
            self.logger.error(f"Failed to get schema version: {e}")
            return 1

    async def _create_schema_version_table(self) -> None:
        """Create schema_version table for tracking migrations."""
        try:
            async with self.db_manager._get_connection() as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS schema_version (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        version INTEGER NOT NULL,
                        applied_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        description TEXT
                    )
                """)
                await conn.commit()
                self.logger.info("Created schema_version table")

        except Exception as e:
            self.logger.error(f"Failed to create schema_version table: {e}")
            raise SchemaMigrationError(f"Schema version table creation failed: {e}") from e

    async def _set_schema_version(self, version: int, description: str = "") -> None:
        """Set schema version in database."""
        try:
            async with self.db_manager._get_connection() as conn:
                await conn.execute("""
                    INSERT INTO schema_version (version, description)
                    VALUES (?, ?)
                """, (version, description))
                await conn.commit()

        except Exception as e:
            self.logger.error(f"Failed to set schema version {version}: {e}")
            raise SchemaMigrationError(f"Schema version update failed: {e}") from e

    async def migrate_to_latest(self) -> bool:
        """
        Migrate database to latest schema version.

        Returns:
            True if migration successful
        """
        try:
            current_version = await self.get_schema_version()

            if current_version >= self.target_version:
                self.logger.info(f"Database already at latest version {current_version}")
                return True

            self.logger.info(f"Migrating database from version {current_version} to {self.target_version}")

            # Apply migrations sequentially
            for version in range(current_version + 1, self.target_version + 1):
                success = await self._apply_migration(version)
                if not success:
                    self.logger.error(f"Migration to version {version} failed")
                    return False

            self.logger.info("Database migration completed successfully")
            return True

        except Exception as e:
            self.logger.error(f"Database migration failed: {e}")
            return False

    async def _apply_migration(self, target_version: int) -> bool:
        """
        Apply specific migration version.

        Args:
            target_version: Version to migrate to

        Returns:
            True if migration successful
        """
        try:
            if target_version == 2:
                raise SchemaMigrationError("Migration to version 2 has been removed.")
            elif target_version == 3:
                raise SchemaMigrationError("Migration to version 3 has been removed.")
            else:
                self.logger.warning(f"Unknown migration version: {target_version}")
                return False

        except Exception as e:
            self.logger.error(f"Migration to version {target_version} failed: {e}")
            return False

    async def validate_schema(self) -> Dict[str, Any]:
        """
        Validate current database schema.

        Returns:
            Dictionary with validation results
        """
        validation_results = {
            'valid': True,
            'version': 0,
            'tables': {},
            'indexes': {},
            'errors': []
        }

        try:
            validation_results['version'] = await self.get_schema_version()

            async with self.db_manager._get_connection() as conn:
                # Check required tables based on version

                # v3: Minimal schema with only presets and settings
                required_tables = [
                    'presets', 'settings', 'schema_version'
                ]

                for table in required_tables:
                    cursor = await conn.execute("""
                        SELECT name FROM sqlite_master
                        WHERE type='table' AND name=?
                    """, (table,))

                    exists = cursor.fetchone() is not None
                    validation_results['tables'][table] = exists

                    if not exists:
                        validation_results['valid'] = False
                        validation_results['errors'].append(f"Missing table: {table}")

                # Check required indexes based on version
                # v3: Only preset index required
                required_indexes = [
                    'idx_presets_usage'
                ]

                for index in required_indexes:
                    cursor = await conn.execute("""
                        SELECT name FROM sqlite_master
                        WHERE type='index' AND name=?
                    """, (index,))

                    exists = cursor.fetchone() is not None
                    validation_results['indexes'][index] = exists

                    if not exists:
                        validation_results['valid'] = False
                        validation_results['errors'].append(f"Missing index: {index}")

        except Exception as e:
            validation_results['valid'] = False
            validation_results['errors'].append(f"Validation error: {e}")
            self.logger.error(f"Schema validation failed: {e}")

        return validation_results

    async def get_table_info(self, table_name: str) -> List[Dict[str, Any]]:
        """
        Get detailed table information.

        Args:
            table_name: Name of table to inspect

        Returns:
            List of column information dictionaries
        """
        try:
            async with self.db_manager._get_connection() as conn:
                cursor = await conn.execute(f"PRAGMA table_info({table_name})")
                rows = cursor.fetchall()

                columns = []
                for row in rows:
                    columns.append({
                        'cid': row[0],
                        'name': row[1],
                        'type': row[2],
                        'notnull': bool(row[3]),
                        'default': row[4],
                        'pk': bool(row[5])
                    })

                return columns

        except Exception as e:
            self.logger.error(f"Failed to get table info for {table_name}: {e}")
            return []

    async def get_index_info(self) -> List[Dict[str, Any]]:
        """
        Get information about all database indexes.

        Returns:
            List of index information dictionaries
        """
        try:
            async with self.db_manager._get_connection() as conn:
                cursor = await conn.execute("""
                    SELECT name, tbl_name, sql
                    FROM sqlite_master
                    WHERE type='index' AND name NOT LIKE 'sqlite_%'
                    ORDER BY name
                """)
                rows = cursor.fetchall()

                indexes = []
                for row in rows:
                    indexes.append({
                        'name': row[0],
                        'table': row[1],
                        'sql': row[2]
                    })

                return indexes

        except Exception as e:
            self.logger.error(f"Failed to get index info: {e}")
            return []

    async def backup_database(self, backup_path: str) -> bool:
        """
        Create a backup of the database before migration.

        Args:
            backup_path: Path where backup should be created

        Returns:
            True if backup successful
        """
        try:
            async with self.db_manager._get_connection() as conn:
                # Use SQLite backup API
                backup_conn = sqlite3.connect(backup_path)
                conn.conn.backup(backup_conn)
                backup_conn.close()

                self.logger.info(f"Database backup created: {backup_path}")
                return True

        except Exception as e:
            self.logger.error(f"Database backup failed: {e}")
            return False

    async def rollback_migration(self, target_version: int) -> bool:
        """
        Rollback database to previous version.

        Args:
            target_version: Version to rollback to

        Returns:
            True if rollback successful
        """
        try:
            current_version = await self.get_schema_version()

            if current_version <= target_version:
                self.logger.info(f"Database already at or below version {target_version}")
                return True

            # Support rollback from v2 to v1 and from v3 to v1 (skip v2)
            if current_version == 2 and target_version == 1:
                raise SchemaMigrationError("Rollback from version 2 has been removed.")
            elif current_version == 3 and target_version == 1:
                raise SchemaMigrationError("Rollback from version 3 has been removed.")
            else:
                self.logger.error(f"Rollback from v{current_version} to v{target_version} not supported")
                return False

        except Exception as e:
            self.logger.error(f"Migration rollback failed: {e}")
            return False

    async def optimize_database(self) -> bool:
        """
        Optimize database performance.

        Returns:
            True if optimization successful
        """
        try:
            async with self.db_manager._get_connection() as conn:
                # Update statistics for query planner
                await conn.execute("ANALYZE")

                # Vacuum database to reclaim space and reorganize
                await conn.execute("VACUUM")

                # Rebuild indexes
                await conn.execute("REINDEX")

                await conn.commit()

                self.logger.info("Database optimization completed")
                return True

        except Exception as e:
            self.logger.error(f"Database optimization failed: {e}")
            return False
