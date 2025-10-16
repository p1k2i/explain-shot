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
        self.target_version = 2   # Performance optimization version

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
                return await self._migrate_to_v2_performance()
            else:
                self.logger.warning(f"Unknown migration version: {target_version}")
                return False

        except Exception as e:
            self.logger.error(f"Migration to version {target_version} failed: {e}")
            return False

    async def _migrate_to_v2_performance(self) -> bool:
        """
        Migrate to version 2: Performance optimization schema.

        Returns:
            True if migration successful
        """
        try:
            async with self.db_manager._get_connection() as conn:
                # Create cached_responses table
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS cached_responses (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        prompt_hash TEXT NOT NULL UNIQUE,
                        original_prompt TEXT NOT NULL,
                        response TEXT NOT NULL,
                        model_name TEXT NOT NULL,
                        cached_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        last_accessed DATETIME DEFAULT CURRENT_TIMESTAMP,
                        access_count INTEGER DEFAULT 1,
                        response_size INTEGER,
                        processing_time REAL,
                        ttl_expires_at DATETIME,
                        session_id TEXT,
                        metadata TEXT DEFAULT '{}'
                    )
                """)

                # Create performance_metrics table
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS performance_metrics (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        metric_type TEXT NOT NULL,
                        component TEXT NOT NULL,
                        value REAL NOT NULL,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                        session_id TEXT,
                        metadata TEXT DEFAULT '{}'
                    )
                """)

                # Create storage_cleanup_log table
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS storage_cleanup_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        cleanup_type TEXT NOT NULL,
                        files_removed INTEGER DEFAULT 0,
                        bytes_freed INTEGER DEFAULT 0,
                        duration_seconds REAL,
                        triggered_by TEXT,
                        cleanup_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        details TEXT DEFAULT '{}'
                    )
                """)

                # Create indexes for cached_responses
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_cached_responses_hash ON cached_responses(prompt_hash)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_cached_responses_model ON cached_responses(model_name)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_cached_responses_accessed ON cached_responses(last_accessed)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_cached_responses_expires ON cached_responses(ttl_expires_at)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_cached_responses_session ON cached_responses(session_id)")

                # Create indexes for performance_metrics
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_performance_metrics_type ON performance_metrics(metric_type)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_performance_metrics_component ON performance_metrics(component)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_performance_metrics_timestamp ON performance_metrics(timestamp)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_performance_metrics_session ON performance_metrics(session_id)")

                # Create indexes for storage_cleanup_log
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_storage_cleanup_type ON storage_cleanup_log(cleanup_type)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_storage_cleanup_timestamp ON storage_cleanup_log(cleanup_at)")

                # Add performance indexes to existing tables
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_screenshots_file_size ON screenshots(file_size)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_screenshots_filename ON screenshots(filename)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_history_timestamp ON chat_history(timestamp)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_history_model ON chat_history(model_name)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_presets_category ON presets(category)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_presets_favorite ON presets(is_favorite)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_settings_updated ON settings(updated_at)")

                # Add partial indexes for better performance
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_cached_responses_valid ON cached_responses(prompt_hash) WHERE ttl_expires_at IS NULL OR ttl_expires_at > datetime('now')")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_presets_active ON presets(usage_count DESC) WHERE is_builtin = 0")

                await conn.commit()

                # Record migration
                await self._set_schema_version(2, "Performance optimization schema with caching, metrics, and enhanced indexes")

                self.logger.info("Successfully migrated to performance optimization schema (v2)")
                return True

        except Exception as e:
            self.logger.error(f"Failed to migrate to performance schema: {e}")
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
                # Check required tables
                required_tables = [
                    'screenshots', 'chat_history', 'presets', 'settings',
                    'schema_version'
                ]

                if validation_results['version'] >= 2:
                    required_tables.extend([
                        'cached_responses', 'performance_metrics', 'storage_cleanup_log'
                    ])

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

                # Check required indexes
                required_indexes = [
                    'idx_screenshots_timestamp',
                    'idx_chat_screenshot_id',
                    'idx_presets_usage'
                ]

                if validation_results['version'] >= 2:
                    required_indexes.extend([
                        'idx_cached_responses_hash',
                        'idx_performance_metrics_type',
                        'idx_storage_cleanup_type'
                    ])

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

            # For now, only support rollback from v2 to v1
            if current_version == 2 and target_version == 1:
                return await self._rollback_from_v2()
            else:
                self.logger.error(f"Rollback from v{current_version} to v{target_version} not supported")
                return False

        except Exception as e:
            self.logger.error(f"Migration rollback failed: {e}")
            return False

    async def _rollback_from_v2(self) -> bool:
        """
        Rollback from performance optimization schema (v2) to base schema (v1).

        Returns:
            True if rollback successful
        """
        try:
            async with self.db_manager._get_connection() as conn:
                # Drop performance optimization tables
                await conn.execute("DROP TABLE IF EXISTS cached_responses")
                await conn.execute("DROP TABLE IF EXISTS performance_metrics")
                await conn.execute("DROP TABLE IF EXISTS storage_cleanup_log")

                # Drop performance indexes (keep base indexes)
                performance_indexes = [
                    'idx_screenshots_file_size',
                    'idx_screenshots_filename',
                    'idx_chat_history_timestamp',
                    'idx_chat_history_model',
                    'idx_presets_category',
                    'idx_presets_favorite',
                    'idx_settings_updated',
                    'idx_presets_active'
                ]

                for index in performance_indexes:
                    await conn.execute(f"DROP INDEX IF EXISTS {index}")

                await conn.commit()

                # Record rollback
                await self._set_schema_version(1, "Rollback from performance optimization schema")

                self.logger.info("Successfully rolled back to base schema (v1)")
                return True

        except Exception as e:
            self.logger.error(f"Failed to rollback from v2: {e}")
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
