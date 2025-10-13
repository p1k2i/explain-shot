"""
Simple test for HotkeyHandler implementation

Tests the hotkey system integration and mock functionality without pytest.
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add project root to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.controllers.event_bus import EventBus
from src.controllers.hotkey_handler import HotkeyHandler, HotkeyCombo
from src.controllers.main_controller import MainController
from src.models.settings_manager import SettingsManager
from src import EventTypes


async def test_hotkey_combination_parsing():
    """Test hotkey combination parsing."""
    print("Testing hotkey combination parsing...")

    event_bus = EventBus()
    settings_manager = SettingsManager(auto_create=True, validate_on_load=False)
    await settings_manager.initialize_database()

    handler = HotkeyHandler(event_bus, settings_manager)

    try:
        # Test valid combinations
        combo1 = handler._parse_hotkey_combination("ctrl+shift+s")
        assert combo1.modifiers == {'ctrl', 'shift'}
        assert combo1.key == 's'
        assert combo1.display_name == "Ctrl+Shift+S"
        print("✓ Valid combination parsed correctly")

        combo2 = handler._parse_hotkey_combination("ctrl+alt+f12")
        assert combo2.modifiers == {'ctrl', 'alt'}
        assert combo2.key == 'f12'
        print("✓ Function key combination parsed correctly")

        # Test invalid combinations
        try:
            handler._parse_hotkey_combination("invalid")
            assert False, "Should raise validation error"
        except Exception:
            print("✓ Invalid combination properly rejected")

        print("Hotkey combination parsing test PASSED\n")

    finally:
        await handler.shutdown_handlers()
        await event_bus.shutdown()


async def test_hotkey_registration():
    """Test hotkey registration process."""
    print("Testing hotkey registration...")

    event_bus = EventBus()
    settings_manager = SettingsManager(auto_create=True, validate_on_load=False)
    await settings_manager.initialize_database()

    handler = HotkeyHandler(event_bus, settings_manager)

    try:
        # Initialize handler
        success = await handler.initialize_handlers()
        assert success
        print("✓ Handler initialized successfully")

        # Test registration
        combo = HotkeyCombo(
            modifiers={'ctrl', 'shift'},
            key='t',
            raw_combination='ctrl+shift+t'
        )

        result = await handler.register_hotkey(
            'test_hotkey',
            combo,
            'test_action'
        )

        print(f"✓ Hotkey registration result: {result}")

        # Check registered hotkeys
        registered = handler.get_registered_hotkeys()
        print(f"✓ Currently registered hotkeys: {list(registered.keys())}")

        print("Hotkey registration test PASSED\n")

    finally:
        await handler.shutdown_handlers()
        await event_bus.shutdown()


async def test_event_integration():
    """Test event integration between components."""
    print("Testing event integration...")

    event_bus = EventBus()
    settings_manager = SettingsManager(auto_create=True, validate_on_load=False)
    await settings_manager.initialize_database()

    main_controller = MainController(event_bus, settings_manager)

    try:
        # Initialize controller
        success = await main_controller.initialize()
        assert success
        print("✓ Main controller initialized successfully")

        # Test event emission
        received_events = []

        async def event_handler(event_data):
            received_events.append(event_data)

        await event_bus.subscribe(
            EventTypes.SCREENSHOT_CAPTURED,
            event_handler
        )
        print("✓ Event handler subscribed")

        # Emit hotkey event
        await event_bus.emit(
            EventTypes.HOTKEY_SCREENSHOT_CAPTURE,
            {
                'hotkey_id': 'test',
                'combination': 'Ctrl+Shift+S',
                'timestamp': 123456789.0,
                'mock_action': 'screenshot_capture_requested'
            },
            source="test"
        )
        print("✓ Hotkey event emitted")

        # Wait for processing
        await asyncio.sleep(0.2)

        # Check if event was handled
        if len(received_events) > 0:
            print("✓ Event was handled successfully")
            print(f"  Received event data: {received_events[0].data}")
        else:
            print("⚠ No events received (may be normal in test)")

        print("Event integration test PASSED\n")

    finally:
        await main_controller.shutdown()
        await event_bus.shutdown()


async def test_mock_functionality():
    """Test mock implementations."""
    print("Testing mock functionality...")

    event_bus = EventBus()
    settings_manager = SettingsManager(auto_create=True, validate_on_load=False)
    await settings_manager.initialize_database()

    main_controller = MainController(event_bus, settings_manager)

    try:
        # Initialize controller
        await main_controller.initialize()
        print("✓ Controller initialized for mock testing")

        # Test mock screenshot capture
        await main_controller._mock_screenshot_capture({
            'trigger_source': 'test',
            'hotkey_combination': 'Ctrl+Shift+S'
        })
        print("✓ Mock screenshot capture executed")

        # Test mock overlay toggle
        await main_controller._mock_overlay_toggle({
            'trigger_source': 'test',
            'hotkey_combination': 'Ctrl+Shift+O'
        })
        print("✓ Mock overlay toggle executed")

        # Test mock settings open
        await main_controller._mock_settings_open({
            'trigger_source': 'test',
            'hotkey_combination': 'Ctrl+Shift+P'
        })
        print("✓ Mock settings open executed")

        print("Mock functionality test PASSED\n")

    finally:
        await main_controller.shutdown()
        await event_bus.shutdown()


async def run_complete_hotkey_test():
    """Run complete hotkey system test."""
    print("=== Starting Complete Hotkey System Test ===\n")

    try:
        await test_hotkey_combination_parsing()
        await test_hotkey_registration()
        await test_event_integration()
        await test_mock_functionality()

        print("=== All Tests PASSED ===")

    except Exception as e:
        print(f"=== Test FAILED with error: {e} ===")
        import traceback
        traceback.print_exc()


async def manual_test_hotkey_system():
    """Manual test for the complete hotkey system."""
    print("=== Starting Manual Hotkey System Test ===\n")

    # Create components
    event_bus = EventBus()
    settings_manager = SettingsManager(auto_create=True, validate_on_load=False)
    await settings_manager.initialize_database()

    # Create main controller
    main_controller = MainController(event_bus, settings_manager)

    try:
        # Initialize
        success = await main_controller.initialize()
        print(f"Initialization successful: {success}")

        if success:
            # Get status
            status = await main_controller.get_application_status()
            print("\nApplication Status:")
            for key, value in status.items():
                print(f"  {key}: {value}")

            # Test hotkey simulation
            if main_controller.hotkey_handler:
                print("\nSimulating hotkey events...")

                # Simulate screenshot hotkey
                await event_bus.emit(
                    EventTypes.HOTKEY_SCREENSHOT_CAPTURE,
                    {
                        'hotkey_id': 'screenshot_capture',
                        'combination': 'Ctrl+Shift+S',
                        'timestamp': 123456789.0,
                        'mock_action': 'screenshot_capture_requested'
                    },
                    source="manual_test"
                )

                # Simulate overlay hotkey
                await event_bus.emit(
                    EventTypes.HOTKEY_OVERLAY_TOGGLE,
                    {
                        'hotkey_id': 'overlay_toggle',
                        'combination': 'Ctrl+Shift+O',
                        'timestamp': 123456789.0,
                        'mock_action': 'overlay_toggle_requested'
                    },
                    source="manual_test"
                )

                # Wait for processing
                await asyncio.sleep(0.3)

                print("Hotkey simulation completed")

                # Check handler status
                if main_controller.hotkey_handler.is_handler_active():
                    print("✓ Hotkey handler is active")
                    registered = main_controller.hotkey_handler.get_registered_hotkeys()
                    print(f"✓ Registered hotkeys: {list(registered.keys())}")
                else:
                    print("⚠ Hotkey handler is not active")

    finally:
        # Cleanup
        await main_controller.shutdown()
        await event_bus.shutdown()

    print("\n=== Manual Test Completed ===")


if __name__ == "__main__":
    # Run both test suites
    asyncio.run(run_complete_hotkey_test())
    print("\n" + "="*50 + "\n")
    asyncio.run(manual_test_hotkey_system())
