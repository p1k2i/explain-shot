"""Right column of the gallery: prompt presets."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...presets.manager import Preset, PresetManager
from ..animation import HoverAnimator, HoverStates, HoverStyle


_STATES_DARK = HoverStates(
    idle=HoverStyle(QColor("#262626"), QColor("#3d3d3d"), radius=6),
    hover=HoverStyle(QColor("#3a3a3a"), QColor("#0067c0"), radius=6, border_width=2),
    duration_ms=140,
)
_STATES_LIGHT = HoverStates(
    idle=HoverStyle(QColor("#ffffff"), QColor("#dcdcdc"), radius=6),
    hover=HoverStyle(QColor("#eef4fb"), QColor("#0067c0"), radius=6, border_width=2),
    duration_ms=140,
)

# Per-button hover animations for the action row. QSS :hover jumps
# instantly and doesn't feel modern; this animates bg + border over 120ms.
_BTN_STATES_DARK = {
    "accent": HoverStates(
        idle=HoverStyle(QColor("#0067c0"), QColor("#0067c0"), radius=4, border_width=1),
        hover=HoverStyle(QColor("#0079e0"), QColor("#0079e0"), radius=4, border_width=1),
        pressed=HoverStyle(QColor("#005ba1"), QColor("#005ba1"), radius=4, border_width=1),
        duration_ms=120,
    ),
    "flat": HoverStates(
        idle=HoverStyle(QColor(0, 0, 0, 0), QColor(0, 0, 0, 0), radius=4, border_width=1),
        hover=HoverStyle(QColor("#3a3a3a"), QColor("#5a5a5a"), radius=4, border_width=1),
        pressed=HoverStyle(QColor("#2b2b2b"), QColor("#3d3d3d"), radius=4, border_width=1),
        duration_ms=120,
    ),
    "danger": HoverStates(
        idle=HoverStyle(QColor(0, 0, 0, 0), QColor(0, 0, 0, 0), radius=4, border_width=1),
        hover=HoverStyle(QColor("#c94040"), QColor("#c94040"), radius=4, border_width=1),
        pressed=HoverStyle(QColor("#a33333"), QColor("#a33333"), radius=4, border_width=1),
        duration_ms=120,
    ),
}
_BTN_STATES_LIGHT = {
    "accent": HoverStates(
        idle=HoverStyle(QColor("#0067c0"), QColor("#0067c0"), radius=4, border_width=1),
        hover=HoverStyle(QColor("#005ba1"), QColor("#005ba1"), radius=4, border_width=1),
        pressed=HoverStyle(QColor("#004a85"), QColor("#004a85"), radius=4, border_width=1),
        duration_ms=120,
    ),
    "flat": HoverStates(
        idle=HoverStyle(QColor(0, 0, 0, 0), QColor(0, 0, 0, 0), radius=4, border_width=1),
        hover=HoverStyle(QColor("#eef4fb"), QColor("#cfcfcf"), radius=4, border_width=1),
        pressed=HoverStyle(QColor("#dceaf7"), QColor("#cfcfcf"), radius=4, border_width=1),
        duration_ms=120,
    ),
    "danger": HoverStates(
        idle=HoverStyle(QColor(0, 0, 0, 0), QColor(0, 0, 0, 0), radius=4, border_width=1),
        hover=HoverStyle(QColor("#c94040"), QColor("#c94040"), radius=4, border_width=1),
        pressed=HoverStyle(QColor("#a33333"), QColor("#a33333"), radius=4, border_width=1),
        duration_ms=120,
    ),
}


def _animate_button(btn, kind: str, theme: str) -> None:
    """Attach a HoverAnimator that animates the button's own background."""
    table = _BTN_STATES_LIGHT if theme == "light" else _BTN_STATES_DARK
    HoverAnimator.attach(btn, table[kind])


