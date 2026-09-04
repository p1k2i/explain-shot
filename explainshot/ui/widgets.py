"""Small shared widgets used across windows.

Kept out of any theme module so they don't create a circular import — the
chevron combo needs Qt but not any theme tokens (it uses the palette's
text colour so it inherits whatever the QSS sets).
"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QPainter, QPaintEvent, QPen
from PyQt6.QtWidgets import QComboBox, QStyleOptionComboBox, QWidget


class ChevronComboBox(QComboBox):
    """QComboBox with a self-painted down-caret.

    Reason for the subclass: our theme QSS customises
    ``QComboBox::drop-down`` (no border, fixed width) which — per Qt's
    stylesheet rules — hides the platform arrow. Reinstating an arrow via
    ``::down-arrow`` requires shipping an image; painting it here keeps the
    styling code local and colour follows the widget's text colour so it
    tracks light/dark automatically.
    """

    def paintEvent(self, event: QPaintEvent | None) -> None:  # type: ignore[override]
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        color = self.palette().text().color()
        if not color.isValid():
            color = QColor("#e0e0e0")
        pen = QPen(color)
        pen.setWidthF(1.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)

        # 8x5 chevron, right-aligned inside a 20px drop-down zone.
        rect = self.rect()
        cx = rect.right() - 12
        cy = rect.center().y() + 1
        w = 5
        h = 3
        painter.drawLine(QPointF(cx - w, cy - h), QPointF(cx, cy + h))
        painter.drawLine(QPointF(cx, cy + h), QPointF(cx + w, cy - h))
