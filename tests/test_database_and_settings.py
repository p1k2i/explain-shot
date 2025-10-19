"""Tests for DatabaseManager and SettingsManager.

These tests exercise the small, testable parts of the original
integration scripts (database setup, settings persistence)
but in a unit-testable, non-interactive way.
"""

import pytest

from src.models.database_manager import DatabaseManager
from src.models.settings_manager import SettingsManager


@pytest.mark.asyncio
async def test_database_settings_flow(tmp_path):
    db_file = tmp_path / "test_db.sqlite"

    db = DatabaseManager(str(db_file))
    await db.initialize_database()

    # Settings operations
    ok = await db.set_setting("app.test_bool", True)
    assert ok is True

    val = await db.get_setting("app.test_bool", default=False)
    assert val is True

    all_settings = await db.get_all_settings()
    assert "app.test_bool" in all_settings

    # Test different setting types
    await db.set_setting("app.test_int", 42)
    await db.set_setting("app.test_float", 3.14)
    await db.set_setting("app.test_string", "hello")
    await db.set_setting("app.test_json", {"key": "value"})

    assert await db.get_setting("app.test_int") == 42
    assert await db.get_setting("app.test_float") == 3.14
    assert await db.get_setting("app.test_string") == "hello"
    assert await db.get_setting("app.test_json") == {"key": "value"}

    # Delete settings
    deleted = await db.delete_setting("app.test_bool")
    assert deleted is True

    # Verify deleted setting returns default
    val = await db.get_setting("app.test_bool", default=False)
    assert val is False

    await db.close()


@pytest.mark.asyncio
async def test_settings_manager_merge_validation_and_import(tmp_path):
    db_file = tmp_path / "settings_db.sqlite"
    db = DatabaseManager(str(db_file))

    # Use a SettingsManager wired to a test database
    settings_manager = SettingsManager(database_manager=db, validate_on_load=False)

    # Load defaults
    settings = await settings_manager.load_settings()
    assert settings is not None

    # Update a valid setting
    ok = await settings_manager.update_setting("ui.opacity", 0.7)
    assert ok is True
    new_val = await settings_manager.get_setting("ui.opacity")
    assert new_val == 0.7

    # Try to update an invalid value (out of allowed range)
    bad = await settings_manager.update_setting("ui.opacity", 10.0)
    assert bad is False

    # Import invalid settings should return False when validation is enabled
    import_result = await settings_manager.import_settings({"ui": {"opacity": 10}}, validate=True)
    assert import_result is False

    # Reset a section and ensure defaults are applied
    await settings_manager.update_setting("ui.font_size", 20)
    assert await settings_manager.get_setting("ui.font_size") == 20

    await settings_manager.reset_to_defaults("ui")
    assert await settings_manager.get_setting("ui.font_size") == 12

    await db.close()
