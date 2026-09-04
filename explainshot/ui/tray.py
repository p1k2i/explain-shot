"""System tray. Uses Qt's QSystemTrayIcon — pystray ran the icon in a
detached daemon thread that made shutdown flaky and prevented calling
Qt code from the menu handlers. QSystemTrayIcon lives on the Qt main
thread, so signals connect naturally.
"""

from __future__ import annotations

import logging
from typing import Callable

from PyQt6.QtCore import QObject
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

from .. import APP_NAME, APP_VERSION
from ..core.signals import AppSignals
from .icons import app_icon

log = logging.getLogger(__name__)


class Tray(QObject):
    def __init__(
        self,
        signals: AppSignals,
        *,
        on_capture: Callable[[], None],
        on_show_gallery: Callable[[], None],
        on_show_settings: Callable[[], None],
        on_quit: Callable[[], None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.signals = signals
        self._on_capture = on_capture
        self._on_show_gallery = on_show_gallery
        self._on_show_settings = on_show_settings
        self._on_quit = on_quit

        self.icon = QSystemTrayIcon(app_icon(), parent=self)
        self.icon.setToolTip(f"{APP_NAME} {APP_VERSION}")

        self._build_menu()
        self.icon.activated.connect(self._on_activated)

    def show(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            log.warning("system tray not available on this platform")
            return
        self.icon.show()

    def hide(self) -> None:
        self.icon.hide()

    def notify(self, title: str, message: str) -> None:
        self.icon.showMessage(title, message, app_icon(), 3000)

    # -- internal --------------------------------------------------------------

    def _build_menu(self) -> None:
        menu = QMenu()

        capture = QAction("Capture region\tCtrl+Shift+S", menu)
        capture.triggered.connect(self._on_capture)

        gallery = QAction("Open gallery", menu)
        gallery.triggered.connect(self._on_show_gallery)

        settings = QAction("Settings…", menu)
        settings.triggered.connect(self._on_show_settings)

        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(self._on_quit)

        menu.addAction(capture)
        menu.addAction(gallery)
        menu.addSeparator()
        menu.addAction(settings)
        menu.addSeparator()
        menu.addAction(quit_action)

        self.icon.setContextMenu(menu)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # Double-click opens the gallery — the common expected behaviour.
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._on_show_gallery()