class PresetCard(QWidget):
    run_clicked = pyqtSignal(str)
    paste_clicked = pyqtSignal(str)
    edit_clicked = pyqtSignal(str)
    delete_clicked = pyqtSignal(str)
    move_focus = pyqtSignal(str, str)   # id, direction (up/down)

    def __init__(self, preset: Preset, theme: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.preset = preset
        self.setObjectName("PresetCard")
        # Focusable so keyboard users can arrow through the presets column.
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        hint = "Enter: run · Space: paste"
        if not preset.builtin:
            hint += " · F2: edit · Del: delete"
        self.setToolTip(f"{preset.name}\n{hint}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        name_row = QHBoxLayout()
        name = QLabel(preset.name)
        name.setStyleSheet("font-weight: 600;")
        name_row.addWidget(name, 1)
        if preset.usage_count:
            usage = QLabel(f"×{preset.usage_count}")
            usage.setProperty("muted", True)
            name_row.addWidget(usage)
        if preset.builtin:
            tag = QLabel("built-in")
            tag.setObjectName("StatusChip")
            name_row.addWidget(tag)
        layout.addLayout(name_row)

        preview = QLabel(preset.prompt)
        preview.setWordWrap(True)
        preview.setProperty("muted", True)
        preview.setMaximumHeight(44)
        layout.addWidget(preview)

        actions = QHBoxLayout()
        run = QPushButton("Run")
        run.setProperty("accent", True)
        run.setCursor(Qt.CursorShape.PointingHandCursor)
        run.clicked.connect(lambda: self.run_clicked.emit(preset.id))
        actions.addWidget(run)
        _animate_button(run, "accent", theme)

        paste = QPushButton("Paste")
        paste.setProperty("flat", True)
        paste.setCursor(Qt.CursorShape.PointingHandCursor)
        paste.clicked.connect(lambda: self.paste_clicked.emit(preset.id))
        actions.addWidget(paste)
        _animate_button(paste, "flat", theme)

        actions.addStretch(1)

        if not preset.builtin:
            edit = QPushButton("Edit")
            edit.setProperty("flat", True)
            edit.setCursor(Qt.CursorShape.PointingHandCursor)
            edit.clicked.connect(lambda: self.edit_clicked.emit(preset.id))
            actions.addWidget(edit)
            _animate_button(edit, "flat", theme)

            delete = QPushButton("Delete")
            delete.setProperty("flat", True)
            delete.setProperty("danger", True)
            delete.setCursor(Qt.CursorShape.PointingHandCursor)
            delete.clicked.connect(lambda: self.delete_clicked.emit(preset.id))
            actions.addWidget(delete)
            _animate_button(delete, "danger", theme)
        layout.addLayout(actions)

        states = _STATES_DARK if theme == "dark" else _STATES_LIGHT
        self._anim = HoverAnimator.attach(self, states)

    _NAV_KEYS = {
        Qt.Key.Key_Up: "up", Qt.Key.Key_Down: "down",
        Qt.Key.Key_Home: "home", Qt.Key.Key_End: "end",
        Qt.Key.Key_PageUp: "pageup", Qt.Key.Key_PageDown: "pagedown",
    }

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        key = event.key() if event else None
        if key in self._NAV_KEYS:
            self.move_focus.emit(self.preset.id, self._NAV_KEYS[key]); return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.run_clicked.emit(self.preset.id); return
        if key == Qt.Key.Key_Space:
            self.paste_clicked.emit(self.preset.id); return
        if key == Qt.Key.Key_F2 and not self.preset.builtin:
            self.edit_clicked.emit(self.preset.id); return
        if key == Qt.Key.Key_Delete and not self.preset.builtin:
            self.delete_clicked.emit(self.preset.id); return
        super().keyPressEvent(event)

    def focusInEvent(self, event) -> None:  # type: ignore[override]
        self._anim.set_focused(True)
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:  # type: ignore[override]
        self._anim.set_focused(False)
        super().focusOutEvent(event)


class PresetsPanel(QWidget):
    preset_run = pyqtSignal(str)
    preset_paste = pyqtSignal(str)

    def __init__(self, manager: PresetManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.manager = manager
        self._theme = "dark"
        self._cards: list[PresetCard] = []   # visual order, for arrow nav

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("Presets")
        title.setProperty("section", True)
        header.addWidget(title, 1)

        add = QPushButton("+ New")
        add.setProperty("chip", True)
        add.clicked.connect(self._on_new)
        header.addWidget(add)
        self._add_btn = add
        layout.addLayout(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(self.scroll, 1)

        self._host = QWidget()
        self._list = QVBoxLayout(self._host)
        self._list.setContentsMargins(2, 2, 2, 2)
        self._list.setSpacing(8)
        self._list.addStretch(1)
        self.scroll.setWidget(self._host)

        self.reload()

    def set_theme(self, theme: str) -> None:
        self._theme = theme
        self.reload()

    def focus_list(self) -> bool:
        """Focus the presets-list group (first preset card). Returns False when
        there are no presets, so Tab skips this group."""
        if not self._cards:
            return False
        self._cards[0].setFocus(Qt.FocusReason.TabFocusReason)
        self.scroll.ensureWidgetVisible(self._cards[0], 0, 20)
        return True

    def focus_nav(self) -> bool:
        """Focus the presets-nav group (the '+ New' button)."""
        self._add_btn.setFocus(Qt.FocusReason.TabFocusReason)
        return True

    def owns_list_focus(self, widget) -> bool:
        return isinstance(widget, PresetCard) and widget in self._cards

    def owns_nav_focus(self, widget) -> bool:
        return widget is self._add_btn

    def _visible_count(self) -> int:
        if not self._cards:
            return 1
        row_h = self._cards[0].height() + self._list.spacing()
        vh = self.scroll.viewport().height()
        return max(1, vh // max(1, row_h))

    def _on_move_focus(self, preset_id: str, direction: str) -> None:
        ids = [c.preset.id for c in self._cards]
        if preset_id not in ids:
            return
        n = len(self._cards)
        i = ids.index(preset_id)
        page = self._visible_count()
        j = {"up": i - 1, "down": i + 1, "home": 0, "end": n - 1,
             "pageup": i - page, "pagedown": i + page}.get(direction)
        if j is None:
            return
        j = max(0, min(n - 1, j))
        if j == i:
            return
        card = self._cards[j]
        card.setFocus(Qt.FocusReason.OtherFocusReason)
        self.scroll.ensureWidgetVisible(card, 0, 20)

    def reload(self) -> None:
        for i in reversed(range(self._list.count() - 1)):
            item = self._list.itemAt(i)
            if item is None:
                continue
            widget = item.widget()
            if widget:
                widget.deleteLater()
                self._list.removeItem(item)
        self._cards.clear()

        for preset in self.manager.list():
            card = PresetCard(preset, self._theme)
            card.run_clicked.connect(self.preset_run.emit)
            card.paste_clicked.connect(self.preset_paste.emit)
            card.edit_clicked.connect(self._on_edit)
            card.delete_clicked.connect(self._on_delete)
            card.move_focus.connect(self._on_move_focus)
            self._list.insertWidget(self._list.count() - 1, card)
            self._cards.append(card)

    def _on_new(self) -> None:
        name, ok = QInputDialog.getText(self, "New preset", "Name:")
        if not ok or not name.strip():
            return
        prompt, ok = QInputDialog.getMultiLineText(self, "New preset", "Prompt:")
        if not ok or not prompt.strip():
            return
        self.manager.create(name.strip(), prompt.strip())
        self.reload()

    def _on_edit(self, preset_id: str) -> None:
        preset = self.manager.get(preset_id)
        if not preset:
            return
        name, ok = QInputDialog.getText(self, "Edit preset", "Name:", QLineEdit.EchoMode.Normal, preset.name)
        if not ok or not name.strip():
            return
        prompt, ok = QInputDialog.getMultiLineText(self, "Edit preset", "Prompt:", preset.prompt)
        if not ok or not prompt.strip():
            return
        self.manager.update(preset_id, name=name.strip(), prompt=prompt.strip(), description=preset.description)
        self.reload()

    def _on_delete(self, preset_id: str) -> None:
        preset = self.manager.get(preset_id)
        if not preset:
            return
        answer = QMessageBox.question(
            self,
            "Delete preset",
            f"Delete '{preset.name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.manager.delete(preset_id)
            self.reload()
