"""Lightshot-style fullscreen capture overlay.

One widget covers the entire virtual desktop and hosts the whole capture
flow: pick the region, resize/move it, annotate it, commit or cancel.

State model
-----------
The overlay is always in one of three states::

    IDLE            no selection yet — dragging creates one
    EDITING         a selection exists and can be resized / moved / drawn on
    DRAWING         a drawing tool is active; drags inside create annotations

Interaction inside EDITING is driven by hit-testing the pointer against the
eight resize handles, the selection interior (move), and the toolbox
(drag-to-move). The default cursor tool is the "select" tool — the
handles/interior remain interactive. Once the user picks a drawing tool
from the toolbox, dragging inside the selection creates annotations instead.

Rendering
---------
We ask the ScreenshotService to hand us a QPixmap of the full desktop up
front. The overlay paints that dimmed everywhere, then re-paints it bright
inside the selection so the user sees exactly what will be captured (and
so pixel-based tools like the blur can read the real underlying image).

The overlay itself is opaque — no ``WA_TranslucentBackground`` — because
child widgets (the toolbox) inside translucent parents composite poorly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from PyQt6.QtCore import QLineF, QPoint, QPointF, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QGuiApplication,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
    QPolygonF,
)
from PyQt6.QtWidgets import (
    QButtonGroup,
    QColorDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...capture.models import CaptureRegion

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HANDLE_SIZE = 10
HANDLE_HIT = 14              # slightly larger hit target than draw size
_HANDLE_NAMES = ("nw", "n", "ne", "e", "se", "s", "sw", "w")

TOOL_SELECT = "select"
TOOL_RECT = "rectangle"
TOOL_ELLIPSE = "ellipse"
TOOL_ARROW = "arrow"
TOOL_DRAW = "freehand"
TOOL_TEXT = "text"
TOOL_BLUR = "blur"

_DRAW_TOOLS = {TOOL_RECT, TOOL_ELLIPSE, TOOL_ARROW, TOOL_DRAW, TOOL_TEXT, TOOL_BLUR}


# ---------------------------------------------------------------------------
# Annotation ops
# ---------------------------------------------------------------------------


@dataclass
class _Op:
    tool: str
    color: QColor
    width: int
    start: QPointF = field(default_factory=QPointF)
    end: QPointF = field(default_factory=QPointF)
    points: list[QPointF] = field(default_factory=list)
    text: str = ""


# ---------------------------------------------------------------------------
# Toolbox
# ---------------------------------------------------------------------------


class _Toolbox(QFrame):
    """Compact floating toolbar shown next to the selection.

    Emits tool / colour / width changes plus undo / redo / cancel and the
    two save variants. The overlay handles positioning; users can drag the
    toolbox by any non-button area and it stops auto-positioning after that.
    """

    tool_changed = pyqtSignal(str)
    color_changed = pyqtSignal(QColor)
    width_changed = pyqtSignal(int)
    undo_requested = pyqtSignal()
    redo_requested = pyqtSignal()
    cancel_requested = pyqtSignal()
    save_only_requested = pyqtSignal()
    save_and_open_requested = pyqtSignal()
    dragged = pyqtSignal(QPoint)   # new top-left after user drag

    def __init__(self, accent: QColor, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CaptureToolbox")
        # Standalone visual container inside the opaque overlay.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(_TOOLBOX_QSS)
        self._current_color = QColor(accent)

        row = QHBoxLayout(self)
        row.setContentsMargins(6, 6, 6, 6)
        row.setSpacing(4)

        # Grip: click-drag to reposition the toolbox.
        self._grip = QLabel("⋮⋮")
        self._grip.setObjectName("Grip")
        self._grip.setCursor(Qt.CursorShape.SizeAllCursor)
        self._grip.setFixedWidth(14)
        row.addWidget(self._grip)

        # Tool buttons
        self._tool_group = QButtonGroup(self)
        self._tool_group.setExclusive(True)
        for tool_id, glyph, tooltip in (
            (TOOL_SELECT,  "◱", "Select / resize the region"),
            (TOOL_RECT,    "▭", "Rectangle"),
            (TOOL_ELLIPSE, "◯", "Ellipse"),
            (TOOL_ARROW,   "➤", "Arrow"),
            (TOOL_DRAW,    "✎", "Freehand"),
            (TOOL_TEXT,    "T", "Text"),
            (TOOL_BLUR,    "▨", "Blur / pixelate"),
        ):
            btn = QToolButton()
            btn.setText(glyph)
            btn.setToolTip(tooltip)
            btn.setCheckable(True)
            btn.setFixedSize(28, 28)
            btn.setProperty("toolId", tool_id)
            btn.clicked.connect(lambda _=None, t=tool_id: self.tool_changed.emit(t))
            self._tool_group.addButton(btn)
            row.addWidget(btn)
            if tool_id == TOOL_SELECT:
                btn.setChecked(True)

        row.addWidget(_Separator())

        # Colour
        self._color_btn = QToolButton()
        self._color_btn.setFixedSize(24, 24)
        self._color_btn.setToolTip("Colour")
        self._color_btn.clicked.connect(self._pick_color)
        self._apply_color_swatch()
        row.addWidget(self._color_btn)

        # Width
        self._width = QSpinBox()
        self._width.setRange(1, 24)
        self._width.setValue(3)
        self._width.setFixedWidth(48)
        self._width.setToolTip("Line width")
        self._width.valueChanged.connect(self.width_changed.emit)
        row.addWidget(self._width)

        row.addWidget(_Separator())

        # Undo / Redo
        undo_btn = self._icon_btn("↶", "Undo (Ctrl+Z)")
        undo_btn.clicked.connect(self.undo_requested.emit)
        row.addWidget(undo_btn)
        redo_btn = self._icon_btn("↷", "Redo (Ctrl+Y)")
        redo_btn.clicked.connect(self.redo_requested.emit)
        row.addWidget(redo_btn)

        row.addWidget(_Separator())

        # Cancel
        cancel_btn = self._icon_btn("✕", "Cancel (Esc)", danger=True)
        cancel_btn.clicked.connect(self.cancel_requested.emit)
        row.addWidget(cancel_btn)

        # Save (silent) — floppy glyph
        save_btn = QPushButton("Save")
        save_btn.setToolTip("Save to gallery")
        save_btn.setProperty("chip", True)
        save_btn.clicked.connect(self.save_only_requested.emit)
        row.addWidget(save_btn)

        # Save + open gallery — accent primary action.
        # `&&` because Qt otherwise eats a single `&` as the button mnemonic.
        save_open = QPushButton("Save && open")
        save_open.setToolTip("Save and open the gallery")
        save_open.setObjectName("PrimaryButton")
        save_open.clicked.connect(self.save_and_open_requested.emit)
        row.addWidget(save_open)

        self.adjustSize()
        self._drag_offset: QPoint | None = None
        self._grip.installEventFilter(self)

    # -- helpers ---------------------------------------------------------------

    def _icon_btn(self, glyph: str, tooltip: str, *, danger: bool = False) -> QToolButton:
        btn = QToolButton()
        btn.setText(glyph)
        btn.setToolTip(tooltip)
        btn.setFixedSize(28, 28)
        if danger:
            btn.setProperty("danger", True)
        return btn

    def _pick_color(self) -> None:
        chosen = QColorDialog.getColor(self._current_color, self, "Annotation colour")
        if chosen.isValid():
            self._current_color = chosen
            self._apply_color_swatch()
            self.color_changed.emit(chosen)

    def _apply_color_swatch(self) -> None:
        c = self._current_color.name()
        self._color_btn.setStyleSheet(
            f"QToolButton{{background:{c};"
            "border:1px solid rgba(255,255,255,0.35);border-radius:4px;}"
        )

    # -- dragging by the grip -------------------------------------------------

    def eventFilter(self, obj, event) -> bool:  # type: ignore[override]
        if obj is self._grip and event is not None:
            t = event.type().value if hasattr(event.type(), "value") else event.type()
            if event.type().name == "MouseButtonPress":
                self._drag_offset = event.pos() + self._grip.pos()
                return True
            if event.type().name == "MouseMove" and self._drag_offset is not None:
                parent = self.parentWidget()
                if parent is not None:
                    global_pos = self._grip.mapToGlobal(event.pos())
                    new_top_left = parent.mapFromGlobal(global_pos) - self._drag_offset
                    self.dragged.emit(new_top_left)
                return True
            if event.type().name == "MouseButtonRelease":
                self._drag_offset = None
                return True
        return False


class _Separator(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setFrameShape(QFrame.Shape.VLine)
        self.setStyleSheet("color: rgba(255,255,255,0.15);")
        self.setFixedWidth(1)


_TOOLBOX_QSS = """
QFrame#CaptureToolbox {
    background: #2b2b2b;
    border: 1px solid #444;
    border-radius: 10px;
}
QFrame#CaptureToolbox QLabel {
    background: transparent;
    color: #d7d7d7;
    font-size: 13px;
}
QFrame#CaptureToolbox QLabel#Grip {
    color: #888;
    padding: 0 2px;
}
QFrame#CaptureToolbox QToolButton {
    background: transparent;
    color: #e0e0e0;
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 0;
    font-size: 14px;
}
QFrame#CaptureToolbox QToolButton:hover {
    background: #3a3a3a;
    border-color: #555;
}
QFrame#CaptureToolbox QToolButton:checked {
    background: #0067c0;
    color: white;
    border-color: #0067c0;
}
QFrame#CaptureToolbox QToolButton[danger="true"]:hover {
    background: #c94040;
    color: white;
    border-color: #c94040;
}
QFrame#CaptureToolbox QSpinBox {
    background: #1e1e1e;
    color: #e0e0e0;
    border: 1px solid #444;
    border-radius: 4px;
    padding: 2px 4px;
}
QFrame#CaptureToolbox QPushButton {
    background: #383838;
    color: #e5e5e5;
    border: 1px solid #4a4a4a;
    border-radius: 4px;
    padding: 4px 12px;
}
QFrame#CaptureToolbox QPushButton:hover {
    background: #454545;
    border-color: #5a5a5a;
}
QFrame#CaptureToolbox QPushButton#PrimaryButton {
    background: #0067c0;
    color: white;
    border-color: #0067c0;
}
QFrame#CaptureToolbox QPushButton#PrimaryButton:hover {
    background: #005ba1;
    border-color: #005ba1;
}
"""


# ---------------------------------------------------------------------------
# The overlay
# ---------------------------------------------------------------------------


class CaptureOverlay(QWidget):
    """Fullscreen Lightshot-style capture surface.

    Emits ``save_only`` or ``save_and_open`` with the final QPixmap. Emits
    ``cancelled`` when the user aborts.
    """

    save_only = pyqtSignal(QPixmap)
    save_and_open = pyqtSignal(QPixmap)
    cancelled = pyqtSignal()

    def __init__(self, background: QPixmap, accent: str = "#0067c0", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._background = background
        self._accent = QColor(accent)

        # Frameless top-level. Opaque so children (toolbox) composite cleanly.
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # State
        self._state = "idle"
        self._selection: QRect | None = None
        self._drag_action: str | None = None  # "create" | "move" | "resize-<name>" | "draw"
        self._drag_start: QPoint = QPoint()
        self._selection_at_drag_start: QRect | None = None

        # Drawing tools
        self._tool = TOOL_SELECT
        self._color = QColor(accent)
        self._width = 3
        self._ops: list[_Op] = []
        self._redo: list[_Op] = []
        self._active_op: _Op | None = None

        # Toolbox (auto-positioned until the user moves it)
        self._toolbox = _Toolbox(self._accent, parent=self)
        self._toolbox_manual_pos = False
        self._toolbox.hide()
        self._toolbox.tool_changed.connect(self._on_tool_changed)
        self._toolbox.color_changed.connect(self._on_color_changed)
        self._toolbox.width_changed.connect(self._on_width_changed)
        self._toolbox.undo_requested.connect(self._undo)
        self._toolbox.redo_requested.connect(self._redo_op)
        self._toolbox.cancel_requested.connect(self._cancel)
        self._toolbox.save_only_requested.connect(self._commit_save_only)
        self._toolbox.save_and_open_requested.connect(self._commit_save_and_open)
        self._toolbox.dragged.connect(self._on_toolbox_dragged)

    # -- public ----------------------------------------------------------------

    def show_over_desktop(self) -> None:
        geo = _virtual_desktop_geometry()
        self.setGeometry(geo)
        # Background pixmap coordinates match desktop coordinates minus the
        # geometry origin — usually 0 on single-monitor setups, negative when
        # there is a monitor to the left of the primary.
        self._geometry_origin = geo.topLeft()
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    # -- painting --------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent | None) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Dim wash of the real desktop
        p.drawPixmap(0, 0, self._background)
        p.fillRect(self.rect(), QColor(0, 0, 0, 120))

        if self._selection is not None:
            sel = self._selection
            # Restore full brightness inside the selection
            p.drawPixmap(sel, self._background, sel)
            # Annotations painted only inside the selection using clipping
            p.save()
            p.setClipRect(sel)
            for op in self._ops:
                self._paint_op(p, op)
            if self._active_op is not None:
                self._paint_op(p, self._active_op)
            p.restore()
            # Border
            pen = QPen(self._accent)
            pen.setWidth(1)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(sel)
            # Handles (only in select mode; still hit-testable in draw modes
            # but we hide them visually so they don't compete with annotations).
            if self._tool == TOOL_SELECT:
                p.setBrush(self._accent)
                p.setPen(QPen(QColor(255, 255, 255, 220), 1))
                for point in self._handle_positions().values():
                    p.drawRect(
                        QRect(
                            point.x() - HANDLE_SIZE // 2,
                            point.y() - HANDLE_SIZE // 2,
                            HANDLE_SIZE,
                            HANDLE_SIZE,
                        )
                    )
            # Dimensions label
            self._paint_dimensions(p, sel)

    def _paint_dimensions(self, p: QPainter, sel: QRect) -> None:
        text = f"{sel.width()} × {sel.height()}"
        font = QFont("Segoe UI", 10)
        p.setFont(font)
        metrics = p.fontMetrics()
        text_width = metrics.horizontalAdvance(text)
        label_rect = QRect(sel.left(), sel.top() - 24, text_width + 12, 20)
        if label_rect.top() < 4:  # Not enough room above — nudge inside
            label_rect.moveTop(sel.top() + 6)
        p.fillRect(label_rect, QColor(0, 0, 0, 180))
        p.setPen(QColor(255, 255, 255))
        p.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, text)

    def _paint_op(self, p: QPainter, op: _Op) -> None:
        pen = QPen(op.color)
        pen.setWidth(op.width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        if op.tool == TOOL_RECT:
            p.drawRect(_rect_from(op.start, op.end))
        elif op.tool == TOOL_ELLIPSE:
            p.drawEllipse(_rect_from(op.start, op.end))
        elif op.tool == TOOL_ARROW:
            _draw_arrow(p, op.start, op.end, op.color, op.width)
        elif op.tool == TOOL_DRAW:
            if len(op.points) >= 2:
                for a, b in zip(op.points, op.points[1:]):
                    p.drawLine(a, b)
        elif op.tool == TOOL_TEXT:
            font = QFont("Segoe UI", max(10, op.width * 4))
            p.setFont(font)
            p.setPen(op.color)
            p.drawText(op.start, op.text)
        elif op.tool == TOOL_BLUR:
            rect = _rect_from(op.start, op.end).toRect().normalized()
            rect = rect.intersected(self._background.rect())
            if rect.width() > 0 and rect.height() > 0:
                region = self._background.copy(rect)
                small = region.scaled(
                    max(1, rect.width() // 12),
                    max(1, rect.height() // 12),
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                blurred = small.scaled(
                    rect.size(),
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                p.drawPixmap(rect.topLeft(), blurred)

    # -- events ----------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent | None) -> None:  # type: ignore[override]
        if event is None:
            return
        if event.button() == Qt.MouseButton.RightButton:
            self._cancel()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.pos()
        self._drag_start = pos

        if self._selection is None:
            self._drag_action = "create"
            self._selection = QRect(pos, pos)
            self._toolbox_manual_pos = False
            self.update()
            return

        # Selection exists. What did we hit?
        handle = self._hit_handle(pos)
        if handle is not None and self._tool == TOOL_SELECT:
            self._drag_action = f"resize-{handle}"
            self._selection_at_drag_start = QRect(self._selection)
            return
        if self._tool == TOOL_SELECT and self._selection.contains(pos):
            self._drag_action = "move"
            self._selection_at_drag_start = QRect(self._selection)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if self._tool in _DRAW_TOOLS and self._selection.contains(pos):
            self._begin_drawing(pos)
            return
        # Otherwise: start a fresh selection where the user clicked.
        self._drag_action = "create"
        self._selection = QRect(pos, pos)
        self._ops.clear()
        self._redo.clear()
        self._toolbox.hide()
        self._toolbox_manual_pos = False
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent | None) -> None:  # type: ignore[override]
        if event is None:
            return
        pos = event.pos()
        if self._drag_action is None:
            self._update_cursor(pos)
            return
        if self._drag_action == "create":
            self._selection = QRect(self._drag_start, pos).normalized()
            self.update()
            return
        if self._drag_action.startswith("resize-"):
            handle = self._drag_action.split("-", 1)[1]
            self._selection = _resize(self._selection_at_drag_start or self._selection, handle, pos)
            self.update()
            return
        if self._drag_action == "move":
            delta = pos - self._drag_start
            if self._selection_at_drag_start is not None:
                self._selection = self._selection_at_drag_start.translated(delta)
                # Keep it on-screen
                self._selection = self._selection.intersected(self.rect())
            self.update()
            return
        if self._drag_action == "draw" and self._active_op is not None:
            self._active_op.end = QPointF(pos)
            if self._active_op.tool == TOOL_DRAW:
                self._active_op.points.append(QPointF(pos))
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent | None) -> None:  # type: ignore[override]
        if event is None or event.button() != Qt.MouseButton.LeftButton:
            return
        action = self._drag_action
        self._drag_action = None
        self.setCursor(Qt.CursorShape.CrossCursor)
        if action == "create":
            self._normalise_selection()
            self._enter_editing()
            return
        if action == "move" or (action is not None and action.startswith("resize-")):
            self._normalise_selection()
            self._reposition_toolbox()
            self.update()
            return
        if action == "draw" and self._active_op is not None:
            if self._is_meaningful_op(self._active_op):
                self._ops.append(self._active_op)
                self._redo.clear()
            self._active_op = None
            self.update()

    def keyPressEvent(self, event: QKeyEvent | None) -> None:  # type: ignore[override]
        if event is None:
            return
        key = event.key()
        mods = event.modifiers()
        if key == Qt.Key.Key_Escape:
            self._cancel()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self._selection is not None:
                self._commit_save_and_open()
            return
        if mods & Qt.KeyboardModifier.ControlModifier:
            if key == Qt.Key.Key_Z:
                self._undo()
                return
            if key == Qt.Key.Key_Y:
                self._redo_op()
                return
            if key == Qt.Key.Key_S:
                if self._selection is not None:
                    self._commit_save_only()
                return

    # -- selection helpers -----------------------------------------------------

    def _handle_positions(self) -> dict[str, QPoint]:
        assert self._selection is not None
        r = self._selection
        cx = (r.left() + r.right()) // 2
        cy = (r.top() + r.bottom()) // 2
        return {
            "nw": QPoint(r.left(), r.top()),
            "n":  QPoint(cx, r.top()),
            "ne": QPoint(r.right(), r.top()),
            "e":  QPoint(r.right(), cy),
            "se": QPoint(r.right(), r.bottom()),
            "s":  QPoint(cx, r.bottom()),
            "sw": QPoint(r.left(), r.bottom()),
            "w":  QPoint(r.left(), cy),
        }

    def _hit_handle(self, pos: QPoint) -> str | None:
        if self._selection is None:
            return None
        for name, point in self._handle_positions().items():
            hit = QRect(
                point.x() - HANDLE_HIT // 2,
                point.y() - HANDLE_HIT // 2,
                HANDLE_HIT,
                HANDLE_HIT,
            )
            if hit.contains(pos):
                return name
        return None

    def _update_cursor(self, pos: QPoint) -> None:
        if self._selection is None:
            self.setCursor(Qt.CursorShape.CrossCursor)
            return
        handle = self._hit_handle(pos)
        if handle is not None and self._tool == TOOL_SELECT:
            self.setCursor(_HANDLE_CURSORS[handle])
            return
        if self._tool == TOOL_SELECT and self._selection.contains(pos):
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            return
        if self._tool in _DRAW_TOOLS and self._selection.contains(pos):
            cursor = Qt.CursorShape.IBeamCursor if self._tool == TOOL_TEXT else Qt.CursorShape.CrossCursor
            self.setCursor(cursor)
            return
        self.setCursor(Qt.CursorShape.CrossCursor)

    def _normalise_selection(self) -> None:
        if self._selection is None:
            return
        self._selection = self._selection.normalized().intersected(self.rect())

    def _enter_editing(self) -> None:
        if self._selection is None or self._selection.width() < 4 or self._selection.height() < 4:
            self._selection = None
            self.update()
            return
        self._state = "editing"
        self._reposition_toolbox()
        self._toolbox.show()
        self._toolbox.raise_()
        self.update()

    def _reposition_toolbox(self) -> None:
        if self._toolbox_manual_pos or self._selection is None:
            return
        self._toolbox.adjustSize()
        tb = self._toolbox.size()
        sel = self._selection
        margin = 8
        # Prefer below the selection, right-aligned.
        x = min(sel.right() - tb.width(), self.width() - tb.width() - 4)
        x = max(x, 4)
        y = sel.bottom() + margin
        if y + tb.height() > self.height() - 4:
            # No room below — try above.
            y = sel.top() - tb.height() - margin
            if y < 4:
                # No room either side. Sit at the top-right corner of the selection.
                y = sel.top() + margin
        self._toolbox.move(x, y)

    def _on_toolbox_dragged(self, new_top_left: QPoint) -> None:
        self._toolbox_manual_pos = True
        new_top_left.setX(max(0, min(new_top_left.x(), self.width() - self._toolbox.width())))
        new_top_left.setY(max(0, min(new_top_left.y(), self.height() - self._toolbox.height())))
        self._toolbox.move(new_top_left)

    # -- tool state ------------------------------------------------------------

    def _on_tool_changed(self, tool: str) -> None:
        self._tool = tool
        self.update()

    def _on_color_changed(self, color: QColor) -> None:
        self._color = color

    def _on_width_changed(self, width: int) -> None:
        self._width = max(1, width)

    def _begin_drawing(self, pos: QPoint) -> None:
        self._drag_action = "draw"
        if self._tool == TOOL_TEXT:
            text, ok = QInputDialog.getText(self, "Add text", "Text:")
            self._drag_action = None
            if not ok or not text:
                return
            self._ops.append(
                _Op(tool=TOOL_TEXT, color=self._color, width=self._width, start=QPointF(pos), text=text)
            )
            self._redo.clear()
            self.update()
            return
        op = _Op(tool=self._tool, color=self._color, width=self._width, start=QPointF(pos), end=QPointF(pos))
        if self._tool == TOOL_DRAW:
            op.points.append(QPointF(pos))
        self._active_op = op
        self.update()

    def _is_meaningful_op(self, op: _Op) -> bool:
        if op.tool == TOOL_DRAW:
            return len(op.points) >= 2
        return (op.end - op.start).manhattanLength() > 2

    def _undo(self) -> None:
        if self._ops:
            self._redo.append(self._ops.pop())
            self.update()

    def _redo_op(self) -> None:
        if self._redo:
            self._ops.append(self._redo.pop())
            self.update()

    # -- commit paths ----------------------------------------------------------

    def _render_final(self) -> QPixmap | None:
        if self._selection is None:
            return None
        sel = self._selection
        result = QPixmap(sel.size())
        result.fill(Qt.GlobalColor.transparent)
        p = QPainter(result)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        # Paste the source region
        p.drawPixmap(0, 0, self._background, sel.x(), sel.y(), sel.width(), sel.height())
        # Ops are in overlay coordinates — translate onto the cropped canvas.
        p.translate(-sel.topLeft())
        for op in self._ops:
            self._paint_op(p, op)
        p.end()
        return result

    def _commit_save_only(self) -> None:
        pixmap = self._render_final()
        if pixmap is None:
            return
        self.hide()
        self.save_only.emit(pixmap)
        self.close()

    def _commit_save_and_open(self) -> None:
        pixmap = self._render_final()
        if pixmap is None:
            return
        self.hide()
        self.save_and_open.emit(pixmap)
        self.close()

    def _cancel(self) -> None:
        self.hide()
        self.cancelled.emit()
        self.close()


# ---------------------------------------------------------------------------
# Small free helpers
# ---------------------------------------------------------------------------


def _virtual_desktop_geometry() -> QRect:
    geo = QRect()
    for screen in QGuiApplication.screens():
        geo = geo.united(screen.geometry())
    return geo


def _rect_from(a: QPointF, b: QPointF) -> QRectF:
    from PyQt6.QtCore import QRectF as _QRectF
    return _QRectF(a, b).normalized()


def _resize(rect: QRect, handle: str, pos: QPoint) -> QRect:
    left, top, right, bottom = rect.left(), rect.top(), rect.right(), rect.bottom()
    if "n" in handle:
        top = pos.y()
    if "s" in handle:
        bottom = pos.y()
    if "w" in handle:
        left = pos.x()
    if "e" in handle:
        right = pos.x()
    resized = QRect(QPoint(left, top), QPoint(right, bottom)).normalized()
    return resized


def _draw_arrow(p: QPainter, start: QPointF, end: QPointF, color: QColor, width: int) -> None:
    line = QLineF(start, end)
    p.drawLine(line)
    angle = line.angle()
    head_length = 10 + width * 2
    left = QLineF()
    left.setP1(end)
    left.setAngle(angle + 150)
    left.setLength(head_length)
    right = QLineF()
    right.setP1(end)
    right.setAngle(angle - 150)
    right.setLength(head_length)
    p.setBrush(color)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawPolygon(QPolygonF([end, left.p2(), right.p2()]))


_HANDLE_CURSORS = {
    "nw": Qt.CursorShape.SizeFDiagCursor,
    "se": Qt.CursorShape.SizeFDiagCursor,
    "ne": Qt.CursorShape.SizeBDiagCursor,
    "sw": Qt.CursorShape.SizeBDiagCursor,
    "n":  Qt.CursorShape.SizeVerCursor,
    "s":  Qt.CursorShape.SizeVerCursor,
    "e":  Qt.CursorShape.SizeHorCursor,
    "w":  Qt.CursorShape.SizeHorCursor,
}
