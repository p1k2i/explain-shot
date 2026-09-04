"""Custom title bar for our frameless windows.

Behaviour we replicate from the native chrome:
  * click-drag from an empty part of the bar to move the window
  * double-click to toggle maximised
  * right-click on the app icon shows a Windows-style system menu
  * minimise / maximise / close buttons on the right — 48x40, matching
    the Windows 11 chrome so they feel clickable

Drag and resize call into `windowHandle().startSystemMove()` /
`startSystemResize()` — the OS-native path, so Windows-11 aero-snap
("drag to top" for maximise, "drag to edge" for tile) works without
any Win32 message plumbing.
"""

from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QFont, QMouseEvent
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from ..icons import app_icon


# Windows fluent-chrome caption glyphs are in the Private Use Area of the
# Segoe MDL2 Assets / Segoe Fluent Icons fonts. Written as \u escapes so
# they survive round-trips through tools that mangle non-BMP text.
_GLYPH_MINIMISE = chr(0xE921)   # ChromeMinimize
_GLYPH_MAXIMISE = chr(0xE922)   # ChromeMaximize
_GLYPH_RESTORE = chr(0xE923)    # ChromeRestore
_GLYPH_CLOSE = chr(0xE8BB)      # ChromeClose


def _icon_font() -> QFont:
    """The font stack used by the caption buttons."""
    font = QFont()
    font.setFamilies([
        "Segoe Fluent Icons",
        "Segoe MDL2 Assets",
        "Segoe UI Symbol",
        "Segoe UI",
    ])
    font.setPixelSize(11)
    return font


class _CaptionButton(QPushButton):
    """Windows-11 style caption button (48x40)."""

    def __init__(self, glyph: str, tooltip: str, *, danger: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(glyph, parent)
        self.setToolTip(tooltip)
        self.setObjectName("CaptionButton")
        self.setProperty("caption", True)
        if danger:
            self.setProperty("captionDanger", True)
        self.setFixedSize(48, 40)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFont(_icon_font())


class _IconLabel(QLabel):
    """The app icon on the left of the title bar. Right-click opens a
    system menu with the standard window commands."""

    context_menu_requested = pyqtSignal(QPoint)

    def mousePressEvent(self, event: QMouseEvent | None) -> None:  # type: ignore[override]
        if event and event.button() == Qt.MouseButton.RightButton:
            self.context_menu_requested.emit(event.globalPosition().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)


class TitleBar(QFrame):
    """One-row bar: icon | title | spacer | min | max/restore | close."""

    request_close = pyqtSignal()

    def __init__(
        self,
        window: QWidget,
        *,
        title: str = "",
        show_maximise: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._window = window
        self.setObjectName("TitleBar")
        self.setFixedHeight(40)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 0, 0)
        layout.setSpacing(8)

        self._icon_label = _IconLabel()
        self._icon_label.setFixedSize(20, 20)
        self._icon_label.setCursor(Qt.CursorShape.PointingHandCursor)
        pixmap = app_icon().pixmap(20, 20)
        if not pixmap.isNull():
            self._icon_label.setPixmap(pixmap)
        self._icon_label.context_menu_requested.connect(self._show_system_menu)
        layout.addWidget(self._icon_label)

        self._title_label = QLabel(title)
        self._title_label.setObjectName("TitleBarTitle")
        layout.addWidget(self._title_label)

        layout.addStretch(1)

        # Slot for extra widgets (a status chip, model switcher, etc.)
        self._extras_host = QWidget()
        extras = QHBoxLayout(self._extras_host)
        extras.setContentsMargins(0, 0, 8, 0)
        extras.setSpacing(6)
        self._extras_layout = extras
        layout.addWidget(self._extras_host)

        self._min_btn = _CaptionButton(_GLYPH_MINIMISE, "Minimise")
        self._min_btn.clicked.connect(self._window.showMinimized)
        layout.addWidget(self._min_btn)

        self._max_btn = _CaptionButton(_GLYPH_MAXIMISE, "Maximise")
        self._max_btn.clicked.connect(self._toggle_max)
        if show_maximise:
            layout.addWidget(self._max_btn)
        else:
            self._max_btn.hide()

        self._close_btn = _CaptionButton(_GLYPH_CLOSE, "Close", danger=True)
        self._close_btn.clicked.connect(self.request_close.emit)
        layout.addWidget(self._close_btn)

    # -- public tweaks ---------------------------------------------------------

    def add_extra(self, widget: QWidget) -> None:
        self._extras_layout.addWidget(widget)

    def set_title(self, title: str) -> None:
        self._title_label.setText(title)

    def refresh_max_glyph(self) -> None:
        """Swap the glyph after showMaximized/showNormal."""
        if self._window.isMaximized():
            self._max_btn.setText(_GLYPH_RESTORE)
            self._max_btn.setToolTip("Restore")
        else:
            self._max_btn.setText(_GLYPH_MAXIMISE)
            self._max_btn.setToolTip("Maximise")

    # -- drag / double-click ---------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent | None) -> None:  # type: ignore[override]
        if event and event.button() == Qt.MouseButton.LeftButton:
            handle = self._window.windowHandle()
            if handle is not None:
                handle.startSystemMove()
                event.accept()
                return
        if event and event.button() == Qt.MouseButton.RightButton:
            self._show_system_menu(event.globalPosition().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent | None) -> None:  # type: ignore[override]
        if event and event.button() == Qt.MouseButton.LeftButton:
            self._toggle_max()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _toggle_max(self) -> None:
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()
        self.refresh_max_glyph()

    # -- system menu -----------------------------------------------------------

    def _show_system_menu(self, global_pos: QPoint) -> None:
        menu = QMenu(self)

        restore = QAction("Restore", menu)
        restore.setEnabled(self._window.isMaximized())
        restore.triggered.connect(self._window.showNormal)
        menu.addAction(restore)

        move = QAction("Move", menu)
        move.setEnabled(not self._window.isMaximized())

        def _start_move() -> None:
            handle = self._window.windowHandle()
            if handle is not None:
                handle.startSystemMove()

        move.triggered.connect(_start_move)
        menu.addAction(move)

        size = QAction("Size", menu)
        size.setEnabled(not self._window.isMaximized())

        def _start_resize() -> None:
            handle = self._window.windowHandle()
            if handle is not None:
                handle.startSystemResize(Qt.Edge.BottomEdge | Qt.Edge.RightEdge)

        size.triggered.connect(_start_resize)
        menu.addAction(size)

        minimise = QAction("Minimise", menu)
        minimise.triggered.connect(self._window.showMinimized)
        menu.addAction(minimise)

        maximise = QAction("Maximise", menu)
        maximise.setEnabled(not self._window.isMaximized())
        maximise.triggered.connect(self._window.showMaximized)
        menu.addAction(maximise)

        menu.addSeparator()

        close = QAction("Close\tAlt+F4", menu)
        close.triggered.connect(self.request_close.emit)
        menu.addAction(close)

        menu.exec(global_pos)
