"""
ExplainShot Application

A lightweight, cross-platform desktop application for capturing screenshots
and explaining them using AI integration. Built with Python 3.12 following
the MVC pattern with minimal coupling.
"""

from pathlib import Path

__version__ = "0.1.0"
__author__ = "ExplainShot Team"
__description__ = "AI-powered screenshot explanation tool"

# Application metadata
APP_NAME = "ExplainShot"
APP_VERSION = __version__
APP_AUTHOR = __author__
APP_DESCRIPTION = __description__

# Utility functions
def get_app_data_dir() -> str:
    """
    Get the application data directory for storing configuration and data files.

    On Windows, this uses %APPDATA%\\ExplainShot
    On other platforms, this uses the user's home directory .config/ExplainShot

    Returns:
        Path to the application data directory as a string
    """
    import os
    from pathlib import Path

    if os.name == 'nt':  # Windows
        appdata = os.getenv('APPDATA')
        if appdata:
            return str(Path(appdata) / APP_NAME)
        else:
            # Fallback to home directory if APPDATA is not set
            return str(Path.home() / f".{APP_NAME.lower()}")
    else:
        # For other platforms (Linux, macOS), use XDG standard
        xdg_config = os.getenv('XDG_CONFIG_HOME')
        if xdg_config:
            return str(Path(xdg_config) / APP_NAME)
        else:
            return str(Path.home() / ".config" / APP_NAME)

# Configuration constants
DEFAULT_SCREENSHOT_DIR = "screenshots"
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_DATABASE_NAME = str(Path(get_app_data_dir()) / "app_data.db")

# Event types used throughout the application
class EventTypes:
    """Central registry of event types for the EventBus system."""

    # Application lifecycle
    APP_READY = "app.ready"
    APP_SHUTDOWN_REQUESTED = "app.shutdown_requested"
    APP_SHUTDOWN_STARTING = "app.shutdown_starting"
    APP_STATE_CHANGED = "app.state_changed"

    # Tray events
    TRAY_SETTINGS_REQUESTED = "tray.settings_requested"
    TRAY_GALLERY_REQUESTED = "tray.gallery_requested"
    TRAY_OVERLAY_TOGGLE = "tray.overlay_toggle"
    TRAY_QUIT_REQUESTED = "tray.quit_requested"
    TRAY_MENU_SELECTED = "tray.menu_selected"
    TRAY_NOTIFICATION_CLICKED = "tray.notification_clicked"
    TRAY_ICON_DOUBLE_CLICKED = "tray.icon_double_clicked"
    TRAY_CLEANUP_COMPLETE = "tray.cleanup_complete"

    # Screenshot events
    SCREENSHOT_CAPTURE_REQUESTED = "screenshot.capture_requested"
    SCREENSHOT_CAPTURED = "screenshot.captured"
    SCREENSHOT_COMPLETED = "screenshot.completed"

    # UI events
    UI_OVERLAY_SHOW = "ui.overlay.show"
    UI_OVERLAY_HIDE = "ui.overlay.hide"
    UI_SETTINGS_SHOW = "ui.settings.show"
    UI_GALLERY_SHOW = "ui.gallery.show"
    UI_GALLERY_HIDE = "ui.gallery.hide"

    # Gallery events
    GALLERY_REQUESTED = "gallery.requested"
    GALLERY_SHOWN = "gallery.shown"
    GALLERY_HIDDEN = "gallery.hidden"
    GALLERY_SCREENSHOT_SELECTED = "gallery.screenshot_selected"
    GALLERY_PRESET_EXECUTED = "gallery.preset_executed"
    GALLERY_CHAT_MESSAGE_SENT = "gallery.chat_message_sent"
    GALLERY_CLOSED = "gallery.closed"

    # Overlay events
    OVERLAY_SHOWN = "overlay.shown"
    OVERLAY_HIDDEN = "overlay.hidden"
    OVERLAY_ITEM_SELECTED = "overlay.item_selected"
    OVERLAY_DISMISSED = "overlay.dismissed"

    # Settings events
    SETTINGS_UPDATED = "settings.updated"
    SETTINGS_CHANGED = "settings.changed"
    SETTINGS_SAVE_REQUESTED = "settings.save_requested"
    SETTINGS_SAVED = "settings.saved"
    SETTINGS_RESET_REQUESTED = "settings.reset_requested"
    SETTINGS_WINDOW_SHOWN = "settings.window.shown"
    SETTINGS_WINDOW_CLOSED = "settings.window.closed"

    # Error events
    ERROR_OCCURRED = "error.occurred"

    # Hotkey events
    HOTKEY_SCREENSHOT_CAPTURE = "hotkey.screenshot_capture"
    HOTKEY_OVERLAY_TOGGLE = "hotkey.overlay_toggle"
    HOTKEY_SETTINGS_OPEN = "hotkey.settings_open"
    HOTKEY_REGISTRATION_SUCCESS = "hotkey.registration.success"
    HOTKEY_REGISTRATION_FAILED = "hotkey.registration.failed"
    HOTKEY_CONFLICT_DETECTED = "hotkey.conflict.detected"
    HOTKEY_CONFLICT_RESOLVED = "hotkey.conflict.resolved"
    HOTKEY_HANDLER_READY = "hotkey.handler.ready"
    HOTKEY_HANDLER_ERROR = "hotkey.handler.error"

    # AI/Ollama events
    OLLAMA_RESPONSE_RECEIVED = "ollama.response.received"

    # Preset events
    PRESET_CREATED = "preset.created"
    PRESET_UPDATED = "preset.updated"
    PRESET_DELETED = "preset.deleted"

# Application states
class AppState:
    """Application state enumeration."""
    STARTING = "starting"
    READY = "ready"
    BUSY = "busy"
    ERROR = "error"
    SHUTTING_DOWN = "shutting_down"

# Icon states for tray manager
class IconState:
    """System tray icon state enumeration."""
    IDLE = "idle"
    CAPTURING = "capturing"
    PROCESSING = "processing"
    ERROR = "error"
    DISABLED = "disabled"
