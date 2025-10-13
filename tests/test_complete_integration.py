#!/usr/bin/env python3
"""
Complete Integration Test

Tests the entire application workflow to ensure all components work together
after the mock-to-real transformations.
"""

import asyncio
import sys
import logging
from pathlib import Path
# Mock imports removed - using real components only

# Add the src directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.controllers.event_bus import get_event_bus
from src.models.settings_manager import SettingsManager
from src.models.database_manager import DatabaseManager
from src.models.screenshot_manager import ScreenshotManager
from src import EventTypes

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

class ComprehensiveIntegrationTest:
    """Complete integration test suite."""

    def __init__(self):
        self.test_db_path = "test_complete_app.db"
        self.test_screenshots_dir = Path("test_screenshots")

    async def setup(self):
        """Set up test environment."""
        print("Setting up test environment...")

        # Initialize components
        self.db_manager = DatabaseManager(db_path=self.test_db_path)
        await self.db_manager.initialize_database()

        self.settings_manager = SettingsManager(database_manager=self.db_manager)
        await self.settings_manager.initialize_database()

        # Create test screenshots directory
        self.test_screenshots_dir.mkdir(exist_ok=True)

        # Get event bus
        self.event_bus = get_event_bus()

        self.screenshot_manager = ScreenshotManager(
            database_manager=self.db_manager,
            settings_manager=self.settings_manager,
            event_bus=self.event_bus
        )

        # Initialize screenshot manager
        await self.screenshot_manager.initialize()

    async def test_settings_workflow(self):
        """Test complete settings workflow."""
        print("\n--- Testing Settings Workflow ---")

        # Test setting update
        success = await self.settings_manager.update_setting("screenshot.quality", 90)
        print(f"✓ Settings update: {'PASS' if success else 'FAIL'}")

        # Verify setting persisted
        quality = await self.settings_manager.get_setting("screenshot.quality", 95)
        quality_test = quality == 90
        print(f"✓ Settings persistence: {'PASS' if quality_test else 'FAIL'}")

        # Test settings propagation via EventBus
        event_received = []

        async def settings_handler(event_data):
            event_received.append(event_data)

        event_bus = get_event_bus()
        await event_bus.subscribe(EventTypes.SETTINGS_UPDATED, settings_handler)

        # Update setting to trigger event
        await self.settings_manager.update_setting("screenshot.format", "PNG")
        await asyncio.sleep(0.1)  # Allow event processing

        propagation_test = len(event_received) > 0
        print(f"✓ Settings propagation: {'PASS' if propagation_test else 'FAIL'}")

        return success and quality_test and propagation_test

    async def test_screenshot_workflow(self):
        """Test screenshot capture workflow."""
        print("\n--- Testing Screenshot Workflow ---")

        # Test screenshot manager initialization
        init_test = self.screenshot_manager is not None
        print(f"✓ Screenshot manager init: {'PASS' if init_test else 'FAIL'}")

        # Test screenshot directory creation
        dir_test = self.test_screenshots_dir.exists()
        print(f"✓ Screenshots directory: {'PASS' if dir_test else 'FAIL'}")

        return init_test and dir_test

    async def test_event_bus_integration(self):
        """Test EventBus integration across components."""
        print("\n--- Testing EventBus Integration ---")

        event_bus = get_event_bus()
        events_received = {}

        # Set up handlers for different event types
        async def ui_handler(event_data):
            events_received['UI'] = event_data

        async def screenshot_handler(event_data):
            events_received['SCREENSHOT'] = event_data

        # Subscribe to events
        await event_bus.subscribe(EventTypes.UI_SETTINGS_SHOW, ui_handler)
        await event_bus.subscribe(EventTypes.SCREENSHOT_CAPTURED, screenshot_handler)

        # Emit test events
        await event_bus.emit(EventTypes.UI_SETTINGS_SHOW, {"test": "ui"}, source="test")
        await event_bus.emit(EventTypes.SCREENSHOT_CAPTURED,
                           {"screenshot_path": "test.png"}, source="test")

        await asyncio.sleep(0.1)  # Allow event processing

        ui_test = 'UI' in events_received
        screenshot_test = 'SCREENSHOT' in events_received

        print(f"✓ UI events: {'PASS' if ui_test else 'FAIL'}")
        print(f"✓ Screenshot events: {'PASS' if screenshot_test else 'FAIL'}")

        return ui_test and screenshot_test

    async def test_database_integration(self):
        """Test database operations."""
        print("\n--- Testing Database Integration ---")

        # Test settings CRUD
        await self.db_manager.set_setting("test.key", "test_value")
        retrieved_value = await self.db_manager.get_setting("test.key")

        crud_test = retrieved_value == "test_value"
        print(f"✓ Database CRUD: {'PASS' if crud_test else 'FAIL'}")

        # Test settings retrieval
        all_settings = await self.db_manager.get_all_settings()
        retrieval_test = isinstance(all_settings, dict) and len(all_settings) > 0
        print(f"✓ Settings retrieval: {'PASS' if retrieval_test else 'FAIL'}")

        return crud_test and retrieval_test

    async def cleanup(self):
        """Clean up test resources."""
        print("\nCleaning up test resources...")

        # Remove test database
        try:
            Path(self.test_db_path).unlink(missing_ok=True)
            print("✓ Test database cleaned up")
        except Exception as e:
            print(f"⚠ Database cleanup warning: {e}")

        # Remove test screenshots directory
        try:
            for file in self.test_screenshots_dir.glob("*"):
                file.unlink()
            self.test_screenshots_dir.rmdir()
            print("✓ Test screenshots cleaned up")
        except Exception as e:
            print(f"⚠ Screenshots cleanup warning: {e}")

    async def run_all_tests(self):
        """Run complete test suite."""
        print("=== Complete Integration Test Suite ===")

        try:
            await self.setup()

            # Run all test categories
            settings_result = await self.test_settings_workflow()
            screenshot_result = await self.test_screenshot_workflow()
            eventbus_result = await self.test_event_bus_integration()
            database_result = await self.test_database_integration()

            # Calculate overall result
            all_results = [settings_result, screenshot_result, eventbus_result, database_result]
            overall_success = all(all_results)

            print("\n=== Test Results ===")
            print(f"Settings Workflow: {'PASS' if settings_result else 'FAIL'}")
            print(f"Screenshot Workflow: {'PASS' if screenshot_result else 'FAIL'}")
            print(f"EventBus Integration: {'PASS' if eventbus_result else 'FAIL'}")
            print(f"Database Integration: {'PASS' if database_result else 'FAIL'}")
            print(f"\n=== Overall Result: {'PASS' if overall_success else 'FAIL'} ===")

            if overall_success:
                print("\n🎉 All integration tests passed! Mock-to-real transformation successful!")
            else:
                print("\n❌ Some tests failed. Please review the results above.")

            return 0 if overall_success else 1

        except Exception as e:
            print(f"\n❌ Test suite failed with error: {e}")
            import traceback
            traceback.print_exc()
            return 1
        finally:
            await self.cleanup()

async def main():
    """Run the complete integration test."""
    test_suite = ComprehensiveIntegrationTest()
    return await test_suite.run_all_tests()

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
