"""
Preset Migration Utility

This module provides functionality to migrate presets from the database
to the new JSON file-based storage system.
"""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from .database_manager import DatabaseManager
from .preset_manager import PresetManager
from .. import get_app_data_dir

logger = logging.getLogger(__name__)


class PresetMigration:
    """Handles migration of presets from database to file system."""

    def __init__(self, database_manager: DatabaseManager, preset_manager: Optional[PresetManager] = None):
        """
        Initialize PresetMigration.

        Args:
            database_manager: DatabaseManager instance
            preset_manager: PresetManager instance (will create if None)
        """
        self.database_manager = database_manager
        self.preset_manager = preset_manager or PresetManager()

    async def migrate_presets(self) -> dict:
        """
        Migrate all presets from database to JSON files.

        Returns:
            Migration results dictionary with counts and errors
        """
        results = {
            'total_found': 0,
            'successfully_migrated': 0,
            'failed': 0,
            'skipped_builtin': 0,
            'errors': []
        }

        try:
            # Initialize preset manager
            await self.preset_manager.initialize()

            # Note: Database preset functionality has been removed.
            # This migration is now a no-op since presets are stored in files.
            # The preset manager will automatically initialize built-in presets.
            logger.info("Database preset migration no longer applicable - presets are now file-based")
            results['total_found'] = 0
            results['successfully_migrated'] = 0

        except Exception as e:
            error_msg = f"Migration initialization failed: {e}"
            results['errors'].append(error_msg)
            logger.error(error_msg)

        return results

    async def backup_database_presets(self, backup_path: Optional[str] = None) -> bool:
        """
        Create a backup of database presets before migration.

        Args:
            backup_path: Custom backup file path (auto-generated if None)

        Returns:
            True if backup successful
        """
        try:
            final_backup_path: str
            if backup_path is None:
                backup_dir = Path(get_app_data_dir()) / "backups"
                backup_dir.mkdir(exist_ok=True)
                final_backup_path = str(backup_dir / "presets_backup.json")
            else:
                final_backup_path = backup_path

            # Initialize preset manager
            await self.preset_manager.initialize()

            # Note: Database preset functionality has been removed.
            # Creating empty backup file as placeholder.
            backup_data = {
                'backup_timestamp': datetime.now().isoformat(),
                'source': 'database (removed)',
                'version': '1.0',
                'presets': [],
                'note': 'Database preset functionality removed - presets are now file-based'
            }

            # Save backup
            with open(final_backup_path, 'w', encoding='utf-8') as f:
                json.dump(backup_data, f, indent=2, ensure_ascii=False)

            logger.info(f"Created placeholder backup file at {final_backup_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to create preset backup: {e}")
            return False

    async def verify_migration(self) -> dict:
        """
        Verify that migration was successful by comparing database and file presets.

        Returns:
            Verification results dictionary
        """
        results = {
            'database_count': 0,
            'file_count': 0,
            'user_presets_db': 0,
            'user_presets_files': 0,
            'missing_in_files': [],
            'extra_in_files': [],
            'verification_passed': False
        }

        try:
            # Initialize preset manager
            await self.preset_manager.initialize()

            # Note: Database preset functionality has been removed.
            # Verification now just ensures file-based presets are working.
            results['database_count'] = 0
            results['user_presets_db'] = 0

            # Get file presets
            file_presets = await self.preset_manager.get_presets(limit=1000)
            results['file_count'] = len(file_presets)

            # Filter user presets from files
            file_user_presets = [p for p in file_presets if not p.is_builtin]
            results['user_presets_files'] = len(file_user_presets)

            # Since database is empty, no missing presets
            results['missing_in_files'] = []
            results['extra_in_files'] = []

            # Verification passes if all user presets are migrated
            results['verification_passed'] = (
                len(results['missing_in_files']) == 0 and
                results['user_presets_db'] == results['user_presets_files']
            )

            logger.info(f"Verification: DB user presets: {results['user_presets_db']}, "
                       f"File user presets: {results['user_presets_files']}, "
                       f"Missing: {len(results['missing_in_files'])}, "
                       f"Passed: {results['verification_passed']}")

        except Exception as e:
            logger.error(f"Migration verification failed: {e}")

        return results


async def run_preset_migration(db_path: Optional[str] = None) -> dict:
    """
    Convenience function to run complete preset migration.

    Args:
        db_path: Database path (uses default if None)

    Returns:
        Migration results dictionary
    """
    try:
        # Initialize database manager
        db_manager = DatabaseManager(db_path)
        await db_manager.initialize_database()

        # Initialize preset manager
        preset_manager = PresetManager()

        # Create migration instance
        migration = PresetMigration(db_manager, preset_manager)

        # Create backup first
        logger.info("Creating backup of existing presets...")
        backup_success = await migration.backup_database_presets()
        if not backup_success:
            logger.warning("Backup failed, but continuing with migration")

        # Run migration
        logger.info("Starting preset migration...")
        results = await migration.migrate_presets()

        # Verify migration
        logger.info("Verifying migration...")
        verification = await migration.verify_migration()
        results['verification'] = verification

        # Cleanup
        await db_manager.close()
        await preset_manager.close()

        return results

    except Exception as e:
        logger.error(f"Preset migration failed: {e}")
        return {
            'total_found': 0,
            'successfully_migrated': 0,
            'failed': 0,
            'errors': [str(e)]
        }


if __name__ == "__main__":
    # Allow running migration as standalone script
    async def main():
        logging.basicConfig(level=logging.INFO)
        results = await run_preset_migration()
        print(f"Migration Results: {results}")

    asyncio.run(main())
