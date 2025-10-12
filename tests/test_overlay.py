"""
Test script for Overlay Window functionality.

This script tests the overlay window independently to verify it works
before full integration into the main application.
"""

import asyncio
import logging
import sys
from pathlib import Path
from PyQt6.QtWidgets import QApplication

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Import our components
from src.controllers.event_bus import EventBus
from src.models.settings_manager import SettingsManager
from src.views.ui_manager import UIManager

# Setup basic logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


class OverlayTest:
    """Test class for overlay window functionality."""

    def __init__(self):
        self.app = None
        self.event_bus = None
        self.settings_manager = None
        self.ui_manager = None
        self.timer = None

    async def initialize(self):
        """Initialize test components."""
        try:
            logger.info("Initializing overlay test...")

            # Create QApplication
            self.app = QApplication.instance()
            if self.app is None:
                self.app = QApplication(sys.argv)

            # Initialize EventBus
            self.event_bus = EventBus()

            # Initialize minimal SettingsManager
            self.settings_manager = SettingsManager()
            await self.settings_manager.initialize_database()

            # Initialize UIManager
            self.ui_manager = UIManager(
                event_bus=self.event_bus,
                settings_manager=self.settings_manager,
                screenshot_manager=None  # No screenshot manager for this test
            )

            await self.ui_manager.initialize()

            logger.info("Overlay test initialization complete")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize test: {e}")
            return False

    async def test_overlay_show_hide(self):
        """Test showing and hiding the overlay."""
        try:
            logger.info("Testing overlay show/hide...")

            # Show overlay
            logger.info("Showing overlay...")
            assert self.ui_manager is not None, "UIManager not initialized"
            success = await self.ui_manager.show_overlay()
            if success:
                logger.info("✅ Overlay shown successfully")
            else:
                logger.error("❌ Failed to show overlay")
                return False

            # Process events for 3 seconds to allow GUI to update
            logger.info("Processing events for 3 seconds...")
            assert self.app is not None, "QApplication not initialized"
            for _ in range(30):  # 30 * 0.1 = 3 seconds
                self.app.processEvents()
                await asyncio.sleep(0.1)

            # Hide overlay
            logger.info("Hiding overlay...")
            assert self.ui_manager is not None, "UIManager not initialized"
            success = await self.ui_manager.hide_overlay(reason="test_completed")
            if success:
                logger.info("✅ Overlay hidden successfully")
            else:
                logger.error("❌ Failed to hide overlay")
                return False

            return True

        except Exception as e:
            logger.error(f"Error in overlay test: {e}")
            return False

    async def test_overlay_with_hotkey_simulation(self):
        """Test overlay by simulating hotkey trigger."""
        try:
            logger.info("Testing overlay with hotkey simulation...")

            assert self.event_bus is not None, "EventBus not initialized"

            # Simulate hotkey trigger
            logger.info("Simulating overlay hotkey trigger...")
            await self.event_bus.emit(
                "hotkey.overlay_toggle",
                {
                    'combination': 'ctrl+shift+o',
                    'timestamp': asyncio.get_event_loop().time(),
                    'trigger_source': 'test'
                },
                source="test"
            )

            # Wait for processing
            logger.info("Waiting for overlay to be triggered...")
            await asyncio.sleep(2)

            # Check if overlay is visible
            if self.ui_manager and hasattr(self.ui_manager, 'overlay_manager') and self.ui_manager.overlay_manager:
                is_visible = self.ui_manager.overlay_manager.is_overlay_visible()
                logger.info(f"Overlay visible after hotkey: {is_visible}")
                if is_visible:
                    logger.info("✅ Overlay shown successfully via hotkey")
                else:
                    logger.error("❌ Overlay not visible after hotkey trigger")
                    return False
            else:
                logger.warning("Cannot check overlay visibility - UI manager not available")

            # Wait a bit more to see if it stays visible
            await asyncio.sleep(3)

            # Simulate another hotkey to hide
            logger.info("Simulating second hotkey to hide overlay...")
            await self.event_bus.emit(
                "hotkey.overlay_toggle",
                {
                    'combination': 'ctrl+shift+o',
                    'timestamp': asyncio.get_event_loop().time(),
                    'trigger_source': 'test'
                },
                source="test"
            )

            # Wait for hide
            await asyncio.sleep(1)

            logger.info("✅ Hotkey simulation test completed")
            return True

        except Exception as e:
            logger.error(f"Error in hotkey simulation test: {e}")
            return False

    async def _on_overlay_shown(self, event_data):
        """Handle overlay shown event."""
        logger.info(f"📢 Overlay shown event received: {event_data.data}")

    async def _on_overlay_hidden(self, event_data):
        """Handle overlay hidden event."""
        logger.info(f"📢 Overlay hidden event received: {event_data.data}")

    async def _on_item_selected(self, event_data):
        """Handle item selection event."""
        logger.info(f"📢 Item selected event received: {event_data.data}")

    async def run_all_tests(self):
        """Run all overlay tests."""
        try:
            logger.info("🚀 Starting overlay window tests...")

            # Initialize
            if not await self.initialize():
                logger.error("❌ Initialization failed")
                return False

            # Test basic show/hide
            if not await self.test_overlay_show_hide():
                logger.error("❌ Show/hide test failed")
                return False

            # Test events
            if not await self.test_overlay_with_hotkey_simulation():
                logger.error("❌ Hotkey simulation test failed")
                return False

            logger.info("✅ All overlay tests passed!")
            return True

        except Exception as e:
            logger.error(f"❌ Test suite failed: {e}")
            return False
        finally:
            # Cleanup
            if self.ui_manager:
                await self.ui_manager.shutdown()
            if self.event_bus:
                await self.event_bus.shutdown()


async def main():
    """Main test function."""
    test = OverlayTest()

    try:
        # Run tests
        success = await test.run_all_tests()

        if success:
            logger.info("🎉 All tests completed successfully!")
            sys.exit(0)
        else:
            logger.error("💥 Some tests failed!")
            sys.exit(1)

    except KeyboardInterrupt:
        logger.info("Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    # Run the test
    asyncio.run(main())
