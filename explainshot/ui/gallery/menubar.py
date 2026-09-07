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

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QColor, QPainter, QPen
from PyQt6.QtWidgets import QApplication, QMenu, QMenuBar, QWidget


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
    # Emitted when the user presses Esc while keyboard-navigating the bar (with
    # no dropdown open) — the window uses it to move focus back to the content.
    exited = pyqtSignal()

    def __init__(self, accent: str = "#0067c0", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("GalleryMenuBar")
        self._accent = QColor(accent)
        # Index of the keyboard-highlighted top-level menu (-1 = not in keyboard
        # mode). We drive this ourselves: QMenuBar's setActiveAction pops the
        # menu open, which we don't want on mere focus.
        self._kb_current = -1
        # Actions that only make sense with a screenshot selected.
        self._screenshot_actions: list[QAction] = []
        self._build()

    # -- keyboard navigation (Tab-group) ---------------------------------------
    #
    # On focus we highlight a menu title (painted below) WITHOUT opening it;
    # Left/Right/Home/End move the highlight; Down/Enter/Space/Return open the
    # highlighted menu; Esc leaves; losing focus clears everything.

    def focusInEvent(self, event) -> None:  # type: ignore[override]
        # Fresh keyboard entry highlights the first menu. Returning from one of
        # our own popups (PopupFocusReason) keeps the current highlight.
        if self._kb_current < 0 and self.actions():
            self._kb_current = 0
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:  # type: ignore[override]
        # Leaving the bar for good (Tab away, click elsewhere) closes any open
        # dropdown and drops the highlight. A focus-out INTO our own popup
        # (PopupFocusReason) is how a menu opens, so leave that be.
        if event is None or event.reason() != Qt.FocusReason.PopupFocusReason:
            popup = QApplication.activePopupWidget()
            if isinstance(popup, QMenu):
                popup.close()
            self._kb_current = -1
            self.update()
        super().focusOutEvent(event)

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        key = event.key() if event else None
        acts = self.actions()
        if self._kb_current >= 0 and acts:
            if key in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Home, Qt.Key.Key_End):
                if key == Qt.Key.Key_Left:
                    self._kb_current = (self._kb_current - 1) % len(acts)
                elif key == Qt.Key.Key_Right:
                    self._kb_current = (self._kb_current + 1) % len(acts)
                elif key == Qt.Key.Key_Home:
                    self._kb_current = 0
                else:
                    self._kb_current = len(acts) - 1
                self.update()
                return
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
                # Open the highlighted menu (this is the one place we want the
                # popup). QMenuBar takes over navigation while it's open.
                self.setActiveAction(acts[self._kb_current])
                return
            if key == Qt.Key.Key_Escape:
                self._kb_current = -1
                self.update()
                self.exited.emit()
                return
        super().keyPressEvent(event)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        # Underline the keyboard-highlighted menu title (skip while a dropdown
        # is open — QMenuBar draws its own active highlight then).
        if self._kb_current < 0 or QApplication.activePopupWidget() is not None:
            return
        acts = self.actions()
        if not (0 <= self._kb_current < len(acts)):
            return
        rect = self.actionGeometry(acts[self._kb_current])
        painter = QPainter(self)
        pen = QPen(self._accent)
        pen.setWidth(2)
        painter.setPen(pen)
        y = rect.bottom() - 1
        painter.drawLine(rect.left() + 6, y, rect.right() - 6, y)

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
