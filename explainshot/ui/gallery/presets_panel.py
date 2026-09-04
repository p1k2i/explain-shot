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


class PresetCard(QWidget):
    run_clicked = pyqtSignal(str)
    paste_clicked = pyqtSignal(str)
    edit_clicked = pyqtSignal(str)
    delete_clicked = pyqtSignal(str)

    def __init__(self, preset: Preset, theme: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.preset = preset
        self.setObjectName("PresetCard")

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
        run.clicked.connect(lambda: self.run_clicked.emit(preset.id))
        actions.addWidget(run)

        paste = QPushButton("Paste")
        paste.setProperty("flat", True)
        paste.clicked.connect(lambda: self.paste_clicked.emit(preset.id))
        actions.addWidget(paste)

        actions.addStretch(1)

        if not preset.builtin:
            edit = QPushButton("Edit")
            edit.setProperty("flat", True)
            edit.clicked.connect(lambda: self.edit_clicked.emit(preset.id))
            actions.addWidget(edit)

            delete = QPushButton("Delete")
            delete.setProperty("flat", True)
            delete.setProperty("danger", True)
            delete.clicked.connect(lambda: self.delete_clicked.emit(preset.id))
            actions.addWidget(delete)
        layout.addLayout(actions)

        states = _STATES_DARK if theme == "dark" else _STATES_LIGHT
        HoverAnimator.attach(self, states)


class PresetsPanel(QWidget):
    preset_run = pyqtSignal(str)
    preset_paste = pyqtSignal(str)

    def __init__(self, manager: PresetManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.manager = manager
        self._theme = "dark"

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

    def reload(self) -> None:
        for i in reversed(range(self._list.count() - 1)):
            item = self._list.itemAt(i)
            if item is None:
                continue
            widget = item.widget()
            if widget:
                widget.deleteLater()
                self._list.removeItem(item)

        for preset in self.manager.list():
            card = PresetCard(preset, self._theme)
            card.run_clicked.connect(self.preset_run.emit)
            card.paste_clicked.connect(self.preset_paste.emit)
            card.edit_clicked.connect(self._on_edit)
            card.delete_clicked.connect(self._on_delete)
            self._list.insertWidget(self._list.count() - 1, card)

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
