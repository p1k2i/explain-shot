"""A small, neat corner pop-up shown after a silent full-screen capture.

Frameless, click-through-free top-level that fades in at a screen corner,
holds for a configurable time, then fades out. Clicking it dismisses early
(and emits `clicked`, which the app uses to open the gallery on that shot).
It never steals keyboard focus, so it won't interrupt whatever you're doing.
"""

from __future__ import annotations

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QCursor,
    QGuiApplication,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

_MARGIN = 18          # gap from the screen edge
_FADE_MS = 160        # fade in / out duration


class _CloseButton(QPushButton):
    """Dismiss button that paints its "×" as a centred vector instead of a text
    glyph — text glyphs sit on the baseline and look shifted downward. The QSS
    (#ToastClose) still paints the hover background; we only draw the cross."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("", parent)          # no text — the cross is painted
        self.setObjectName("ToastClose")

    def paintEvent(self, event: QPaintEvent | None) -> None:  # type: ignore[override]
        super().paintEvent(event)             # QSS background / hover / radius
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect()
        span = 13.0
        r = QRectF(
            rect.width() / 2 - span / 2,
            rect.height() / 2 - span / 2,
            span, span,
        )
        color = self.palette().buttonText().color()
        if not color.isValid() or color.alpha() == 0:
            color = QColor("#b3b3b3")
        pen = QPen(color)
        pen.setWidthF(2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(r.topLeft(), r.bottomRight())
        painter.drawLine(r.topRight(), r.bottomLeft())


class CaptureToast(QWidget):
    clicked = pyqtSignal()
    closed = pyqtSignal()

    def __init__(
        self,
        title: str,
        subtitle: str = "",
        pixmap: QPixmap | None = None,
        *,
        duration_ms: int = 2000,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self._duration_ms = max(300, int(duration_ms))
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setObjectName("ToastCard")
        row = QHBoxLayout(card)
        row.setContentsMargins(12, 4, 4, 4)
        row.setSpacing(10)

        if pixmap is not None and not pixmap.isNull():
            thumb = QLabel()
            thumb.setObjectName("ToastThumb")
            thumb.setFixedSize(56, 34)
            thumb.setScaledContents(False)
            thumb.setPixmap(
                pixmap.scaled(
                    56, 34,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            row.addWidget(thumb)

        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(1)
        title_label = QLabel(title)
        title_label.setObjectName("ToastTitle")
        text.addWidget(title_label)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("ToastSub")
            sub.setProperty("muted", True)
            text.addWidget(sub)
        row.addLayout(text, 1)

        # Small "×" to dismiss the pop-up WITHOUT opening the gallery. It sits
        # top-right and consumes its own click, so it never triggers the
        # body-click that opens the shot.
        close_btn = _CloseButton()
        close_btn.setFixedSize(34, 34)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        close_btn.setToolTip("Dismiss")
        close_btn.clicked.connect(lambda: self._dismiss())
        # NO alignment flag: with one, QBoxLayout sizes the button to its
        # sizeHint (which collapses a text-less button to ~17px). Plain
        # addWidget honours the fixed 34×34 and centres it, so the gaps above /
        # below / right equal the row's (equal) margins — minimal & symmetric.
        row.addWidget(close_btn)

        outer.addWidget(card)

        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.timeout.connect(self._dismiss)
        self._dismissing = False

    # -- lifecycle -------------------------------------------------------------

    def show_toast(self) -> None:
        self.setWindowOpacity(0.0)
        self.adjustSize()
        self._move_to_corner()
        self.show()
        self.raise_()
        self._fade.stop()
        self._fade.setDuration(_FADE_MS)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()
        self._dismiss_timer.start(self._duration_ms)

    def _move_to_corner(self) -> None:
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        x = area.right() - self.width() - _MARGIN
        y = area.bottom() - self.height() - _MARGIN
        self.move(x, y)

    def _dismiss(self) -> None:
        if self._dismissing:
            return
        self._dismissing = True
        self._dismiss_timer.stop()
        self._fade.stop()
        self._fade.setDuration(_FADE_MS)
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        self._fade.finished.connect(self._finish)
        self._fade.start()

    def _finish(self) -> None:
        self.hide()
        self.closed.emit()

    def mousePressEvent(self, event: QMouseEvent | None) -> None:  # type: ignore[override]
        if event and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            self._dismiss()
            event.accept()
            return
        super().mousePressEvent(event)
