#!/usr/bin/env python3
"""
Integration Test Script

Simple test to verify the core integration works properly.
"""

import asyncio
import sys
import logging
from pathlib import Path

# Add the src directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.controllers.event_bus import get_event_bus
from src.models.settings_manager import SettingsManager
from src.models.database_manager import DatabaseManager

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def test_settings_integration():
    """Test settings integration with database."""
    print("Testing Settings Integration...")

    # Initialize components
    db_manager = DatabaseManager(db_path="test_app_data.db")
    await db_manager.initialize_database()

    settings_manager = SettingsManager(database_manager=db_manager)
    await settings_manager.initialize_database()

    # Test setting update
    success = await settings_manager.update_setting("screenshot.quality", 85)
    print(f"Setting update success: {success}")

    # Test getting setting
    quality = await settings_manager.get_setting("screenshot.quality", 95)
    print(f"Retrieved quality setting: {quality}")

    # Test settings load
    settings = await settings_manager.load_settings()
    print(f"Loaded settings version: {settings.version}")

    return success and quality == 85

async def test_event_bus():
    """Test EventBus functionality."""
    print("Testing EventBus...")

    event_bus = get_event_bus()
    received_events = []

    # Subscribe to test event
    async def test_handler(event_data):
        received_events.append(event_data)
        print(f"Received event: {event_data.event_type}")

    await event_bus.subscribe("test.event", test_handler)

    # Emit test event
    await event_bus.emit("test.event", {"test": "data"}, source="test")

    # Process events
    await asyncio.sleep(0.1)

    return len(received_events) > 0

async def main():
    """Run integration tests."""
    print("=== Integration Test Suite ===")

    try:
        # Test EventBus
        event_success = await test_event_bus()
        print(f"EventBus test: {'PASS' if event_success else 'FAIL'}")

        # Test Settings Integration
        settings_success = await test_settings_integration()
        print(f"Settings integration test: {'PASS' if settings_success else 'FAIL'}")

        # Overall result
        overall_success = event_success and settings_success
        print(f"\n=== Overall Result: {'PASS' if overall_success else 'FAIL'} ===")

        return 0 if overall_success else 1

    except Exception as e:
        print(f"Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        # Cleanup test database
        try:
            Path("test_app_data.db").unlink(missing_ok=True)
            print("Cleaned up test database")
        except Exception:
            pass

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
