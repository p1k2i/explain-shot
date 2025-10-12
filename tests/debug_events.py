"""
Debug test to trace event flow from hotkey to overlay display.
"""

import asyncio
import logging
import sys
from pathlib import Path
from PyQt6.QtWidgets import QApplication

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.controllers.event_bus import EventBus
from src.models.settings_manager import SettingsManager
from src.views.ui_manager import UIManager
from src.controllers.main_controller import MainController
from src import EventTypes

# Setup detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


async def debug_event_flow():
    """Debug the event flow from hotkey to overlay."""
    try:
        logger.info("🔍 Starting event flow debug...")

        # Create QApplication
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)

        # Initialize EventBus
        event_bus = EventBus()

        # Initialize SettingsManager
        settings_manager = SettingsManager()
        await settings_manager.initialize_database()

        # Initialize UIManager
        ui_manager = UIManager(
            event_bus=event_bus,
            settings_manager=settings_manager
        )
        await ui_manager.initialize()

        # Initialize MainController
        main_controller = MainController(
            event_bus=event_bus,
            settings_manager=settings_manager,
            ui_manager=ui_manager
        )
        await main_controller.initialize()

        # Add debug subscribers to trace events
        await event_bus.subscribe("ui.overlay.show", debug_ui_overlay_show, priority=200)
        await event_bus.subscribe("overlay.shown", debug_overlay_shown, priority=200)
        await event_bus.subscribe("hotkey.overlay_toggle", debug_hotkey_overlay, priority=200)

        logger.info("🎯 All components initialized, testing event flow...")

        # Test 1: Direct UI manager call
        logger.info("📞 Test 1: Direct UI manager show_overlay() call")
        success = await ui_manager.show_overlay()
        logger.info(f"   Result: {success}")
        await asyncio.sleep(1)
        await ui_manager.hide_overlay()
        await asyncio.sleep(1)

        # Test 2: UI event emission
        logger.info("📡 Test 2: Emit UI_OVERLAY_SHOW event")
        await event_bus.emit(EventTypes.UI_OVERLAY_SHOW, {"test": "direct_ui_event"})
        await asyncio.sleep(2)

        # Test 3: Hotkey event emission
        logger.info("🔥 Test 3: Emit HOTKEY_OVERLAY_TOGGLE event")
        await event_bus.emit(
            EventTypes.HOTKEY_OVERLAY_TOGGLE,
            {
                "combination": "Ctrl+Shift+O",
                "timestamp": asyncio.get_event_loop().time(),
                "source": "debug_test"
            }
        )
        await asyncio.sleep(2)

        # Test 4: Check event subscriptions
        logger.info("📋 Test 4: Check event subscriptions")
        metrics = await event_bus.get_metrics()
        subscription_counts = metrics.get('subscription_counts', {})
        logger.info(f"   Event subscriptions: {subscription_counts}")

        # Cleanup
        await main_controller.shutdown()
        await ui_manager.shutdown()
        await event_bus.shutdown()

        logger.info("✅ Debug test completed")

    except Exception as e:
        logger.error(f"❌ Debug test failed: {e}")
        import traceback
        traceback.print_exc()


async def debug_ui_overlay_show(event_data):
    """Debug handler for UI overlay show events."""
    logger.info(f"🔍 UI_OVERLAY_SHOW event received: {event_data.data}")


async def debug_overlay_shown(event_data):
    """Debug handler for overlay shown events."""
    logger.info(f"🔍 OVERLAY_SHOWN event received: {event_data.data}")


async def debug_hotkey_overlay(event_data):
    """Debug handler for hotkey overlay events."""
    logger.info(f"🔍 HOTKEY_OVERLAY_TOGGLE event received: {event_data.data}")


if __name__ == "__main__":
    asyncio.run(debug_event_flow())
