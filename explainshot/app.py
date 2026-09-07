"""Application object — owns the singletons and controls window lifecycle."""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import QObject, Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QApplication

from . import APP_NAME
from .ai.controller import ChatController
from .ai.history import ChatHistory
from .ai.provider import AIProvider
from .capture.screenshot import ScreenshotService
from .capture.thumbnails import ThumbnailCache
from .config.settings import Settings, load_settings, save_settings
from .core.database import Database
from .core.signals import AppSignals
from .hotkeys.manager import HotkeyManager
from .presets.manager import PresetManager
from .ui.gallery import GalleryWindow
from .ui.icons import app_icon
from .ui.overlay import CaptureOverlay
from .ui.settings import SettingsWindow
from .ui.theme import Theme, apply_theme
from .ui.tray import Tray

log = logging.getLogger(__name__)


class Application(QObject):
    def __init__(self, qt_app: QApplication) -> None:
        super().__init__()
        self.qt_app = qt_app
        self.qt_app.setApplicationName(APP_NAME)
        self.qt_app.setQuitOnLastWindowClosed(False)
        self.qt_app.setWindowIcon(app_icon())

        self.settings: Settings = load_settings()
        self.db = Database()
        self.signals = AppSignals()

        self.thumbnails = ThumbnailCache(
            size=self.settings.ui.thumbnail_px,
            capacity=256,
        )
        self.screenshots = ScreenshotService(
            db=self.db,
            config=self.settings.screenshot,
            directory=self.settings.resolved_screenshot_dir(),
            signals=self.signals,
        )
        self.screenshots.scan_directory()

        self.presets = PresetManager(self.db, self.signals)
        self.history = ChatHistory(self.db)
        self.chat = ChatController(
            self.history,
            self._build_provider,
            context_chars_limit=self.settings.ai.context_chars_limit,
            parent=self,
        )
        self.hotkeys = HotkeyManager(self.settings.hotkeys, self.signals)

        self.tray = Tray(
            self.signals,
            on_capture=self._request_capture,
            on_show_gallery=self.show_gallery,
            on_show_settings=self.show_settings,
            on_quit=self.quit,
            parent=self,
        )

        self._apply_theme()

        # Live references so windows aren't garbage-collected while shown.
        self._gallery: GalleryWindow | None = None
        self._settings_window: SettingsWindow | None = None
        self._capture_overlay: CaptureOverlay | None = None
        self._toasts: list = []   # in-flight capture pop-ups (keep alive)

        # Hotkeys — pynput's background thread signals cross into the main
        # thread via Qt's automatic QueuedConnection.
        self.signals.hotkey_capture_region.connect(self._request_capture)
        self.signals.hotkey_capture_fullscreen.connect(self._capture_fullscreen_silent)
        self.signals.hotkey_toggle_gallery.connect(self.toggle_gallery)
        self.signals.hotkey_open_settings.connect(self.show_settings)
        # Menu bar "Exit" (and any other quit request) routes through here.
        self.signals.shutdown_requested.connect(self.quit)

    # -- lifecycle -------------------------------------------------------------

    def start(self) -> None:
        self.tray.show()
        self.hotkeys.start()

    def quit(self) -> None:
        self.hotkeys.stop()
        self.tray.hide()
        for w in (self._gallery, self._settings_window, self._capture_overlay):
            if w is not None:
                w.close()
        self.db.close()
        self.qt_app.quit()

    # -- gallery ---------------------------------------------------------------

    def show_gallery(self) -> None:
        if self._gallery is None:
            self._gallery = GalleryWindow(
                settings=self.settings,
                signals=self.signals,
                db=self.db,
                screenshots=self.screenshots,
                thumbnails=self.thumbnails,
                presets=self.presets,
                history=self.history,
                chat=self.chat,
            )
            self._gallery.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            self._gallery.destroyed.connect(self._on_gallery_destroyed)
        self._gallery.show()
        self._gallery.raise_()
        self._gallery.activateWindow()

    def toggle_gallery(self) -> None:
        if self._gallery is None or not self._gallery.isVisible():
            self.show_gallery()
        else:
            self._gallery.close()

    def show_settings(self) -> None:
        if self._settings_window is None:
            self._settings_window = SettingsWindow(self.settings, self.signals)
            self._settings_window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            self._settings_window.saved.connect(self._on_settings_saved)
            self._settings_window.destroyed.connect(self._on_settings_destroyed)
        self._settings_window.show()
        self._settings_window.raise_()
        self._settings_window.activateWindow()

    # -- capture flow: Lightshot-style overlay --------------------------------

    def _request_capture(self) -> None:
        if self._capture_overlay is not None:
            return  # already up
        background = self.screenshots.grab_desktop()
        overlay = CaptureOverlay(background, accent=self.settings.ui.accent)
        overlay.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        overlay.save_only.connect(self._on_capture_save_only)
        overlay.save_and_open.connect(self._on_capture_save_and_open)
        overlay.cancelled.connect(self._on_capture_cancelled)
        overlay.destroyed.connect(self._on_overlay_destroyed)
        self._capture_overlay = overlay
        overlay.show_over_desktop()

    def _on_capture_save_only(self, pixmap: QPixmap) -> None:
        record = self._persist_capture(pixmap)
        if record is not None:
            self.tray.notify("Screenshot saved", record.filename)

    def _on_capture_save_and_open(self, pixmap: QPixmap) -> None:
        record = self._persist_capture(pixmap)
        if record is None:
            return
        self.show_gallery()
        if self._gallery is not None:
            self._gallery.screenshots_panel.reload()
            self._gallery.screenshots_panel.select(record.id)

    def _persist_capture(self, pixmap: QPixmap):
        try:
            return self.screenshots.save_pixmap(pixmap)
        except Exception as exc:
            log.exception("save failed")
            self.tray.notify("Save failed", str(exc))
            return None

    def _on_capture_cancelled(self) -> None:
        pass

    # -- silent full-screen capture -------------------------------------------

    def _capture_fullscreen_silent(self) -> None:
        """Grab the whole (virtual) desktop and save it straight to the gallery
        — no region selector, no window. save_pixmap emits screenshot_captured,
        so an open gallery updates itself. Confirmation is either a neat corner
        pop-up (if enabled) or the system tray toast."""
        try:
            pixmap = self.screenshots.grab_desktop()
        except Exception as exc:
            log.exception("full-screen capture failed")
            self.tray.notify("Capture failed", str(exc))
            return
        record = self._persist_capture(pixmap)
        if record is None:
            return
        if self.settings.ui.capture_toast:
            self._show_capture_toast(record, pixmap)
        else:
            self.tray.notify("Screenshot saved", record.filename)

    def _show_capture_toast(self, record, pixmap: QPixmap) -> None:
        from .ui.toast import CaptureToast
        toast = CaptureToast(
            "Screenshot saved", record.filename, pixmap,
            duration_ms=int(round(float(self.settings.ui.capture_toast_seconds) * 1000)),
        )
        toast.clicked.connect(lambda rid=record.id: self._open_from_toast(rid))
        toast.closed.connect(lambda t=toast: self._toasts.remove(t) if t in self._toasts else None)
        self._toasts.append(toast)
        toast.show_toast()

    def _open_from_toast(self, screenshot_id: str) -> None:
        self.show_gallery()
        if self._gallery is not None:
            self._gallery.screenshots_panel.reload()
            self._gallery.screenshots_panel.select(screenshot_id)

    # -- settings-saved handling ----------------------------------------------

    def _on_settings_saved(self, new_settings: Settings) -> None:
        self.settings = new_settings
        save_settings(self.settings)
        self._apply_theme()
        self.hotkeys.reload(self.settings.hotkeys)
        self.thumbnails.set_size(self.settings.ui.thumbnail_px)
        self.screenshots.config = self.settings.screenshot
        self.screenshots.directory = self._ensured_screenshot_dir()
        self.screenshots.scan_directory()
        self.chat.set_context_chars_limit(self.settings.ai.context_chars_limit)
        # Push the theme change into the live gallery so cards restyle.
        from .ui.gallery.chat_panel import set_chat_theme
        set_chat_theme(self.settings.ui.theme)
        if self._gallery is not None:
            self._gallery.screenshots_panel.set_theme(self.settings.ui.theme)
            self._gallery.presets_panel.set_theme(self.settings.ui.theme)
            self._gallery._refresh_transcript()

    def _on_gallery_destroyed(self, *_) -> None:
        self._gallery = None

    def _on_settings_destroyed(self, *_) -> None:
        self._settings_window = None

    def _on_overlay_destroyed(self, *_) -> None:
        self._capture_overlay = None

    def _apply_theme(self) -> None:
        theme = Theme.resolve(self.settings.ui.theme, self.settings.ui.accent)
        apply_theme(self.qt_app, theme)

    def _build_provider(self) -> AIProvider:
        ai = self.settings.ai
        return AIProvider(
            base_url=ai.base_url,
            api_key=ai.api_key,
            model=ai.model,
            timeout=float(ai.timeout_seconds),
        )

    def _ensured_screenshot_dir(self) -> Path:
        p = Path(self.settings.resolved_screenshot_dir())
        p.mkdir(parents=True, exist_ok=True)
        return p
