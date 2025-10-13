"""
Integration test to verify gallery works with the main application structure.
This tests the EventBus integration and UI Manager coordination.
"""

import asyncio
import sys
import logging
from pathlib import Path

# Add the src directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer

# Import application components
from src.controllers.event_bus import EventBus
from src.controllers.main_controller import MainController
from src.models.settings_manager import SettingsManager
from src.models.database_manager import DatabaseManager
from src.models.screenshot_manager import ScreenshotManager
from src.views.ui_manager import UIManager
from src import EventTypes

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_gallery_integration():
    """Test gallery integration with the main application architecture."""
    try:
        logger.info("Starting gallery integration test...")

        # Create Qt application
        app = QApplication([])

        # Create core components following main.py pattern
        event_bus = EventBus()
        settings_manager = SettingsManager()
        database_manager = DatabaseManager("test_integration.db")
        screenshot_manager = ScreenshotManager(
            database_manager=database_manager,
            settings_manager=settings_manager,
            event_bus=event_bus
        )

        # Create UI Manager with all dependencies
        ui_manager = UIManager(
            event_bus=event_bus,
            settings_manager=settings_manager,
            screenshot_manager=screenshot_manager,
            database_manager=database_manager
        )

        # Create Main Controller
        main_controller = MainController(
            event_bus=event_bus,
            settings_manager=settings_manager,
            database_manager=database_manager,
            screenshot_manager=screenshot_manager,
            ui_manager=ui_manager
        )

        # Initialize components in order
        logger.info("Initializing components...")
        await settings_manager.initialize_database()
        await database_manager.initialize_database()
        await screenshot_manager.initialize()
        await ui_manager.initialize()
        await main_controller.initialize()

        logger.info("All components initialized successfully")

        # Test gallery triggering via EventBus (simulating tray menu click)
        logger.info("Testing gallery trigger via EventBus...")
        await event_bus.emit(
            EventTypes.TRAY_GALLERY_REQUESTED,
            {"screenshot_id": None},
            source="IntegrationTest"
        )

        # Give it a moment to process
        await asyncio.sleep(0.1)

        # Test gallery trigger with pre-selected screenshot
        logger.info("Testing gallery with pre-selected screenshot...")
        await event_bus.emit(
            EventTypes.UI_GALLERY_SHOW,
            {"screenshot_id": 1},
            source="IntegrationTest"
        )

        await asyncio.sleep(0.1)

        # Test EventBus gallery events
        logger.info("Testing gallery event propagation...")

        def close_app():
            logger.info("Integration test completed, closing application...")
            try:
                asyncio.create_task(ui_manager.shutdown())
            except Exception as e:
                logger.warning(f"Shutdown error: {e}")
            app.quit()

        # Run for 15 seconds to allow manual interaction
        QTimer.singleShot(15000, close_app)

        logger.info("Gallery integration test running... (15 seconds)")
        logger.info("You should see the gallery window open with sample data")

        # Run the Qt event loop
        app.exec()

        logger.info("Integration test completed successfully")
        return True

    except Exception as e:
        logger.error(f"Integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Main integration test function."""
    try:
        logger.info("=== Gallery Integration Test ===")

        # Run the async test
        result = asyncio.run(test_gallery_integration())
        if result:
            logger.info("Gallery integration test completed successfully")
        else:
            logger.error("Gallery integration test failed")
            sys.exit(1)

    except KeyboardInterrupt:
        logger.info("Integration test interrupted by user")
    except Exception as e:
        logger.error(f"Integration test failed with exception: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
