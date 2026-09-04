"""Custom title bar for our frameless windows.

Behaviour we replicate from the native chrome:
  * click-drag from an empty part of the bar to move the window
  * double-click to toggle maximised
  * minimise / maximise / close buttons on the right

Drag and resize call into `windowHandle().startSystemMove()` /
`startSystemResize()` — the Wayland/Windows native path, so Windows-11
aero-snap ("drag to top" for maximise, "drag to edge" for tile) works
without any Win32 message plumbing.
"""

from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QMouseEvent, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from ..icons import app_icon


class _CaptionButton(QPushButton):
    """Windows-11 style caption button (44x32) with hover/press states.
    Uses the standard geometry so it feels like the OS."""

    def __init__(self, glyph: str, tooltip: str, *, danger: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(glyph, parent)
        self.setToolTip(tooltip)
        self.setObjectName("CaptionButton")
        self.setProperty("caption", True)
        if danger:
            self.setProperty("captionDanger", True)
        self.setFixedSize(46, 32)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)


class TitleBar(QFrame):
    """One-row bar: icon | title | spacer | min | max/restore | close.

    Emits `request_close` so the parent can decide whether to close (main
    window) or hide (a dialog that should live modally). Min/max operate
    on `window` directly."""

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
        self.setFixedHeight(36)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 0, 0)
        layout.setSpacing(8)

        icon_label = QLabel()
        icon_label.setFixedSize(16, 16)
        pixmap = app_icon().pixmap(16, 16)
        if not pixmap.isNull():
            icon_label.setPixmap(pixmap)
        layout.addWidget(icon_label)

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

        self._min_btn = _CaptionButton("–", "Minimise")   # en dash
        self._min_btn.clicked.connect(self._window.showMinimized)
        layout.addWidget(self._min_btn)

        self._max_btn = _CaptionButton("□", "Maximise")   # ☐
        self._max_btn.clicked.connect(self._toggle_max)
        if show_maximise:
            layout.addWidget(self._max_btn)
        else:
            self._max_btn.hide()

        self._close_btn = _CaptionButton("✕", "Close", danger=True)  # ✕
        self._close_btn.clicked.connect(self.request_close.emit)
        layout.addWidget(self._close_btn)

    # -- public tweaks ---------------------------------------------------------

    def add_extra(self, widget: QWidget) -> None:
        self._extras_layout.addWidget(widget)

    def set_title(self, title: str) -> None:
        self._title_label.setText(title)

    def refresh_max_glyph(self) -> None:
        """Call after showMaximized/showNormal to swap the glyph."""
        self._max_btn.setText("❐" if self._window.isMaximized() else "□")
        self._max_btn.setToolTip("Restore" if self._window.isMaximized() else "Maximise")

    # -- drag / double-click ---------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent | None) -> None:  # type: ignore[override]
        if event and event.button() == Qt.MouseButton.LeftButton:
            handle = self._window.windowHandle()
            if handle is not None:
                handle.startSystemMove()
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
