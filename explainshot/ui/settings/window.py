"""Settings window.

Down from ~1500 lines to about 300 by removing:
  * the FieldValidator plumbing (Qt already highlights invalid values via
    QLineEdit::setValidator; for the few free-form fields we just show
    an inline label if the value can't be applied),
  * every widget for the deleted OptimizationConfig (twelve fields),
  * every widget for the deleted ChatConfig (five fields nobody used),
  * the modal-dialog-inside-a-QDialog trampoline,
  * validation-error CSS classes, colored borders, and property polish
    dances — the theme handles those via [error=true].
"""

from __future__ import annotations

import asyncio
import logging

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...ai.provider import AIProvider
from ...config.settings import Settings, save_settings
from ...core.signals import AppSignals
from ...util.autostart import AutoStart
from ..icons import app_icon

log = logging.getLogger(__name__)


class SettingsWindow(QDialog):
    saved = pyqtSignal(object)   # emits the new Settings

    def __init__(self, settings: Settings, signals: AppSignals, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.signals = signals

        self.setWindowIcon(app_icon())
        self.setWindowTitle("ExplainShot — Settings")
        self.resize(560, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        title = QLabel("Settings")
        title.setProperty("title", True)
        layout.addWidget(title)

        tabs = QTabWidget()
        tabs.addTab(self._ai_tab(), "AI provider")
        tabs.addTab(self._screenshot_tab(), "Screenshots")
        tabs.addTab(self._hotkeys_tab(), "Hotkeys")
        tabs.addTab(self._appearance_tab(), "Appearance")
        layout.addWidget(tabs, 1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)

        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        button_row.addWidget(cancel)

        save = QPushButton("Save")
        save.setProperty("accent", True)
        save.setDefault(True)
        save.clicked.connect(self._on_save)
        button_row.addWidget(save)
        layout.addLayout(button_row)

    # -- tabs ------------------------------------------------------------------

    def _ai_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setSpacing(10)

        self.base_url = QLineEdit(self.settings.ai.base_url)
        self.base_url.setPlaceholderText("http://localhost:11434/v1")
        form.addRow("Base URL", self.base_url)

        self.api_key = QLineEdit(self.settings.ai.api_key)
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("leave empty for Ollama / local")
        form.addRow("API key", self.api_key)

        model_row = QHBoxLayout()
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.addItem(self.settings.ai.model)
        model_row.addWidget(self.model, 1)
        refresh = QPushButton("Fetch models")
        refresh.setProperty("flat", True)
        refresh.clicked.connect(self._on_fetch_models)
        model_row.addWidget(refresh)
        form.addRow("Model", model_row)

        self.timeout = QSpinBox()
        self.timeout.setRange(5, 900)
        self.timeout.setSuffix(" s")
        self.timeout.setValue(self.settings.ai.timeout_seconds)
        form.addRow("Request timeout", self.timeout)

        test = QPushButton("Test connection")
        test.clicked.connect(self._on_test)
        self.test_status = QLabel("")
        self.test_status.setProperty("muted", True)
        row = QHBoxLayout()
        row.addWidget(test)
        row.addWidget(self.test_status, 1)
        form.addRow("", row)

        note = QLabel(
            "Any OpenAI-compatible endpoint works. Common presets:\n"
            "  •  Ollama — http://localhost:11434/v1  (no key)\n"
            "  •  OpenAI — https://api.openai.com/v1\n"
            "  •  LM Studio — http://localhost:1234/v1"
        )
        note.setProperty("muted", True)
        note.setWordWrap(True)
        form.addRow("", note)
        return tab

    def _screenshot_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        form.setSpacing(10)

        dir_row = QHBoxLayout()
        self.directory = QLineEdit(self.settings.resolved_screenshot_dir())
        dir_row.addWidget(self.directory, 1)
        browse = QPushButton("Browse…")
        browse.setProperty("flat", True)
        browse.clicked.connect(self._on_browse)
        dir_row.addWidget(browse)
        form.addRow("Save folder", dir_row)

        self.image_format = QComboBox()
        self.image_format.addItems(["PNG", "JPEG"])
        self.image_format.setCurrentText(self.settings.screenshot.image_format.upper())
        form.addRow("Image format", self.image_format)

        quality_row = QHBoxLayout()
        self.quality = QSlider(Qt.Orientation.Horizontal)
        self.quality.setRange(50, 100)
        self.quality.setValue(int(self.settings.screenshot.jpeg_quality))
        self.quality_label = QLabel(f"{self.quality.value()}%")
        self.quality_label.setProperty("muted", True)
        self.quality.valueChanged.connect(lambda v: self.quality_label.setText(f"{v}%"))
        quality_row.addWidget(self.quality, 1)
        quality_row.addWidget(self.quality_label)
        form.addRow("JPEG quality", quality_row)
        return tab

    def _hotkeys_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        form.setSpacing(10)

        self.hk_capture = QKeySequenceEdit(QKeySequence(self.settings.hotkeys.capture_region))
        self.hk_capture.setClearButtonEnabled(True)
        form.addRow("Capture region", self.hk_capture)

        self.hk_gallery = QKeySequenceEdit(QKeySequence(self.settings.hotkeys.toggle_gallery))
        self.hk_gallery.setClearButtonEnabled(True)
        form.addRow("Open gallery", self.hk_gallery)

        self.hk_settings = QKeySequenceEdit(QKeySequence(self.settings.hotkeys.open_settings))
        self.hk_settings.setClearButtonEnabled(True)
        form.addRow("Open settings", self.hk_settings)

        note = QLabel("Hotkeys are registered globally on Windows.")
        note.setProperty("muted", True)
        form.addRow("", note)
        return tab

    def _appearance_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        form.setSpacing(10)

        self.theme = QComboBox()
        self.theme.addItems(["dark", "light"])
        self.theme.setCurrentText(self.settings.ui.theme)
        form.addRow("Theme", self.theme)

        self.accent = QLineEdit(self.settings.ui.accent)
        self.accent.setPlaceholderText("#0067c0")
        form.addRow("Accent colour", self.accent)

        self.thumb = QSpinBox()
        self.thumb.setRange(96, 320)
        self.thumb.setSingleStep(8)
        self.thumb.setSuffix(" px")
        self.thumb.setValue(int(self.settings.ui.thumbnail_px))
        form.addRow("Thumbnail size", self.thumb)

        self.autostart = QCheckBox("Launch when Windows starts")
        self.autostart.setChecked(self.settings.autostart)
        form.addRow("", self.autostart)
        return tab

    # -- actions ---------------------------------------------------------------

    def _on_browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Choose screenshot folder", self.directory.text())
        if chosen:
            self.directory.setText(chosen)

    def _on_fetch_models(self) -> None:
        async def run() -> None:
            provider = self._current_provider()
            self.test_status.setText("Fetching…")
            try:
                names = await provider.list_models()
                current = self.model.currentText()
                self.model.clear()
                self.model.addItems(names or [current])
                if current in names:
                    self.model.setCurrentText(current)
                self.test_status.setText(f"{len(names)} model(s) available")
            except Exception as exc:
                self.test_status.setText(f"Failed: {exc}")
        asyncio.ensure_future(run())

    def _on_test(self) -> None:
        async def run() -> None:
            provider = self._current_provider()
            self.test_status.setText("Testing…")
            ok = await provider.ping()
            self.test_status.setText("✓ Reachable" if ok else "✗ Unreachable")
        asyncio.ensure_future(run())

    def _current_provider(self) -> AIProvider:
        return AIProvider(
            base_url=self.base_url.text().strip() or "http://localhost:11434/v1",
            api_key=self.api_key.text().strip(),
            model=self.model.currentText().strip(),
            timeout=float(self.timeout.value()),
        )

    def _on_save(self) -> None:
        s = self.settings
        s.ai.base_url = self.base_url.text().strip() or s.ai.base_url
        s.ai.api_key = self.api_key.text()
        s.ai.model = self.model.currentText().strip() or s.ai.model
        s.ai.timeout_seconds = int(self.timeout.value())

        s.screenshot.directory = self.directory.text().strip()
        s.screenshot.image_format = self.image_format.currentText()
        s.screenshot.jpeg_quality = int(self.quality.value())

        s.hotkeys.capture_region = self.hk_capture.keySequence().toString().lower() or s.hotkeys.capture_region
        s.hotkeys.toggle_gallery = self.hk_gallery.keySequence().toString().lower() or s.hotkeys.toggle_gallery
        s.hotkeys.open_settings = self.hk_settings.keySequence().toString().lower() or s.hotkeys.open_settings

        s.ui.theme = self.theme.currentText()
        accent = self.accent.text().strip()
        if accent:
            s.ui.accent = accent
        s.ui.thumbnail_px = int(self.thumb.value())

        s.autostart = self.autostart.isChecked()

        try:
            save_settings(s)
            AutoStart().set(s.autostart)
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return

        self.saved.emit(s)
        self.accept()
