"""
Custom Title Bar Component

Frameless window title bar with drag handling and window controls.
"""

import logging
from typing import cast

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton, QFrame

logger = logging.getLogger(__name__)


class CustomTitleBar(QFrame):
    """Custom title bar with native drag handling."""

    def __init__(self, title: str = "Gallery", parent=None):
        super().__init__(parent)
        self.setFixedHeight(40)
        self.setObjectName("TitleBar")
        self._drag_active = False
        self._drag_start_pos = None

        # Create layout and widgets
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)

        # Title
        self.title_label = QLabel(title)
        self.title_label.setObjectName("column_header")
        layout.addWidget(self.title_label)

        layout.addStretch()

        # Window controls
        self.minimize_button = QPushButton("−")
        self.minimize_button.setFixedSize(30, 30)
        self.minimize_button.setObjectName("title_bar_minimize")
        self.minimize_button.clicked.connect(self._on_minimize)

        self.close_button = QPushButton("×")
        self.close_button.setFixedSize(30, 30)
        self.close_button.setObjectName("title_bar_close")
        self.close_button.clicked.connect(self._on_close)

        layout.addWidget(self.minimize_button)
        layout.addWidget(self.close_button)

    def _on_minimize(self):
        """Handle minimize button click."""
        parent_widget = self.parent()
        if parent_widget and hasattr(parent_widget, 'showMinimized'):
            cast(QWidget, parent_widget).showMinimized()

    def _on_close(self):
        """Handle close button click."""
        parent_widget = self.parent()
        if parent_widget and hasattr(parent_widget, 'close'):
            cast(QWidget, parent_widget).close()

    def mousePressEvent(self, a0):
        """Handle mouse press for dragging."""
        if a0 and hasattr(a0, 'button') and a0.button() == Qt.MouseButton.LeftButton:
            widget_under_mouse = self.childAt(a0.position().toPoint())
            if not (widget_under_mouse and isinstance(widget_under_mouse, QPushButton)):
                self._drag_active = True
                window = self.window()
                if window and hasattr(window, 'frameGeometry'):
                    self._drag_start_pos = a0.globalPosition().toPoint() - window.frameGeometry().topLeft()
                a0.accept()
            else:
                super().mousePressEvent(a0)
        else:
            super().mousePressEvent(a0)

    def mouseMoveEvent(self, a0):
        """Handle mouse move for dragging."""
        if self._drag_active and self._drag_start_pos is not None:
            if a0 and hasattr(a0, 'buttons') and a0.buttons() == Qt.MouseButton.LeftButton:
                window = self.window()
                if window and hasattr(window, 'move'):
                    new_pos = a0.globalPosition().toPoint() - self._drag_start_pos
                    window.move(new_pos)
                a0.accept()
            else:
                self._drag_active = False
                self._drag_start_pos = None
        else:
            super().mouseMoveEvent(a0)

    def mouseReleaseEvent(self, a0):
        """Handle mouse release to stop dragging."""
        if a0 and hasattr(a0, 'button') and a0.button() == Qt.MouseButton.LeftButton and self._drag_active:
            self._drag_active = False
            self._drag_start_pos = None
            a0.accept()
        else:
            super().mouseReleaseEvent(a0)
