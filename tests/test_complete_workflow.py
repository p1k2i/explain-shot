#!/usr/bin/env python3
"""
Test the complete hotkey-to-overlay workflow including UIManager.
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add project root to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from PyQt6.QtWidgets import QApplication
from src.controllers.event_bus import EventBus
from src.controllers.main_controller import MainController
from src.models.settings_manager import SettingsManager
from src.views.ui_manager import UIManager
from src import EventTypes

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


async def test_complete_workflow():
    """Test complete hotkey-to-overlay workflow with UI components."""
    try:
        logger.info("🚀 Testing complete hotkey-to-overlay workflow...")

        # Create QApplication
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)

        # Initialize components
        event_bus = EventBus()
        settings_manager = SettingsManager()
        await settings_manager.initialize_database()

        # Initialize UIManager
        ui_manager = UIManager(
            event_bus=event_bus,
            settings_manager=settings_manager
        )
        ui_init_success = await ui_manager.initialize()
        if not ui_init_success:
            logger.warning("UIManager initialization failed, skipping UI tests")
            # Cleanup
            await event_bus.shutdown()
            return

        # Initialize MainController with UIManager
        main_controller = MainController(
            event_bus=event_bus,
            settings_manager=settings_manager,
            ui_manager=ui_manager
        )
        await main_controller.initialize()

        logger.info("✅ All components initialized successfully")

        # Test 1: Direct hotkey event emission
        logger.info("🧪 Test 1: Emitting hotkey.overlay_toggle event...")
        await event_bus.emit(
            EventTypes.HOTKEY_OVERLAY_TOGGLE,
            {
                "combination": "Ctrl+Shift+O",
                "timestamp": asyncio.get_event_loop().time(),
                "source": "workflow_test"
            }
        )

        # Wait for event processing
        await asyncio.sleep(1)

        # Check if overlay is visible
        is_overlay_visible = False
        if hasattr(ui_manager, 'overlay_manager') and ui_manager.overlay_manager:
            is_overlay_visible = ui_manager.overlay_manager.is_overlay_visible()

        logger.info(f"📊 Overlay visible after hotkey: {is_overlay_visible}")

        if is_overlay_visible:
            logger.info("✅ Test 1: PASSED - Overlay shown via hotkey")

            # Test 2: Hide overlay
            logger.info("🧪 Test 2: Testing overlay toggle (hide)...")
            await event_bus.emit(
                EventTypes.HOTKEY_OVERLAY_TOGGLE,
                {
                    "combination": "Ctrl+Shift+O",
                    "timestamp": asyncio.get_event_loop().time(),
                    "source": "workflow_test_hide"
                }
            )

            await asyncio.sleep(1)

            is_overlay_visible_after_hide = False
            if hasattr(ui_manager, 'overlay_manager') and ui_manager.overlay_manager:
                is_overlay_visible_after_hide = ui_manager.overlay_manager.is_overlay_visible()
            logger.info(f"📊 Overlay visible after second hotkey: {is_overlay_visible_after_hide}")

            if not is_overlay_visible_after_hide:
                logger.info("✅ Test 2: PASSED - Overlay hidden via hotkey")
            else:
                logger.info("❌ Test 2: FAILED - Overlay still visible")

        else:
            logger.info("❌ Test 1: FAILED - Overlay not shown via hotkey")

        # Cleanup
        await main_controller.shutdown()
        await ui_manager.shutdown()
        await event_bus.shutdown()

        logger.info("🎉 Complete workflow test completed")

    except Exception as e:
        logger.error(f"❌ Workflow test failed: {e}")
        logger.debug("Exception details:", exc_info=True)


if __name__ == "__main__":
    asyncio.run(test_complete_workflow())
