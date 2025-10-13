"""
Integration test for the complete overlay system.

Tests the full workflow from hotkey trigger to overlay display
and interaction handling.
"""

import asyncio
import logging
import sys
from pathlib import Path
from PyQt6.QtWidgets import QApplication

# Add project root to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import components
from src.controllers.event_bus import EventBus
from src.models.settings_manager import SettingsManager
from src.models.database_manager import DatabaseManager
from src.models.screenshot_manager import ScreenshotManager
from src.views.ui_manager import UIManager
from src.controllers.main_controller import MainController
from src import EventTypes

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


class IntegrationTest:
    """Integration test for overlay system."""

    def __init__(self):
        self.app = None
        self.event_bus = None
        self.settings_manager = None
        self.database_manager = None
        self.screenshot_manager = None
        self.ui_manager = None
        self.main_controller = None

    async def initialize(self):
        """Initialize all components."""
        try:
            logger.info("🔧 Initializing integration test components...")

            # Create QApplication
            self.app = QApplication.instance()
            if self.app is None:
                self.app = QApplication(sys.argv)

            # Initialize EventBus
            self.event_bus = EventBus()

            # Initialize SettingsManager
            self.settings_manager = SettingsManager()
            await self.settings_manager.initialize_database()

            # Initialize DatabaseManager
            self.database_manager = DatabaseManager()
            await self.database_manager.initialize_database()

            # Initialize ScreenshotManager
            self.screenshot_manager = ScreenshotManager(
                database_manager=self.database_manager,
                settings_manager=self.settings_manager,
                event_bus=self.event_bus
            )
            await self.screenshot_manager.initialize()

            # Initialize UIManager with screenshot manager
            self.ui_manager = UIManager(
                event_bus=self.event_bus,
                settings_manager=self.settings_manager,
                screenshot_manager=self.screenshot_manager
            )
            await self.ui_manager.initialize()

            # Initialize MainController
            self.main_controller = MainController(
                event_bus=self.event_bus,
                settings_manager=self.settings_manager,
                database_manager=self.database_manager,
                screenshot_manager=self.screenshot_manager,
                ui_manager=self.ui_manager
            )
            await self.main_controller.initialize()

            logger.info("✅ All components initialized successfully")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to initialize: {e}")
            return False

    async def test_hotkey_to_overlay_workflow(self):
        """Test the complete workflow from hotkey to overlay display."""
        try:
            logger.info("🎯 Testing hotkey to overlay workflow...")

            # Subscribe to overlay events to track the flow
            await self.event_bus.subscribe("overlay.shown", self._on_overlay_shown)
            await self.event_bus.subscribe("overlay.item_selected", self._on_item_selected)

            # Simulate hotkey trigger
            logger.info("🔥 Simulating overlay hotkey trigger...")
            await self.event_bus.emit(
                EventTypes.HOTKEY_OVERLAY_TOGGLE,
                {
                    "combination": "Ctrl+Shift+O",
                    "timestamp": asyncio.get_event_loop().time(),
                    "source": "integration_test"
                },
                source="IntegrationTest"
            )

            # Wait for processing
            await asyncio.sleep(1)

            # Check if overlay is visible
            if self.ui_manager and self.ui_manager.overlay_manager:
                is_visible = self.ui_manager.overlay_manager.is_overlay_visible()
                if is_visible:
                    logger.info("✅ Overlay is visible after hotkey trigger")

                    # Wait a bit then hide it
                    await asyncio.sleep(2)
                    await self.ui_manager.hide_overlay(reason="test_completed")

                    return True
                else:
                    logger.error("❌ Overlay not visible after hotkey trigger")
                    return False
            else:
                logger.error("❌ UI manager or overlay manager not available")
                return False

        except Exception as e:
            logger.error(f"❌ Workflow test failed: {e}")
            return False

    async def test_mock_interactions(self):
        """Test mock interactions with overlay items."""
        try:
            logger.info("🖱️ Testing overlay interactions...")

            # Show overlay first
            success = await self.ui_manager.show_overlay()
            if not success:
                logger.error("❌ Failed to show overlay for interaction test")
                return False

            # Wait a moment
            await asyncio.sleep(1)

            # Simulate clicking on "Open Settings" function
            logger.info("🔧 Simulating settings function selection...")
            await self.event_bus.emit(
                "overlay.item_selected",
                {
                    "type": "function",
                    "data": {
                        "id": "settings",
                        "action": "open_settings",
                        "title": "📱 Open Settings"
                    }
                },
                source="IntegrationTest"
            )

            await asyncio.sleep(0.5)

            # Show overlay again and simulate screenshot selection
            await self.ui_manager.show_overlay()
            await asyncio.sleep(1)

            logger.info("🖼️ Simulating screenshot selection...")
            await self.event_bus.emit(
                "overlay.item_selected",
                {
                    "type": "screenshot",
                    "data": {
                        "id": "mock_1",
                        "filename": "screenshot_001.png"
                    }
                },
                source="IntegrationTest"
            )

            await asyncio.sleep(0.5)

            logger.info("✅ Interaction test completed")
            return True

        except Exception as e:
            logger.error(f"❌ Interaction test failed: {e}")
            return False

    async def test_screenshot_integration(self):
        """Test real screenshot capture and overlay refresh."""
        try:
            logger.info("📸 Testing screenshot integration...")

            # Capture a screenshot
            logger.info("📷 Capturing test screenshot...")
            result = await self.screenshot_manager.capture_screenshot()

            if result.success:
                logger.info(f"✅ Screenshot captured: {result.metadata.filename}")

                # Show overlay to see if it includes the new screenshot
                await self.ui_manager.show_overlay()
                await asyncio.sleep(2)
                await self.ui_manager.hide_overlay(reason="test_completed")

                return True
            else:
                logger.error(f"❌ Screenshot capture failed: {result.error_message}")
                return False

        except Exception as e:
            logger.error(f"❌ Screenshot integration test failed: {e}")
            return False

    async def _on_overlay_shown(self, event_data):
        """Handle overlay shown event."""
        data = event_data.data or {}
        position = data.get("position", "unknown")
        count = data.get("screenshot_count", 0)
        logger.info(f"📢 Overlay shown at {position} with {count} screenshots")

    async def _on_item_selected(self, event_data):
        """Handle item selection event."""
        data = event_data.data or {}
        item_type = data.get("type", "unknown")
        item_data = data.get("data", {})
        logger.info(f"📢 Item selected: {item_type} - {item_data}")

    async def run_all_tests(self):
        """Run all integration tests."""
        try:
            logger.info("🚀 Starting integration tests...")

            # Initialize
            if not await self.initialize():
                return False

            # Test hotkey workflow
            if not await self.test_hotkey_to_overlay_workflow():
                return False

            # Test interactions
            if not await self.test_mock_interactions():
                return False

            # Test screenshot integration
            if not await self.test_screenshot_integration():
                return False

            logger.info("🎉 All integration tests passed!")
            return True

        except Exception as e:
            logger.error(f"❌ Integration test suite failed: {e}")
            return False
        finally:
            # Cleanup
            await self.cleanup()

    async def cleanup(self):
        """Clean up resources."""
        try:
            logger.info("🧹 Cleaning up...")

            if self.main_controller:
                await self.main_controller.shutdown()

            if self.ui_manager:
                await self.ui_manager.shutdown()

            if self.screenshot_manager:
                await self.screenshot_manager.shutdown()

            if self.event_bus:
                await self.event_bus.shutdown()

            logger.info("✅ Cleanup completed")

        except Exception as e:
            logger.error(f"❌ Cleanup failed: {e}")


async def main():
    """Main test function."""
    test = IntegrationTest()

    try:
        success = await test.run_all_tests()

        if success:
            logger.info("🎊 All integration tests passed!")
            sys.exit(0)
        else:
            logger.error("💥 Some tests failed!")
            sys.exit(1)

    except KeyboardInterrupt:
        logger.info("Test interrupted by user")
        await test.cleanup()
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        await test.cleanup()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
