"""Application object — owns the singletons and controls window lifecycle.

Replaces main_controller.py + ui_manager.py + optimized_main_controller.py
(a combined ~1600 lines). All the async signal marshalling that ran through
a custom EventBus, a per-tick QTimer, an event queue, then asyncio tasks —
gone. Qt signals + qasync do the job natively.
"""

from __future__ import annotations

import logging

from pathlib import Path

from PyQt6.QtCore import QObject, Qt
from PyQt6.QtWidgets import QApplication

from . import APP_NAME
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
from .ui.overlay import RegionSelector
from .ui.settings import SettingsWindow
from .ui.theme import Theme, apply_theme
from .ui.tray import Tray

log = logging.getLogger(__name__)


class Application(QObject):
    def __init__(self, qt_app: QApplication) -> None:
        super().__init__()
        self.qt_app = qt_app
        self.qt_app.setApplicationName(APP_NAME)
        self.qt_app.setQuitOnLastWindowClosed(False)  # tray keeps us alive
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
        self._region_selector: RegionSelector | None = None

        # Connect hotkeys — pynput fires on a background thread, Qt marshals
        # to the main thread via QueuedConnection automatically.
        self.signals.hotkey_capture_region.connect(self._request_capture)
        self.signals.hotkey_toggle_gallery.connect(self.toggle_gallery)
        self.signals.hotkey_open_settings.connect(self.show_settings)

    # -- lifecycle -------------------------------------------------------------

    def start(self) -> None:
        self.tray.show()
        self.hotkeys.start()

    def quit(self) -> None:
        self.hotkeys.stop()
        self.tray.hide()
        if self._gallery:
            self._gallery.close()
        if self._settings_window:
            self._settings_window.close()
        if self._region_selector:
            self._region_selector.close()
        self.db.close()
        self.qt_app.quit()

    # -- window commands -------------------------------------------------------

    def show_gallery(self) -> None:
        if self._gallery is None:
            self._gallery = GalleryWindow(
                settings=self.settings,
                signals=self.signals,
                screenshots=self.screenshots,
                thumbnails=self.thumbnails,
                presets=self.presets,
                history=self.history,
                provider_factory=self._build_provider,
            )
            self._gallery.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            self._gallery.destroyed.connect(self._on_gallery_destroyed)
        window = self._gallery
        window.show()
        window.raise_()
        window.activateWindow()

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

    def _request_capture(self) -> None:
        # Only one selector at a time.
        if self._region_selector is not None:
            self._region_selector.close()
        selector = RegionSelector(accent=self.settings.ui.accent)
        selector.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        selector.region_selected.connect(self._on_region_selected)
        selector.cancelled.connect(self._on_region_cancelled)
        selector.destroyed.connect(self._on_selector_destroyed)
        self._region_selector = selector
        selector.show_over_desktop()

    def _on_region_selected(self, region) -> None:
        try:
            record = self.screenshots.capture(region)
        except Exception as exc:
            log.exception("capture failed")
            self.tray.notify("Capture failed", str(exc))
            return
        self.tray.notify("Screenshot captured", record.filename)
        # Open the gallery pre-selected on the new screenshot.
        self.show_gallery()
        if self._gallery:
            self._gallery.screenshots_panel.select(record.id)

    def _on_region_cancelled(self) -> None:
        # Nothing to do — the widget hides itself.
        pass

    # -- signals plumbing ------------------------------------------------------

    def _on_settings_saved(self, new_settings: Settings) -> None:
        self.settings = new_settings
        save_settings(self.settings)
        self._apply_theme()
        self.hotkeys.reload(self.settings.hotkeys)
        self.thumbnails.set_size(self.settings.ui.thumbnail_px)
        self.screenshots.config = self.settings.screenshot
        self.screenshots.directory = self._ensured_screenshot_dir()
        self.screenshots.scan_directory()

    def _on_gallery_destroyed(self, *_) -> None:
        self._gallery = None

    def _on_settings_destroyed(self, *_) -> None:
        self._settings_window = None

    def _on_selector_destroyed(self, *_) -> None:
        self._region_selector = None

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
