"""Application menu bar for the gallery window.

A Photoshop/VS Code-style menu bar (File / Edit / View / Help) that lives as
its own row under the custom title bar. It is deliberately dumb: every item
emits a signal and the GalleryWindow wires those to the right handler (a panel
method, or an app-wide signal for capture / settings / quit). Adding a new
command is a two-liner here plus one connection in the window — the intended
growth path as the app gains tools.
"""

from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup
from PyQt6.QtWidgets import QMenu, QMenuBar, QWidget


class GalleryMenuBar(QMenuBar):
    # File
    capture_requested = pyqtSignal()
    open_folder_requested = pyqtSignal()
    settings_requested = pyqtSignal()
    quit_requested = pyqtSignal()
    # Edit (conversation / current screenshot — enabled only with a selection)
    clear_requested = pyqtSignal()
    compact_requested = pyqtSignal()
    rename_requested = pyqtSignal()
    delete_requested = pyqtSignal()
    # View
    view_mode_requested = pyqtSignal(str)   # "grid" | "list"
    refresh_requested = pyqtSignal()
    # Help
    about_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("GalleryMenuBar")
        # Actions that only make sense with a screenshot selected.
        self._screenshot_actions: list[QAction] = []
        self._build()

    # -- construction ----------------------------------------------------------

    def _build(self) -> None:
        file_menu = self.addMenu("&File")
        self._act(file_menu, "New Screenshot…", self.capture_requested.emit, "Ctrl+N")
        file_menu.addSeparator()
        self._act(file_menu, "Open Screenshots Folder", self.open_folder_requested.emit, "Ctrl+Shift+O")
        file_menu.addSeparator()
        self._act(file_menu, "Settings…", self.settings_requested.emit, "Ctrl+,")
        file_menu.addSeparator()
        self._act(file_menu, "Exit", self.quit_requested.emit, "Ctrl+Q")

        edit_menu = self.addMenu("&Edit")
        self._screenshot_actions += [
            self._act(edit_menu, "Clear Conversation", self.clear_requested.emit),
            self._act(edit_menu, "Compact Conversation", self.compact_requested.emit),
        ]
        edit_menu.addSeparator()
        self._screenshot_actions += [
            self._act(edit_menu, "Rename Screenshot…", self.rename_requested.emit),
            self._act(edit_menu, "Delete Screenshot", self.delete_requested.emit),
        ]

        view_menu = self.addMenu("&View")
        self._grid_action = self._act(
            view_menu, "Grid", lambda: self.view_mode_requested.emit("grid"), checkable=True)
        self._list_action = self._act(
            view_menu, "List", lambda: self.view_mode_requested.emit("list"), checkable=True)
        group = QActionGroup(self)
        group.setExclusive(True)
        group.addAction(self._grid_action)
        group.addAction(self._list_action)
        view_menu.addSeparator()
        self._act(view_menu, "Refresh", self.refresh_requested.emit, "F5")

        help_menu = self.addMenu("&Help")
        self._act(help_menu, "About ExplainShot", self.about_requested.emit)

    def _act(
        self,
        menu: QMenu,
        text: str,
        slot: Callable[[], None],
        shortcut: str | None = None,
        *,
        checkable: bool = False,
    ) -> QAction:
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(shortcut)
        action.setCheckable(checkable)
        action.triggered.connect(lambda _checked=False: slot())
        menu.addAction(action)
        return action

    # -- state sync (called by the window) -------------------------------------

    def set_screenshot_actions_enabled(self, enabled: bool) -> None:
        for action in self._screenshot_actions:
            action.setEnabled(enabled)

    def set_view_mode(self, mode: str) -> None:
        self._grid_action.setChecked(mode == "grid")
        self._list_action.setChecked(mode == "list")
