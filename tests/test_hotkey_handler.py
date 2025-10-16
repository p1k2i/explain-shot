"""Unit tests for HotkeyHandler logic (non-GUI parts).

These tests target parsing, validation, registration logic and conflict
resolution paths that don't require a real keyboard listener or GUI.
"""

import asyncio
import pytest

from src.controllers.hotkey_handler import (
    HotkeyHandler,
    HotkeyCombo,
    HotkeyValidationError,
)
from src.controllers.event_bus import EventBus
from src.models.settings_manager import SettingsManager


@pytest.mark.asyncio
async def test_parse_valid_and_invalid_hotkey_combinations():
    bus = EventBus()
    settings_manager = SettingsManager()

    handler = HotkeyHandler(bus, settings_manager)

    combo = handler._parse_hotkey_combination("ctrl+shift+s")
    assert combo.modifiers == {"ctrl", "shift"}
    assert combo.key == "s"
    assert combo.display_name == "Ctrl+Shift+S"

    # Invalid formats
    with pytest.raises(HotkeyValidationError):
        handler._parse_hotkey_combination("invalid")

    # Forbidden system hotkey
    with pytest.raises(HotkeyValidationError):
        handler._parse_hotkey_combination("ctrl+alt+del")


@pytest.mark.asyncio
async def test_register_and_unregister_hotkey_success_and_conflict():
    bus = EventBus()
    settings_manager = SettingsManager()
    handler = HotkeyHandler(bus, settings_manager)

    # Listen for registration success events
    event_triggered = asyncio.Event()

    async def on_registration(event):
        if event.data and event.data.get("hotkey_id") == "test1":
            event_triggered.set()

    await bus.subscribe("hotkey.registration.success", on_registration)

    combo_ok = handler._parse_hotkey_combination("ctrl+shift+s")

    ok = await handler.register_hotkey("test1", combo_ok, "action.capture")
    assert ok is True

    # Wait for the registration event to be emitted
    await asyncio.wait_for(event_triggered.wait(), timeout=1.0)

    registered = handler.get_registered_hotkeys()
    assert "test1" in registered

    # Try to register a conflicting system combo
    combo_conflict = handler._parse_hotkey_combination("ctrl+shift+esc")
    ok2 = await handler.register_hotkey("conflict1", combo_conflict, "action.x")
    assert ok2 is False

    conflicts = handler.get_conflict_report()
    assert any(ci.hotkey_id == "conflict1" for ci in conflicts)

    # Cleanup
    await handler.unregister_hotkey("test1")
    assert "test1" not in handler.get_registered_hotkeys()

    await handler.shutdown_handlers()


@pytest.mark.asyncio
async def test_generate_alternatives_and_availability():
    bus = EventBus()
    settings_manager = SettingsManager()
    handler = HotkeyHandler(bus, settings_manager)

    original = handler._parse_hotkey_combination("ctrl+shift+esc")
    alts = handler._generate_alternatives(original)

    # Limit should be no more than 3 alternatives
    assert len(alts) <= 3

    # Check that alternatives look like valid combos
    assert any(isinstance(a, HotkeyCombo) for a in alts)

    # Availability check for a good and bad combo
    good = handler._parse_hotkey_combination("ctrl+shift+s")
    assert await handler.check_hotkey_availability(good) is True

    bad = handler._parse_hotkey_combination("ctrl+shift+esc")
    assert await handler.check_hotkey_availability(bad) is False
