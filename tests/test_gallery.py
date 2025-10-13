"""
Simple test script for the Gallery Window implementation.
"""

import asyncio
import sys
import logging
from pathlib import Path

# Add the src directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer

# Import our components
from src.controllers.event_bus import EventBus
from src.models.settings_manager import SettingsManager
from src.models.database_manager import DatabaseManager
from src.models.screenshot_manager import ScreenshotManager
from src.views.gallery_window import GalleryWindow

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_gallery():
    """Test the gallery window functionality."""
    try:
        logger.info("Starting gallery test...")

        # Create Qt application
        app = QApplication([])

        # Create components
        event_bus = EventBus()
        settings_manager = SettingsManager()
        database_manager = DatabaseManager("test_gallery.db")
        screenshot_manager = ScreenshotManager(
            database_manager=database_manager,
            settings_manager=settings_manager,
            event_bus=event_bus
        )

        # Initialize components
        await settings_manager.initialize_database()
        await database_manager.initialize_database()
        await screenshot_manager.initialize()

        # Create gallery window
        gallery = GalleryWindow(
            event_bus=event_bus,
            screenshot_manager=screenshot_manager,
            database_manager=database_manager,
            settings_manager=settings_manager
        )

        # Initialize and show gallery
        if await gallery.initialize():
            await gallery.show_gallery()
            logger.info("Gallery window shown successfully")
        else:
            logger.error("Failed to initialize gallery")
            return False

        # Keep the app running for a bit to test
        def close_app():
            logger.info("Closing gallery test")
            gallery.close()
            app.quit()

        # Auto-close after 30 seconds for testing
        QTimer.singleShot(30000, close_app)

        # Run the Qt event loop
        app.exec()
        return True

    except Exception as e:
        logger.error(f"Gallery test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Main test function."""
    try:
        # Run the async test
        result = asyncio.run(test_gallery())
        if result:
            logger.info("Gallery test completed successfully")
        else:
            logger.error("Gallery test failed")
            sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Test interrupted by user")
    except Exception as e:
        logger.error(f"Test failed with exception: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
