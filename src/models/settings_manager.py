"""
Settings Manager Module

Manages application configuration with auto-start setup, validation,
and persistence using SQLite database storage.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional, List, Callable
from dataclasses import dataclass, asdict, field
from enum import Enum
import asyncio
import sqlite3
from datetime import datetime

logger = logging.getLogger(__name__)


class AutoStartMethod(Enum):
    """Auto-start implementation methods."""
    AUTO = "auto"
    REGISTRY = "registry"
    STARTUP_FOLDER = "startup_folder"
    DISABLED = "disabled"


@dataclass
class HotkeyConfig:
    """Hotkey configuration."""
    screenshot_capture: str = "ctrl+shift+s"
    overlay_toggle: str = "ctrl+shift+o"
    settings_open: str = "ctrl+shift+p"
    enabled: bool = True


@dataclass
class UIConfig:
    """UI configuration."""
    theme: str = "dark"
    opacity: float = 0.9
    font_size: int = 12
    window_always_on_top: bool = False
    auto_hide_overlay: bool = True
    overlay_timeout_seconds: int = 10


@dataclass
class ScreenshotConfig:
    """Screenshot configuration."""
    save_directory: str = "screenshots"
    filename_format: str = "screenshot_%Y%m%d_%H%M%S"
    image_format: str = "PNG"
    quality: int = 95
    auto_cleanup_days: int = 30
    thumbnail_size: tuple = (150, 150)


@dataclass
class OllamaConfig:
    """Ollama AI configuration."""
    server_url: str = "http://localhost:11434"
    default_model: str = "llava"
    timeout_seconds: int = 30
    max_retries: int = 3
    enable_streaming: bool = False


@dataclass
class AutoStartConfig:
    """Auto-start configuration."""
    enabled: bool = False
    method: AutoStartMethod = AutoStartMethod.AUTO
    delay_seconds: int = 5
    start_minimized: bool = True
    check_on_startup: bool = True


@dataclass
class ApplicationSettings:
    """Complete application settings."""
    # Core settings
    version: str = "0.1.0"
    first_run: bool = True
    debug_mode: bool = False
    log_level: str = "INFO"

    # Feature configurations
    hotkeys: HotkeyConfig = field(default_factory=HotkeyConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    screenshot: ScreenshotConfig = field(default_factory=ScreenshotConfig)
    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    auto_start: AutoStartConfig = field(default_factory=AutoStartConfig)

    # Metadata
    last_updated: Optional[str] = None
    update_count: int = 0


class SettingsValidationError(Exception):
    """Exception raised when settings validation fails."""
    pass


class SettingsManager:
    """
    Application settings manager with database persistence.

    Handles configuration validation, auto-start setup, and runtime
    settings updates with database storage.
    """

    def __init__(
        self,
        db_path: Optional[Path] = None,
        auto_create: bool = True,
        validate_on_load: bool = True
    ):
        """
        Initialize SettingsManager.

        Args:
            db_path: Path to SQLite database file
            auto_create: Whether to create database if it doesn't exist
            validate_on_load: Whether to validate settings when loading
        """
        self.db_path = db_path or Path("app_data.db")
        self.auto_create = auto_create
        self.validate_on_load = validate_on_load

        # Current settings
        self._settings: Optional[ApplicationSettings] = None
        self._settings_lock = asyncio.Lock()

        # Validation rules
        self._validation_rules = self._setup_validation_rules()

        # Change callbacks
        self._change_callbacks: List[Callable] = []

        logger.info("SettingsManager initialized with database: %s", self.db_path)

    def _setup_validation_rules(self) -> Dict[str, Callable]:
        """Set up validation rules for settings."""
        return {
            'ui.opacity': lambda x: 0.1 <= x <= 1.0,
            'ui.font_size': lambda x: 8 <= x <= 32,
            'ui.overlay_timeout_seconds': lambda x: 1 <= x <= 300,
            'screenshot.quality': lambda x: 1 <= x <= 100,
            'screenshot.auto_cleanup_days': lambda x: 1 <= x <= 365,
            'ollama.timeout_seconds': lambda x: 5 <= x <= 300,
            'ollama.max_retries': lambda x: 0 <= x <= 10,
            'auto_start.delay_seconds': lambda x: 0 <= x <= 60,
        }

    async def initialize_database(self) -> None:
        """Initialize the settings database."""
        if not self.db_path.exists() and not self.auto_create:
            raise FileNotFoundError(f"Database not found: {self.db_path}")

        # Create directory if needed
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Create settings table
        async with self._get_db_connection() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    type TEXT DEFAULT 'string',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    metadata TEXT
                )
            """)
            await conn.commit()

        logger.info("Settings database initialized")

    def _get_db_connection(self):
        """Get async database connection."""
        # For now, use a simple sync connection wrapper
        # In a full implementation, consider using aiosqlite
        class AsyncConnection:
            def __init__(self, db_path):
                self.conn = sqlite3.connect(db_path)
                self.conn.row_factory = sqlite3.Row
                self.cursor = None

            async def execute(self, sql, params=None):
                self.cursor = self.conn.execute(sql, params or ())
                return self.cursor

            async def fetchall(self):
                return self.cursor.fetchall() if self.cursor else []

            async def fetchone(self):
                return self.cursor.fetchone() if self.cursor else None

            async def commit(self):
                return self.conn.commit()

            async def close(self):
                return self.conn.close()

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                await self.close()

        return AsyncConnection(self.db_path)

    async def load_settings(self) -> ApplicationSettings:
        """
        Load settings from database.

        Returns:
            ApplicationSettings instance
        """
        async with self._settings_lock:
            if self._settings is not None:
                return self._settings

            # Initialize database if needed
            await self.initialize_database()

            # Load settings from database
            settings_dict = {}

            async with self._get_db_connection() as conn:
                cursor = await conn.execute("SELECT key, value, type FROM settings")
                rows = cursor.fetchall()

                for row in rows:
                    key, value_str, value_type = row

                    # Parse value based on type
                    try:
                        if value_type == 'json':
                            value = json.loads(value_str)
                        elif value_type == 'bool':
                            value = value_str.lower() == 'true'
                        elif value_type == 'int':
                            value = int(value_str)
                        elif value_type == 'float':
                            value = float(value_str)
                        else:
                            value = value_str

                        settings_dict[key] = value

                    except (json.JSONDecodeError, ValueError) as e:
                        logger.warning(
                            "Failed to parse setting '%s' with value '%s': %s",
                            key, value_str, e
                        )

            # Create settings object with defaults and overrides
            self._settings = self._merge_with_defaults(settings_dict)

            # Validate if requested
            if self.validate_on_load:
                await self.validate_settings()

            logger.info("Settings loaded successfully")
            return self._settings

    def _merge_with_defaults(self, overrides: Dict[str, Any]) -> ApplicationSettings:
        """Merge override values with default settings."""
        # Start with defaults
        settings = ApplicationSettings()

        # Apply overrides using dot notation
        for key, value in overrides.items():
            self._set_nested_value(settings, key, value)

        return settings

    def _set_nested_value(self, obj: Any, key: str, value: Any) -> None:
        """Set value using dot notation key."""
        parts = key.split('.')
        current = obj

        # Navigate to parent object
        for part in parts[:-1]:
            if hasattr(current, part):
                current = getattr(current, part)
            else:
                logger.warning("Invalid settings key: %s", key)
                return

        # Set final value
        final_key = parts[-1]
        if hasattr(current, final_key):
            setattr(current, final_key, value)
        else:
            logger.warning("Invalid settings key: %s", key)

    def _get_nested_value(self, obj: Any, key: str) -> Any:
        """Get value using dot notation key."""
        parts = key.split('.')
        current = obj

        for part in parts:
            if hasattr(current, part):
                current = getattr(current, part)
            else:
                return None

        return current

    async def save_settings(self, settings: Optional[ApplicationSettings] = None) -> None:
        """
        Save settings to database.

        Args:
            settings: Settings to save (uses current if None)
        """
        async with self._settings_lock:
            if settings is None:
                settings = self._settings

            if settings is None:
                raise ValueError("No settings to save")

            # Update metadata
            settings.last_updated = datetime.now().isoformat()
            settings.update_count += 1

            # Convert to flat dictionary
            flat_dict = self._flatten_settings(settings)

            # Save to database
            async with self._get_db_connection() as conn:
                for key, value in flat_dict.items():
                    # Determine value type
                    if isinstance(value, bool):
                        value_str = str(value).lower()
                        value_type = 'bool'
                    elif isinstance(value, int):
                        value_str = str(value)
                        value_type = 'int'
                    elif isinstance(value, float):
                        value_str = str(value)
                        value_type = 'float'
                    elif isinstance(value, (dict, list)):
                        value_str = json.dumps(value)
                        value_type = 'json'
                    else:
                        value_str = str(value)
                        value_type = 'string'

                    # Insert or update
                    await conn.execute("""
                        INSERT OR REPLACE INTO settings
                        (key, value, type, updated_at)
                        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    """, (key, value_str, value_type))

                await conn.commit()

            self._settings = settings

            # Notify change callbacks
            await self._notify_changes()

            logger.info("Settings saved successfully")

    def _flatten_settings(self, settings: ApplicationSettings) -> Dict[str, Any]:
        """Flatten settings object to dot-notation dictionary."""
        flat_dict = {}

        def flatten_object(obj, prefix=""):
            for key, value in asdict(obj).items():
                full_key = f"{prefix}.{key}" if prefix else key

                if isinstance(value, dict):
                    for sub_key, sub_value in value.items():
                        flat_dict[f"{full_key}.{sub_key}"] = sub_value
                else:
                    flat_dict[full_key] = value

        flatten_object(settings)
        return flat_dict

    async def get_setting(self, key: str, default: Any = None) -> Any:
        """
        Get a specific setting value.

        Args:
            key: Setting key in dot notation
            default: Default value if not found

        Returns:
            Setting value or default
        """
        settings = await self.load_settings()
        value = self._get_nested_value(settings, key)
        return value if value is not None else default

    async def update_setting(self, key: str, value: Any) -> bool:
        """
        Update a specific setting.

        Args:
            key: Setting key in dot notation
            value: New value

        Returns:
            True if updated successfully
        """
        try:
            # Validate the new value
            if not await self.validate_setting(key, value):
                return False

            # Load current settings
            settings = await self.load_settings()

            # Update the value
            self._set_nested_value(settings, key, value)

            # Save updated settings
            await self.save_settings(settings)

            logger.info("Setting updated: %s = %s", key, value)
            return True

        except Exception as e:
            logger.error("Failed to update setting '%s': %s", key, e)
            return False

    async def validate_setting(self, key: str, value: Any) -> bool:
        """
        Validate a specific setting value.

        Args:
            key: Setting key
            value: Value to validate

        Returns:
            True if valid
        """
        if key in self._validation_rules:
            try:
                return self._validation_rules[key](value)
            except Exception as e:
                logger.warning("Validation error for '%s': %s", key, e)
                return False

        return True

    async def validate_settings(self) -> None:
        """
        Validate all current settings.

        Raises:
            SettingsValidationError: If validation fails
        """
        if self._settings is None:
            return

        flat_dict = self._flatten_settings(self._settings)
        errors = []

        for key, value in flat_dict.items():
            if not await self.validate_setting(key, value):
                errors.append(f"Invalid value for '{key}': {value}")

        if errors:
            raise SettingsValidationError(f"Settings validation failed: {'; '.join(errors)}")

    async def reset_to_defaults(self, section: Optional[str] = None) -> None:
        """
        Reset settings to defaults.

        Args:
            section: Section to reset (all if None)
        """
        if section is None:
            # Reset all settings
            self._settings = ApplicationSettings()
            await self.save_settings()
            logger.info("All settings reset to defaults")
        else:
            # Reset specific section
            settings = await self.load_settings()

            if section == "hotkeys":
                settings.hotkeys = HotkeyConfig()
            elif section == "ui":
                settings.ui = UIConfig()
            elif section == "screenshot":
                settings.screenshot = ScreenshotConfig()
            elif section == "ollama":
                settings.ollama = OllamaConfig()
            elif section == "auto_start":
                settings.auto_start = AutoStartConfig()
            else:
                logger.warning("Unknown settings section: %s", section)
                return

            await self.save_settings(settings)
            logger.info("Settings section '%s' reset to defaults", section)

    async def export_settings(self) -> Dict[str, Any]:
        """
        Export settings as dictionary.

        Returns:
            Settings dictionary
        """
        settings = await self.load_settings()
        return asdict(settings)

    async def import_settings(self, data: Dict[str, Any], validate: bool = True) -> bool:
        """
        Import settings from dictionary.

        Args:
            data: Settings data
            validate: Whether to validate imported settings

        Returns:
            True if imported successfully
        """
        try:
            # Create settings object from data
            flat_data = {}

            def flatten_dict(d, prefix=""):
                for key, value in d.items():
                    full_key = f"{prefix}.{key}" if prefix else key
                    if isinstance(value, dict):
                        flatten_dict(value, full_key)
                    else:
                        flat_data[full_key] = value

            flatten_dict(data)

            # Create new settings with imported data
            new_settings = self._merge_with_defaults(flat_data)

            # Validate if requested
            if validate:
                # Temporarily set settings for validation
                old_settings = self._settings
                self._settings = new_settings
                try:
                    await self.validate_settings()
                except SettingsValidationError:
                    self._settings = old_settings
                    raise

            # Save imported settings
            await self.save_settings(new_settings)

            logger.info("Settings imported successfully")
            return True

        except Exception as e:
            logger.error("Failed to import settings: %s", e)
            return False

    def add_change_callback(self, callback: Callable) -> None:
        """
        Add callback for settings changes.

        Args:
            callback: Function to call when settings change
        """
        self._change_callbacks.append(callback)

    def remove_change_callback(self, callback: Callable) -> bool:
        """
        Remove settings change callback.

        Args:
            callback: Callback to remove

        Returns:
            True if removed
        """
        try:
            self._change_callbacks.remove(callback)
            return True
        except ValueError:
            return False

    async def _notify_changes(self) -> None:
        """Notify all change callbacks."""
        for callback in self._change_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(self._settings)
                else:
                    callback(self._settings)
            except Exception as e:
                logger.error("Error in settings change callback: %s", e)

    async def cleanup_old_backups(self, keep_count: int = 5) -> int:
        """
        Clean up old settings backups.

        Args:
            keep_count: Number of backups to keep

        Returns:
            Number of backups removed
        """
        # This would implement backup cleanup logic
        # For now, just return 0
        return 0

    def __str__(self) -> str:
        """String representation of settings."""
        if self._settings is None:
            return "SettingsManager(not loaded)"

        return f"SettingsManager(version={self._settings.version}, updates={self._settings.update_count})"
