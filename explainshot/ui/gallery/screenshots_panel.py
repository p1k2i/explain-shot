"""Left column of the gallery: the screenshot list.

Card grid, lazy thumbnails. No transparency, no CSS-per-item juggling —
the theme handles the [selected=true] state via property polish.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...capture.models import ScreenshotRecord
from ...capture.screenshot import ScreenshotService
from ...capture.thumbnails import ThumbnailCache


class ScreenshotCard(QWidget):
    clicked = pyqtSignal(str)
    delete_requested = pyqtSignal(str)

    def __init__(self, record: ScreenshotRecord, thumb_px: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.record = record
        self.setObjectName("ScreenshotCard")
        self.setProperty("selected", False)
        self.setFixedWidth(thumb_px + 16)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        self.image = QLabel()
        self.image.setFixedSize(thumb_px, thumb_px)
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setStyleSheet("background: transparent;")
        layout.addWidget(self.image)

        meta_row = QHBoxLayout()
        meta_row.setSpacing(4)
        self.name = QLabel(record.filename)
        self.name.setProperty("muted", True)
        self.name.setToolTip(record.filename)
        # Truncate visually; QLabel will elide via style if needed.
        self.name.setMaximumWidth(thumb_px)
        meta_row.addWidget(self.name, 1)
        layout.addLayout(meta_row)

        self.dim = QLabel(f"{record.width}×{record.height}")
        self.dim.setProperty("muted", True)
        layout.addWidget(self.dim)

    def set_pixmap(self, pixmap: QPixmap) -> None:
        self.image.setPixmap(
            pixmap.scaled(
                self.image.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        # Trigger QSS re-evaluation for property selectors.
        style = self.style()
        if style:
            style.unpolish(self)
            style.polish(self)

    def mousePressEvent(self, event: QMouseEvent | None) -> None:  # type: ignore[override]
        if event and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.record.id)
        super().mousePressEvent(event)


class ScreenshotsPanel(QWidget):
    selection_changed = pyqtSignal(object)  # ScreenshotRecord or None
    delete_requested = pyqtSignal(str)      # screenshot id

    def __init__(
        self,
        service: ScreenshotService,
        thumbnails: ThumbnailCache,
        thumb_px: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.thumbnails = thumbnails
        self.thumb_px = thumb_px
        self._cards: dict[str, ScreenshotCard] = {}
        self._selected_id: str | None = None

        self.thumbnails.ready.connect(self._on_thumbnail_ready)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("Screenshots")
        title.setProperty("section", True)
        header.addWidget(title, 1)

        refresh = QPushButton("Refresh")
        refresh.setProperty("flat", True)
        refresh.clicked.connect(self.reload)
        header.addWidget(refresh)
        layout.addLayout(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.scroll, 1)

        self._grid_host = QWidget()
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(4, 4, 4, 4)
        self._grid.setSpacing(8)
        self.scroll.setWidget(self._grid_host)

    # -- public API ------------------------------------------------------------

    def reload(self) -> None:
        records = self.service.list_recent(limit=500)
        self._rebuild_grid(records)

    def add_or_update(self, record: ScreenshotRecord) -> None:
        if record.id in self._cards:
            return
        records = [record, *[c.record for c in self._cards.values()]]
        self._rebuild_grid(records)
        self.select(record.id)

    def remove(self, screenshot_id: str) -> None:
        card = self._cards.pop(screenshot_id, None)
        if card:
            card.deleteLater()
        if self._selected_id == screenshot_id:
            self._selected_id = None
            self.selection_changed.emit(None)
        self.thumbnails.evict(screenshot_id)

    def select(self, screenshot_id: str | None) -> None:
        if self._selected_id == screenshot_id:
            return
        prior = self._cards.get(self._selected_id or "")
        if prior:
            prior.set_selected(False)
        self._selected_id = screenshot_id
        card = self._cards.get(screenshot_id or "")
        if card:
            card.set_selected(True)
            self.scroll.ensureWidgetVisible(card, 0, 20)
        self.selection_changed.emit(card.record if card else None)

    def set_thumb_size(self, px: int) -> None:
        if px == self.thumb_px:
            return
        self.thumb_px = px
        self.thumbnails.set_size(px)
        self.reload()

    # -- internals -------------------------------------------------------------

    def _rebuild_grid(self, records: list[ScreenshotRecord]) -> None:
        # Clear existing
        for card in self._cards.values():
            card.deleteLater()
        self._cards.clear()
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget:
                widget.deleteLater()

        columns = max(1, self.width() // (self.thumb_px + 32))
        for index, record in enumerate(records):
            card = ScreenshotCard(record, self.thumb_px, parent=self._grid_host)
            card.clicked.connect(self.select)
            self._cards[record.id] = card
            row, col = divmod(index, columns)
            self._grid.addWidget(card, row, col)
            pixmap = self.thumbnails.request(record.id, record.path)
            if pixmap is not None:
                card.set_pixmap(pixmap)

        # Stretch bottom row so cards align top-left cleanly
        self._grid.setRowStretch(self._grid.rowCount(), 1)
        self._grid.setColumnStretch(columns, 1)

        # Re-apply selection if still valid
        if self._selected_id in self._cards:
            self._cards[self._selected_id].set_selected(True)
        else:
            self._selected_id = None

    def _on_thumbnail_ready(self, screenshot_id: str, pixmap: QPixmap) -> None:
        card = self._cards.get(screenshot_id)
        if card is not None:
            card.set_pixmap(pixmap)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        if self._cards:
            records = [c.record for c in self._cards.values()]
            self._rebuild_grid(records)
