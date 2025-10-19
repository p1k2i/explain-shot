"""
Database Migration Tool.

Run database schema migrations for performance optimization.
Usage: python -m src.models.migrate_db
"""

import asyncio
import logging
import sys
from pathlib import Path

from src import DEFAULT_DATABASE_NAME

# Setup basic logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

async def run_migration():
    """Run the database migration process."""
    try:
        from src.models.database_manager import DatabaseManager
        from src.models.database_schema_migration import DatabaseSchemaMigration

        # Initialize database manager
        db_path = DEFAULT_DATABASE_NAME
        db_manager = DatabaseManager(db_path, logger)
        migration_manager = DatabaseSchemaMigration(db_manager, logger)

        # Check current version
        current_version = await migration_manager.get_schema_version()
        logger.info(f"Current schema version: {current_version}")

        # Migrate to latest
        logger.info("Starting migration to performance optimization schema...")
        success = await migration_manager.migrate_to_latest()

        if success:
            # Validate migration
            validation = await migration_manager.validate_schema()
            if validation['valid']:
                logger.info("✓ Migration completed successfully")
                logger.info(f"✓ New schema version: {validation['version']}")
            else:
                logger.error("✗ Migration validation failed")
                for error in validation['errors']:
                    logger.error(f"  - {error}")
        else:
            logger.error("✗ Migration failed")

        return success

    except ImportError as e:
        logger.error(f"Import error: {e}")
        logger.error("Make sure you're running from the project root directory")
        return False
    except Exception as e:
        logger.error(f"Migration error: {e}")
        return False

if __name__ == "__main__":
    success = asyncio.run(run_migration())
    sys.exit(0 if success else 1)
