"""Fullscreen overlay for click-and-drag region selection.

Replaces the old overlay_window.py (486 lines) + overlay_manager.py
(700 lines) that implemented a bizarre "app functions and recent
screenshots" popup list — nothing to do with actual region selection.

Screen capture UX: darken the whole desktop, cutout the drag rectangle
so the user sees exactly what will be captured, show the accent-coloured
border and pixel dimensions in the corner.
"""

from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QGuiApplication,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
)
from PyQt6.QtWidgets import QApplication, QWidget

from ...capture.models import CaptureRegion


class RegionSelector(QWidget):
    """Fullscreen picker. Emits `region_selected` with a CaptureRegion or
    `cancelled` when the user hits Escape."""

    region_selected = pyqtSignal(object)   # CaptureRegion
    cancelled = pyqtSignal()

    def __init__(self, accent: str = "#0067c0", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._accent = QColor(accent)
        self._start: QPoint | None = None
        self._end: QPoint | None = None

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)

    def show_over_desktop(self) -> None:
        geo = self._virtual_desktop_geometry()
        self.setGeometry(geo)
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    # -- events ----------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent | None) -> None:  # type: ignore[override]
        if not event:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._start = event.pos()
            self._end = event.pos()
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent | None) -> None:  # type: ignore[override]
        if not event:
            return
        if self._start is not None:
            self._end = event.pos()
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent | None) -> None:  # type: ignore[override]
        if not event or event.button() != Qt.MouseButton.LeftButton:
            return
        if self._start is None or self._end is None:
            return
        rect = QRect(self._start, self._end).normalized()
        self.hide()
        if rect.width() < 4 or rect.height() < 4:
            self.cancelled.emit()
            return
        offset = self.geometry().topLeft()
        self.region_selected.emit(
            CaptureRegion(
                x=rect.x() + offset.x(),
                y=rect.y() + offset.y(),
                width=rect.width(),
                height=rect.height(),
            )
        )

    def keyPressEvent(self, event: QKeyEvent | None) -> None:  # type: ignore[override]
        if not event:
            return
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            self.cancelled.emit()

    def paintEvent(self, event: QPaintEvent | None) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        # Dark scrim over everything
        painter.fillRect(self.rect(), QColor(0, 0, 0, 120))

        if self._start is not None and self._end is not None:
            rect = QRect(self._start, self._end).normalized()
            # Cut out the selection — clear paints transparent onto our translucent widget.
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(rect, Qt.GlobalColor.transparent)

            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            pen = QPen(self._accent)
            pen.setWidth(2)
            painter.setPen(pen)
            painter.drawRect(rect)

            painter.setPen(QColor(255, 255, 255))
            painter.drawText(rect.topLeft() + QPoint(6, -6), f"{rect.width()} × {rect.height()}")

    # -- helpers ---------------------------------------------------------------

    @staticmethod
    def _virtual_desktop_geometry() -> QRect:
        # Union of every screen — supports multi-monitor spans.
        geo = QRect()
        for screen in QGuiApplication.screens():
            geo = geo.united(screen.geometry())
        return geo
