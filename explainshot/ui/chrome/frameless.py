"""Base class for our frameless top-level windows.

Handles what the OS chrome usually gave us:
  * mouse-cursor changes near the 8 edges/corners and startSystemResize()
  * dark title-bar attribute on Windows (DwmSetWindowAttribute)
  * WA_DeleteOnClose so windows get GC'd predictably

Subclasses provide their own TitleBar + body. They should place the
TitleBar as the first row of their layout with contentsMargins that keep
the resize band clear.
"""

from __future__ import annotations

import ctypes
import sys
from typing import Optional

from PyQt6.QtCore import QEvent, QPoint, Qt
from PyQt6.QtGui import QCursor, QMouseEvent
from PyQt6.QtWidgets import QWidget


_RESIZE_MARGIN = 6  # pixels of grabbable border for resize


def _cursor_edge(pos: QPoint, size) -> Qt.Edge | None:
    x, y = pos.x(), pos.y()
    w, h = size.width(), size.height()
    m = _RESIZE_MARGIN
    left, right = x <= m, x >= w - m
    top, bottom = y <= m, y >= h - m
    edges = 0
    if left:
        edges |= Qt.Edge.LeftEdge
    if right:
        edges |= Qt.Edge.RightEdge
    if top:
        edges |= Qt.Edge.TopEdge
    if bottom:
        edges |= Qt.Edge.BottomEdge
    return Qt.Edge(edges) if edges else None


def _cursor_for(edge: Qt.Edge) -> Qt.CursorShape:
    left = bool(edge & Qt.Edge.LeftEdge)
    right = bool(edge & Qt.Edge.RightEdge)
    top = bool(edge & Qt.Edge.TopEdge)
    bottom = bool(edge & Qt.Edge.BottomEdge)
    if (top and left) or (bottom and right):
        return Qt.CursorShape.SizeFDiagCursor
    if (top and right) or (bottom and left):
        return Qt.CursorShape.SizeBDiagCursor
    if left or right:
        return Qt.CursorShape.SizeHorCursor
    if top or bottom:
        return Qt.CursorShape.SizeVerCursor
    return Qt.CursorShape.ArrowCursor


class FramelessWindow(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setMouseTracking(True)
        # Store the edge the pointer is currently in, purely for cursor hinting.
        self._hover_edge: Qt.Edge | None = None

    # -- events ----------------------------------------------------------------

    def event(self, event: QEvent | None) -> bool:  # type: ignore[override]
        if event is not None and event.type() == QEvent.Type.HoverMove:
            pos = QCursor.pos()
            local = self.mapFromGlobal(pos)
            edge = _cursor_edge(local, self.size())
            if edge != self._hover_edge:
                self._hover_edge = edge
                self.setCursor(QCursor(_cursor_for(edge)) if edge else QCursor(Qt.CursorShape.ArrowCursor))
        return super().event(event)

    def mousePressEvent(self, event: QMouseEvent | None) -> None:  # type: ignore[override]
        if event and event.button() == Qt.MouseButton.LeftButton and not self.isMaximized():
            edge = _cursor_edge(event.pos(), self.size())
            if edge is not None:
                handle = self.windowHandle()
                if handle is not None:
                    handle.startSystemResize(edge)
                    event.accept()
                    return
        super().mousePressEvent(event)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        _apply_windows_dark_titlebar(self, prefer_dark=True)

    # -- helpers ---------------------------------------------------------------

    def toggle_maximised(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()


def _apply_windows_dark_titlebar(widget: QWidget, prefer_dark: bool) -> None:
    """Ask Windows DWM to draw the frameless-window shadow with the dark
    theme so the drop-shadow around our window matches. No-op elsewhere."""
    if sys.platform != "win32":
        return
    hwnd = int(widget.winId())
    if not hwnd:
        return
    try:
        dwmapi = ctypes.windll.dwmapi  # type: ignore[attr-defined]
    except (OSError, AttributeError):
        return
    # DWMWA_USE_IMMERSIVE_DARK_MODE = 20 (Windows 10 20H1+) / 19 on older 20H1.
    value = ctypes.c_int(1 if prefer_dark else 0)
    for attr in (20, 19):
        result = dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value), ctypes.sizeof(value))
        if result == 0:
            break
