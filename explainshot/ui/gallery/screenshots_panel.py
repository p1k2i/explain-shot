"""Left column of the gallery: the screenshot list.

Card grid with lazy thumbnails and scripted hover/selection animations.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QMouseEvent, QPixmap
from PyQt6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...capture.models import ScreenshotRecord
from ...capture.screenshot import ScreenshotService
from ...capture.thumbnails import ThumbnailCache
from ..animation import HoverAnimator, HoverStates, HoverStyle


_STATES_DARK = HoverStates(
    idle=HoverStyle(QColor("#262626"), QColor("#3d3d3d"), radius=8),
    hover=HoverStyle(QColor("#3a3a3a"), QColor("#0067c0"), radius=8, border_width=2),
    selected=HoverStyle(QColor("#22344a"), QColor("#0067c0"), radius=8, border_width=2),
    duration_ms=140,
)
_STATES_LIGHT = HoverStates(
    idle=HoverStyle(QColor("#ffffff"), QColor("#dcdcdc"), radius=8),
    hover=HoverStyle(QColor("#eef4fb"), QColor("#0067c0"), radius=8, border_width=2),
    selected=HoverStyle(QColor("#dceaf7"), QColor("#0067c0"), radius=8, border_width=2),
    duration_ms=140,
)


class ScreenshotCard(QWidget):
    clicked = pyqtSignal(str)
    activated = pyqtSignal(str)    # double-click → open preview
    context_menu = pyqtSignal(str, object)   # right-click at global pos

    def __init__(self, record: ScreenshotRecord, thumb_px: int, theme: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.record = record
        self.setObjectName("ScreenshotCard")
        self.setFixedWidth(thumb_px + 20)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(4)

        self.image = QLabel()
        self.image.setFixedSize(thumb_px, thumb_px)
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setStyleSheet("background: transparent;")
        layout.addWidget(self.image)

        self.name = QLabel(record.filename)
        self.name.setProperty("muted", True)
        self.name.setToolTip(record.filename)
        self.name.setMaximumWidth(thumb_px)
        layout.addWidget(self.name)

        self.dim = QLabel(f"{record.width}×{record.height}")
        self.dim.setProperty("muted", True)
        layout.addWidget(self.dim)

        states = _STATES_DARK if theme == "dark" else _STATES_LIGHT
        self._anim = HoverAnimator.attach(self, states)

    def set_pixmap(self, pixmap: QPixmap) -> None:
        self.image.setPixmap(
            pixmap.scaled(
                self.image.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def set_selected(self, selected: bool, *, instant: bool = False) -> None:
        self._anim.set_selected(selected, instant=instant)

    def mousePressEvent(self, event: QMouseEvent | None) -> None:  # type: ignore[override]
        if event:
            if event.button() == Qt.MouseButton.LeftButton:
                self.clicked.emit(self.record.id)
            elif event.button() == Qt.MouseButton.RightButton:
                self.context_menu.emit(self.record.id, event.globalPosition().toPoint())
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent | None) -> None:  # type: ignore[override]
        if event and event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self.record.id)
        super().mouseDoubleClickEvent(event)


class ScreenshotsPanel(QWidget):
    selection_changed = pyqtSignal(object)   # ScreenshotRecord or None
    preview_requested = pyqtSignal(str)      # screenshot id (double-click)
    delete_requested = pyqtSignal(str)       # screenshot id
    rename_requested = pyqtSignal(str, str)  # screenshot id, new stem

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
        self._theme = "dark"

        self.thumbnails.ready.connect(self._on_thumbnail_ready)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("Screenshots")
        title.setProperty("section", True)
        header.addWidget(title, 1)

        refresh = QPushButton("Refresh")
        refresh.setProperty("chip", True)
        refresh.clicked.connect(self.reload)
        header.addWidget(refresh)
        layout.addLayout(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(self.scroll, 1)

        self._grid_host = QWidget()
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(2, 2, 2, 2)
        self._grid.setSpacing(10)
        self.scroll.setWidget(self._grid_host)

    def set_theme(self, theme: str) -> None:
        self._theme = theme
        if self._cards:
            self.reload()

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

    def _rebuild_grid(self, records: list[ScreenshotRecord]) -> None:
        for card in self._cards.values():
            card.deleteLater()
        self._cards.clear()
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        columns = max(1, self.width() // (self.thumb_px + 36))
        for index, record in enumerate(records):
            card = ScreenshotCard(record, self.thumb_px, self._theme, parent=self._grid_host)
            card.clicked.connect(self.select)
            card.activated.connect(self.preview_requested.emit)
            card.context_menu.connect(self._on_context_menu)
            self._cards[record.id] = card
            row, col = divmod(index, columns)
            self._grid.addWidget(card, row, col)
            pixmap = self.thumbnails.request(record.id, record.path)
            if pixmap is not None:
                card.set_pixmap(pixmap)

        self._grid.setRowStretch(self._grid.rowCount(), 1)
        self._grid.setColumnStretch(columns, 1)

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

    def _on_context_menu(self, screenshot_id: str, global_pos) -> None:
        card = self._cards.get(screenshot_id)
        if not card:
            return
        menu = QMenu(self)
        open_action = QAction("Open preview", menu)
        open_action.triggered.connect(lambda: self.preview_requested.emit(screenshot_id))
        menu.addAction(open_action)

        rename_action = QAction("Rename…", menu)
        rename_action.triggered.connect(lambda: self._prompt_rename(screenshot_id))
        menu.addAction(rename_action)

        menu.addSeparator()

        delete_action = QAction("Delete", menu)
        delete_action.triggered.connect(lambda: self._confirm_delete(screenshot_id))
        menu.addAction(delete_action)

        menu.exec(global_pos)

    def _prompt_rename(self, screenshot_id: str) -> None:
        card = self._cards.get(screenshot_id)
        if not card:
            return
        from pathlib import Path
        current_stem = Path(card.record.filename).stem
        new_stem, ok = QInputDialog.getText(self, "Rename screenshot", "Name:", text=current_stem)
        if ok and new_stem.strip() and new_stem.strip() != current_stem:
            self.rename_requested.emit(screenshot_id, new_stem.strip())

    def _confirm_delete(self, screenshot_id: str) -> None:
        card = self._cards.get(screenshot_id)
        if not card:
            return
        answer = QMessageBox.question(
            self,
            "Delete screenshot",
            f"Delete '{card.record.filename}' and its conversation?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.delete_requested.emit(screenshot_id)
