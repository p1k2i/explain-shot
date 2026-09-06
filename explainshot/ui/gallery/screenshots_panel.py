"""Left column of the gallery: the screenshot list.

Two view modes share one card widget and one grid layout:
  * **grid** — thumbnail cards flowed into as many columns as fit (the
    default, image-forward browsing).
  * **list** — full-width rows with a small thumbnail and the filename, for
    scanning many shots by name.

A compact toolbar switches the mode and the thumbnail size; both choices are
persisted by the window via the `prefs_changed` signal.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QMouseEvent, QPixmap
from PyQt6.QtWidgets import (
    QButtonGroup,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ...capture.models import ScreenshotRecord
from ...capture.screenshot import ScreenshotService
from ...capture.thumbnails import ThumbnailCache
from ..animation import HoverAnimator, HoverStates, HoverStyle

# Grid thumbnail edge range for the size slider, in px (matches the settings
# window's thumbnail spin box). The cache always decodes at this (larger) grid
# size; list mode just displays a scaled-down copy, so toggling grid<->list
# never re-decodes.
_MIN_THUMB_PX = 32
_MAX_THUMB_PX = 320


def _list_px_for(grid_px: int) -> int:
    """The little thumbnail edge used in list rows, scaled off the grid size
    so the slider also changes list density. Clamped to stay row-sized."""
    return max(40, min(84, round(grid_px * 0.36)))


def _clamp_thumb(px: int) -> int:
    return max(_MIN_THUMB_PX, min(_MAX_THUMB_PX, int(px)))


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

    def __init__(
        self,
        record: ScreenshotRecord,
        thumb_px: int,
        theme: str,
        *,
        mode: str = "grid",
        list_px: int = 56,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.record = record
        self.mode = mode if mode in ("grid", "list") else "grid"
        self.setObjectName("ScreenshotCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        if mode == "list":
            self._build_list(record, list_px)
        else:
            self._build_grid(record, thumb_px)

        states = _STATES_DARK if theme == "dark" else _STATES_LIGHT
        self._anim = HoverAnimator.attach(self, states)

    def _build_grid(self, record: ScreenshotRecord, thumb_px: int) -> None:
        self.setFixedWidth(thumb_px + 20)
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

    def _build_list(self, record: ScreenshotRecord, list_px: int) -> None:
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(list_px + 16)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 12, 8)
        layout.setSpacing(12)

        self.image = QLabel()
        self.image.setFixedSize(list_px, list_px)
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setStyleSheet("background: transparent;")
        layout.addWidget(self.image)

        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(2)
        text.addStretch(1)
        self.name = QLabel(record.filename)
        self.name.setToolTip(record.filename)
        text.addWidget(self.name)
        self.dim = QLabel(f"{record.width}×{record.height}")
        self.dim.setProperty("muted", True)
        text.addWidget(self.dim)
        text.addStretch(1)
        layout.addLayout(text, 1)

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
    prefs_changed = pyqtSignal(str, int)     # view_mode, thumbnail_px — persist upstream

    def __init__(
        self,
        service: ScreenshotService,
        thumbnails: ThumbnailCache,
        thumb_px: int,
        view_mode: str = "grid",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.thumbnails = thumbnails
        self.thumb_px = _clamp_thumb(thumb_px)
        self._view_mode = view_mode if view_mode in ("grid", "list") else "grid"
        self._cards: dict[str, ScreenshotCard] = {}
        self._selected_id: str | None = None
        self._theme = "dark"
        # The size slider re-decodes every thumbnail on change, so we coalesce
        # rapid drags into a single apply once the value settles.
        self._size_debounce = QTimer(self)
        self._size_debounce.setSingleShot(True)
        self._size_debounce.setInterval(160)
        self._size_debounce.timeout.connect(self._apply_slider_size)

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

        layout.addLayout(self._build_toolbar())

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

    # -- toolbar ---------------------------------------------------------------

    def _build_toolbar(self) -> QHBoxLayout:
        tools = QHBoxLayout()
        tools.setContentsMargins(0, 0, 0, 0)
        tools.setSpacing(6)

        # View-mode toggle (grid vs list), mutually exclusive.
        self._view_group = QButtonGroup(self)
        self._view_group.setExclusive(True)
        self._grid_btn = self._toggle_button("▦", "Grid view", "grid")
        self._list_btn = self._toggle_button("☰", "List view", "list")
        (self._grid_btn if self._view_mode == "grid" else self._list_btn).setChecked(True)
        tools.addWidget(self._grid_btn)
        tools.addWidget(self._list_btn)

        tools.addStretch(1)

        size_label = QLabel("Size")
        size_label.setProperty("muted", True)
        tools.addWidget(size_label)

        # Size slider: drives the grid thumbnail edge (and, proportionally, the
        # list thumbnail). The expensive re-decode/rebuild is debounced to when
        # the drag settles.
        self._size_slider = QSlider(Qt.Orientation.Horizontal)
        self._size_slider.setRange(_MIN_THUMB_PX, _MAX_THUMB_PX)
        self._size_slider.setSingleStep(8)
        self._size_slider.setPageStep(32)
        self._size_slider.setFixedWidth(140)
        self._size_slider.setValue(self.thumb_px)
        self._size_slider.setToolTip("Thumbnail size")
        self._size_slider.valueChanged.connect(self._on_size_slider_changed)
        tools.addWidget(self._size_slider)
        return tools

    def _toggle_button(self, glyph: str, tooltip: str, mode: str) -> QPushButton:
        b = QPushButton(glyph)
        b.setProperty("chip", True)
        b.setCheckable(True)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setToolTip(tooltip)
        b.setFixedWidth(34)
        b.clicked.connect(lambda _checked=False, m=mode: self._on_view_pick(m))
        self._view_group.addButton(b)
        return b

    def _on_view_pick(self, mode: str) -> None:
        if mode == self._view_mode:
            return
        self._view_mode = mode
        records = [c.record for c in self._cards.values()]
        self._rebuild(records)
        self.prefs_changed.emit(self._view_mode, self.thumb_px)

    def _on_size_slider_changed(self, _value: int) -> None:
        # Defer the (expensive) re-decode/rebuild until the drag settles.
        self._size_debounce.start()

    def _apply_slider_size(self) -> None:
        px = _clamp_thumb(self._size_slider.value())
        if px == self.thumb_px:
            return
        self.set_thumb_size(px)
        self.prefs_changed.emit(self._view_mode, self.thumb_px)

    def _sync_size_controls(self) -> None:
        """Move the slider to match self.thumb_px without retriggering the
        debounce (used when the size changes from outside the slider)."""
        self._size_slider.blockSignals(True)
        self._size_slider.setValue(self.thumb_px)
        self._size_slider.blockSignals(False)

    # -- public API ------------------------------------------------------------

    def set_theme(self, theme: str) -> None:
        self._theme = theme
        if self._cards:
            self.reload()

    def reload(self) -> None:
        records = self.service.list_recent(limit=500)
        self._rebuild(records)

    def add_or_update(self, record: ScreenshotRecord) -> None:
        if record.id in self._cards:
            return
        records = [record, *[c.record for c in self._cards.values()]]
        self._rebuild(records)
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
        """Change the thumbnail size. Re-decodes the cache at the new (grid)
        edge and rebuilds; safe to call from outside (e.g. settings sync) — it
        syncs the slider without recursing and doesn't emit prefs_changed."""
        px = _clamp_thumb(px)
        if px == self.thumb_px:
            return
        self.thumb_px = px
        self.thumbnails.set_size(px)
        self._sync_size_controls()
        if self._cards:
            self._rebuild([c.record for c in self._cards.values()])
        else:
            self.reload()

    def set_view_mode(self, mode: str) -> None:
        """Switch grid/list from outside; doesn't emit prefs_changed."""
        if mode not in ("grid", "list") or mode == self._view_mode:
            return
        self._view_mode = mode
        (self._grid_btn if mode == "grid" else self._list_btn).setChecked(True)
        self._rebuild([c.record for c in self._cards.values()])

    # -- layout ----------------------------------------------------------------

    def _rebuild(self, records: list[ScreenshotRecord]) -> None:
        self._clear_grid()

        if self._view_mode == "list":
            self._lay_out_list(records)
        else:
            self._lay_out_grid(records)

        if self._selected_id in self._cards:
            self._cards[self._selected_id].set_selected(True, instant=True)
        else:
            self._selected_id = None

    def _clear_grid(self) -> None:
        """Tear down the current cards. Reparent to None *immediately* (not
        just deleteLater) — deleteLater is async and, notably, is not even
        dispatched by processEvents(), so without an eager unparent the old
        cards keep painting at their last geometry (e.g. phantom grid cards
        behind a fresh list). Also zero any stretch factors a previous layout
        set, so a grid↔list switch never inherits stale column/row weights."""
        for card in self._cards.values():
            card.setParent(None)
            card.deleteLater()
        self._cards.clear()
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget() if item else None
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        for col in range(self._grid.columnCount() + 2):
            self._grid.setColumnStretch(col, 0)
        for row in range(self._grid.rowCount() + 2):
            self._grid.setRowStretch(row, 0)

    def _make_card(self, record: ScreenshotRecord) -> ScreenshotCard:
        card = ScreenshotCard(
            record, self.thumb_px, self._theme,
            mode=self._view_mode, list_px=_list_px_for(self.thumb_px),
            parent=self._grid_host,
        )
        card.clicked.connect(self.select)
        card.activated.connect(self.preview_requested.emit)
        card.context_menu.connect(self._on_context_menu)
        self._cards[record.id] = card
        pixmap = self.thumbnails.request(record.id, record.path)
        if pixmap is not None:
            card.set_pixmap(pixmap)
        return card

    def _lay_out_grid(self, records: list[ScreenshotRecord]) -> None:
        columns = max(1, self.width() // (self.thumb_px + 36))
        for index, record in enumerate(records):
            card = self._make_card(record)
            row, col = divmod(index, columns)
            self._grid.addWidget(card, row, col)
        self._grid.setRowStretch(self._grid.rowCount(), 1)
        self._grid.setColumnStretch(columns, 1)

    def _lay_out_list(self, records: list[ScreenshotRecord]) -> None:
        for index, record in enumerate(records):
            card = self._make_card(record)
            self._grid.addWidget(card, index, 0)
        # Rows fill the width; the trailing stretch keeps them packed at top.
        self._grid.setColumnStretch(0, 1)
        self._grid.setRowStretch(len(records), 1)

    def _on_thumbnail_ready(self, screenshot_id: str, pixmap: QPixmap) -> None:
        card = self._cards.get(screenshot_id)
        if card is not None:
            card.set_pixmap(pixmap)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        # Only grid mode depends on width (column count). List rows stretch to
        # fit on their own, so they never need a rebuild on resize.
        if self._view_mode == "grid" and self._cards:
            records = [c.record for c in self._cards.values()]
            self._rebuild(records)

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
