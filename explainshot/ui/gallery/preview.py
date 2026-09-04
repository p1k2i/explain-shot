"""Full-image preview modal opened by double-clicking a screenshot card."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication, QKeyEvent, QPixmap
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..chrome import FramelessWindow, TitleBar


class PreviewWindow(FramelessWindow):
    def __init__(self, image_path: str, filename: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(filename)
        pixmap = QPixmap(image_path)
        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        max_w = avail.width() - 120 if avail else 1200
        max_h = avail.height() - 180 if avail else 800
        w = min(pixmap.width() + 40, max_w)
        h = min(pixmap.height() + 100, max_h)
        self.resize(max(600, w), max(400, h))

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        bar = TitleBar(self, title=filename, show_maximise=True)
        bar.request_close.connect(self.close)
        root.addWidget(bar)

        body = QVBoxLayout()
        body.setContentsMargins(12, 12, 12, 12)
        body.setSpacing(8)

        self._label = QLabel()
        self._label.setPixmap(pixmap)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll = QScrollArea()
        scroll.setWidget(self._label)
        scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll.setStyleSheet("background: rgba(0,0,0,0.4); border: none;")
        body.addWidget(scroll, 1)

        info_row = QHBoxLayout()
        info = QLabel(f"{pixmap.width()} × {pixmap.height()}")
        info.setProperty("muted", True)
        info_row.addWidget(info, 1)

        close = QPushButton("Close (Esc)")
        close.clicked.connect(self.close)
        info_row.addWidget(close)
        body.addLayout(info_row)

        outer = QWidget()
        outer.setLayout(body)
        root.addWidget(outer, 1)

    def keyPressEvent(self, event: QKeyEvent | None) -> None:  # type: ignore[override]
        if event and event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)
