"""Tests for DatabaseManager and SettingsManager.

These tests exercise the small, testable parts of the original
integration scripts (database setup, settings persistence, screenshot
storage) but in a unit-testable, non-interactive way.
"""

from datetime import datetime
import pytest

from src.models.database_manager import DatabaseManager
from src.models.screenshot_models import ScreenshotMetadata
from src.models.settings_manager import SettingsManager


@pytest.mark.asyncio
async def test_database_settings_and_screenshot_flow(tmp_path):
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

    # Screenshot operations
    # Create a small dummy file to allow checksum calculation
    img_path = tmp_path / "img.bin"
    img_path.write_bytes(b"dummy image bytes")

    metadata = ScreenshotMetadata(
        filename="img.bin",
        full_path=str(img_path),
        timestamp=datetime.now(),
        file_size=img_path.stat().st_size,
        resolution=(640, 480),
        format="PNG",
    )

    screenshot_id = await db.create_screenshot(metadata)
    assert isinstance(screenshot_id, int)

    screenshots = await db.get_screenshots(limit=10)
    assert any(s.filename == "img.bin" for s in screenshots)

    # Get by id
    s = await db.get_screenshot_by_id(screenshot_id)
    assert s is not None
    assert s.filename == "img.bin"

    # Delete and check count
    deleted = await db.delete_screenshot(screenshot_id)
    assert deleted is True

    count = await db.get_screenshot_count()
    assert count == 0

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
