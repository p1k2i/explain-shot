"""One QObject full of pyqtSignals — the app-wide notification bus.

The old code had a custom async EventBus (~550 lines) plus a UIManager
trampoline that queued events, marshalled them through a QTimer, then
called asyncio.create_task — every UI action crossed three thread/loop
boundaries for no reason. Qt already ships an async-friendly, thread-safe
signal system; we use it.

Signals are grouped by concern and named by past-tense fact
(screenshot_captured, ai_reply_received). Command-shaped requests
(open_gallery, capture_region) belong on the corresponding window/manager.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal


class AppSignals(QObject):
    # Screenshot lifecycle
    screenshot_captured = pyqtSignal(object)      # ScreenshotRecord
    screenshot_deleted = pyqtSignal(str)          # screenshot_id

    # AI conversation
    ai_reply_started = pyqtSignal(str)            # screenshot_id
    ai_reply_chunk = pyqtSignal(str, str)         # screenshot_id, delta
    ai_reply_completed = pyqtSignal(str, str)     # screenshot_id, full_text
    ai_reply_failed = pyqtSignal(str, str)        # screenshot_id, error

    # Settings
    settings_changed = pyqtSignal(str, object)    # key, value

    # Hotkeys — these fire in the pynput thread; connect with QueuedConnection
    hotkey_capture_region = pyqtSignal()
    hotkey_capture_fullscreen = pyqtSignal()   # grab whole screen, save silently
    hotkey_toggle_gallery = pyqtSignal()
    hotkey_open_settings = pyqtSignal()

    # Preset lifecycle
    preset_saved = pyqtSignal(str)                # preset_id
    preset_deleted = pyqtSignal(str)              # preset_id

    # Application lifecycle
    shutdown_requested = pyqtSignal()
