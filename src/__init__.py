"""
Explain Screenshot Application

A lightweight, cross-platform desktop application for capturing screenshots
and explaining them using AI integration. Built with Python 3.12 following
the MVC pattern with minimal coupling.
"""

__version__ = "0.1.0"
__author__ = "Explain Screenshot Team"
__description__ = "AI-powered screenshot explanation tool"

# Application metadata
APP_NAME = "Explain Screenshot"
APP_VERSION = __version__
APP_AUTHOR = __author__
APP_DESCRIPTION = __description__

# Configuration constants
DEFAULT_SCREENSHOT_DIR = "screenshots"
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_DATABASE_NAME = "app_data.db"

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

    # Settings events
    SETTINGS_UPDATED = "settings.updated"
    SETTINGS_CHANGED = "settings.changed"

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
