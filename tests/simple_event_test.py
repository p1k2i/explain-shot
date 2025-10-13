#!/usr/bin/env python3
"""
Simple test to isolate the MainController event handler issue.
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add project root to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.controllers.event_bus import EventBus
from src.controllers.main_controller import MainController
from src.models.settings_manager import SettingsManager
from src import EventTypes

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


async def simple_handler_test():
    """Test just the MainController event handler."""
    try:
        logger.info("🧪 Testing MainController event handler directly...")

        # Initialize components
        event_bus = EventBus()
        settings_manager = SettingsManager()
        await settings_manager.initialize_database()

        # Create MainController without UI manager (simplified)
        main_controller = MainController(
            event_bus=event_bus,
            settings_manager=settings_manager,
            ui_manager=None  # Simplified test
        )

        # Initialize MainController (this will subscribe to events)
        await main_controller.initialize()

        logger.info("✅ MainController initialized, checking subscriptions...")

        # Check if subscription exists
        metrics = await event_bus.get_metrics()
        subscription_counts = metrics.get('subscription_counts', {})
        logger.info(f"📊 Subscriptions: {subscription_counts}")

        # Emit the event directly
        logger.info("🚀 Emitting hotkey.overlay_toggle event...")
        await event_bus.emit(
            EventTypes.HOTKEY_OVERLAY_TOGGLE,
            {
                "combination": "Ctrl+Shift+O",
                "timestamp": asyncio.get_event_loop().time(),
                "source": "simple_test"
            }
        )

        # Wait a moment for processing
        await asyncio.sleep(0.5)

        logger.info("✅ Test completed")

        # Cleanup
        await main_controller.shutdown()
        await event_bus.shutdown()

    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        logger.debug("Exception details:", exc_info=True)


if __name__ == "__main__":
    asyncio.run(simple_handler_test())
