"""Custom title bar for our frameless windows.

Behaviour we replicate from the native chrome:
  * click-drag from an empty part of the bar to move the window
  * double-click to toggle maximised
  * right-click on the app icon (or empty bar area) shows a Windows-style
    system menu (Restore / Move / Size / Minimise / Maximise / Close)
  * minimise / maximise / close caption buttons on the right, 48x40, so
    they feel clickable

Drag and resize call into ``windowHandle().startSystemMove()`` /
``startSystemResize()`` — the OS-native path, so Windows-11 aero-snap
("drag to top" for maximise, "drag to edge" for tile) works without any
Win32 message plumbing.

Caption glyphs are painted as vector shapes rather than text. An earlier
version relied on the Segoe MDL2 Assets / Segoe Fluent Icons font, but
those glyphs live in the Private Use Area and render as tofu on systems
where those fonts aren't installed. Painting the shapes ourselves means
the buttons look identical on any platform, any font situation.
"""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QMouseEvent, QPainter, QPaintEvent, QPen
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


CAPTION_MIN = "min"
CAPTION_MAX = "max"
CAPTION_RESTORE = "restore"
CAPTION_CLOSE = "close"


class _CaptionButton(QPushButton):
    """Windows-11-style caption button. Fixed 48x40 with a self-painted glyph.

    The QPushButton still handles hit-testing, hover, and the QSS
    background/foreground — we only override the paint step to draw the
    glyph as a vector on top of the button surface.
    """

    def __init__(self, glyph: str, tooltip: str, *, danger: bool = False, parent: QWidget | None = None) -> None:
        # No text — the glyph is painted below. We keep the button label
        # empty so QSS `color` still controls the pen we use.
        super().__init__("", parent)
        self.setToolTip(tooltip)
        self.setObjectName("CaptionButton")
        self.setProperty("caption", True)
        if danger:
            self.setProperty("captionDanger", True)
        self.setFixedSize(48, 40)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._glyph = glyph

    def set_glyph(self, glyph: str) -> None:
        if glyph != self._glyph:
            self._glyph = glyph
            self.update()

    def paintEvent(self, event: QPaintEvent | None) -> None:  # type: ignore[override]
        # Base class paints the QSS background + hover/press states.
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Centred 10x10 mark, matching Windows chrome sizing.
        rect = self.rect()
        cx = rect.width() / 2
        cy = rect.height() / 2
        size = 10.0
        r = QRectF(cx - size / 2, cy - size / 2, size, size)

        # Match text colour so hover-invert on the close button (white on red)
        # picks up automatically.
        color = self.palette().buttonText().color()
        if not color.isValid() or color.alpha() == 0:
            color = QColor("#e5e5e5")
        pen = QPen(color)
        pen.setWidthF(1.2)
        pen.setCapStyle(Qt.PenCapStyle.SquareCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if self._glyph == CAPTION_MIN:
            y = r.center().y()
            painter.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
        elif self._glyph == CAPTION_MAX:
            painter.drawRect(r)
        elif self._glyph == CAPTION_RESTORE:
            # Two overlapping squares: an inner "front" square offset
            # down-left, plus three sides of a back square tucked behind it.
            inner = QRectF(r.left(), r.top() + 2, r.width() - 2, r.height() - 2)
            painter.drawRect(inner)
            back_left = r.left() + 2
            back_top = r.top()
            painter.drawLine(QPointF(back_left, back_top), QPointF(r.right(), back_top))
            painter.drawLine(QPointF(r.right(), back_top), QPointF(r.right(), inner.top()))
            painter.drawLine(QPointF(back_left, back_top), QPointF(back_left, inner.top()))
        elif self._glyph == CAPTION_CLOSE:
            painter.drawLine(r.topLeft(), r.bottomRight())
            painter.drawLine(r.topRight(), r.bottomLeft())


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
        center_title: bool = False,
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

        # Slot for an in-titlebar menu bar (VS Code style). Sits right after the
        # icon; sized to its content so the rest of the bar stays draggable.
        # Transparent so it doesn't paint over the title bar's bottom separator
        # (the global `QWidget { background }` rule would otherwise fill it).
        self._menu_host = QWidget()
        self._menu_host.setObjectName("TitleBarMenuHost")
        self._menu_host.setStyleSheet("#TitleBarMenuHost { background: transparent; }")
        self._menu_layout = QHBoxLayout(self._menu_host)
        self._menu_layout.setContentsMargins(4, 0, 0, 0)
        self._menu_layout.setSpacing(0)
        layout.addWidget(self._menu_host)

        # When a menu bar is present we centre the title between the menu and the
        # caption buttons (again, VS Code style); otherwise it stays left-aligned.
        if center_title:
            layout.addStretch(1)
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

        self._min_btn = _CaptionButton(CAPTION_MIN, "Minimise")
        self._min_btn.clicked.connect(self._window.showMinimized)
        layout.addWidget(self._min_btn)

        self._max_btn = _CaptionButton(CAPTION_MAX, "Maximise")
        self._max_btn.clicked.connect(self._toggle_max)
        if show_maximise:
            layout.addWidget(self._max_btn)
        else:
            self._max_btn.hide()

        self._close_btn = _CaptionButton(CAPTION_CLOSE, "Close", danger=True)
        self._close_btn.clicked.connect(self.request_close.emit)
        layout.addWidget(self._close_btn)

    # -- public tweaks ---------------------------------------------------------

    def add_extra(self, widget: QWidget) -> None:
        self._extras_layout.addWidget(widget)

    def add_menu_bar(self, menu_bar: QWidget) -> None:
        """Embed a QMenuBar into the title bar row (VS Code style)."""
        from PyQt6.QtWidgets import QSizePolicy as _SP
        menu_bar.setSizePolicy(_SP.Policy.Maximum, _SP.Policy.Preferred)
        # Keep the bar shorter than the title bar and vertically centred, so its
        # (opaque) panel never paints over the title bar's 1px bottom separator.
        menu_bar.setFixedHeight(30)
        self._menu_layout.addWidget(menu_bar, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_title(self, title: str) -> None:
        self._title_label.setText(title)

    def refresh_max_glyph(self) -> None:
        """Swap the glyph after showMaximized/showNormal."""
        if self._window.isMaximized():
            self._max_btn.set_glyph(CAPTION_RESTORE)
            self._max_btn.setToolTip("Restore")
        else:
            self._max_btn.set_glyph(CAPTION_MAX)
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
