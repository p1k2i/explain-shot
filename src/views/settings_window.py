"""
Settings Window Module

Implements the main settings dialog window using PyQt6 with dark theme styling,
form validation, and EventBus integration for the MVC architecture.
"""

import asyncio
import logging
from typing import Optional, Dict, Any, List, Callable
from pathlib import Path

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QTabWidget, QWidget,
    QGroupBox, QLabel, QLineEdit, QPushButton, QComboBox, QCheckBox,
    QSlider, QSpinBox, QKeySequenceEdit, QFileDialog, QProgressBar,
    QSpacerItem, QSizePolicy, QMessageBox
)
from PyQt6.QtGui import QKeySequence

from src.utils.style_loader import load_stylesheet

from ..controllers.event_bus import EventBus
from ..models.settings_manager import SettingsManager, ApplicationSettings
from src import EventTypes

logger = logging.getLogger(__name__)


class FieldValidator:
    """
    Validator for settings form fields with visual feedback.
    """

    def __init__(self, field_widget, error_label):
        self.field_widget = field_widget
        self.error_label = error_label
        self.validation_func = None
        self.error_message = ""

    def set_validation(self, func: Callable[[Any], bool], error_msg: str):
        """Set validation function and error message."""
        self.validation_func = func
        self.error_message = error_msg

    def validate(self) -> bool:
        """Validate field and update UI feedback."""
        if not self.validation_func:
            return True

        # Get field value based on widget type
        if isinstance(self.field_widget, QLineEdit):
            value = self.field_widget.text()
        elif isinstance(self.field_widget, QComboBox):
            value = self.field_widget.currentText()
        elif isinstance(self.field_widget, QSpinBox):
            value = self.field_widget.value()
        elif isinstance(self.field_widget, QSlider):
            value = self.field_widget.value()
        elif isinstance(self.field_widget, QKeySequenceEdit):
            key_sequence = self.field_widget.keySequence()
            value = key_sequence.toString() if key_sequence else ""
        else:
            value = None

        try:
            is_valid = self.validation_func(value)
            logger.debug(f"Validation for {self.field_widget.objectName() if hasattr(self.field_widget, 'objectName') else type(self.field_widget).__name__}: value={repr(value)}, valid={is_valid}")
        except Exception as e:
            logger.warning(f"Validation error for field: {e}")
            is_valid = False

        self._update_ui_feedback(is_valid)
        return is_valid

    def _update_ui_feedback(self, is_valid: bool):
        """Update UI visual feedback based on validation result."""
        if is_valid:
            # Clear error styling by resetting to normal styling
            self.field_widget.setStyleSheet("""
                background-color: #444444;
                border: 1px solid #666666;
                border-radius: 4px;
                padding: 6px;
                color: #FFFFFF;
            """)
            self.error_label.setText("")
            self.error_label.hide()
        else:
            # Apply error styling
            self.field_widget.setStyleSheet("""
                border: 2px solid #FF6B6B;
                background-color: #4A2626;
                border-radius: 4px;
                padding: 6px;
                color: #FFFFFF;
            """)
            self.error_label.setText(self.error_message)
            self.error_label.show()


class SettingsWindow(QDialog):
    """
    Main settings dialog window with dark theme and form validation.

    Provides a modal interface for configuring all application settings
    including Ollama models, screenshot preferences, and hotkeys.
    """

    # Signals for async communication
    settings_save_requested = pyqtSignal(dict)
    settings_cancelled = pyqtSignal()
    model_refresh_requested = pyqtSignal()

    def __init__(
        self,
        event_bus: EventBus,
        settings_manager: SettingsManager,
        ollama_client=None,
        parent=None
    ):
        """
        Initialize the settings window.

        Args:
            event_bus: EventBus for communication
            settings_manager: SettingsManager for data persistence
            ollama_client: OllamaClient for model fetching and connection testing
            parent: Parent widget
        """
        super().__init__(parent)

        self.event_bus = event_bus
        self.settings_manager = settings_manager
        self.ollama_client = ollama_client

        # Current settings data
        self.current_settings: Optional[ApplicationSettings] = None
        self.unsaved_changes = False

        # Form validators
        self.validators: List[FieldValidator] = []

        # Store original stylesheets for hotkey widgets
        self.original_stylesheets: Dict[QKeySequenceEdit, str] = {}

        # UI elements (will be created in setup_ui)
        self.model_dropdown: Optional[QComboBox] = None
        self.server_url_field: Optional[QLineEdit] = None
        self.directory_field: Optional[QLineEdit] = None
        self.format_dropdown: Optional[QComboBox] = None
        self.quality_slider: Optional[QSlider] = None
        self.quality_label: Optional[QLabel] = None
        self.capture_hotkey: Optional[QKeySequenceEdit] = None
        self.overlay_hotkey: Optional[QKeySequenceEdit] = None
        self.settings_hotkey: Optional[QKeySequenceEdit] = None
        self.auto_start_checkbox: Optional[QCheckBox] = None
        self.debug_mode_checkbox: Optional[QCheckBox] = None
        self.cleanup_days_spinbox: Optional[QSpinBox] = None
        self.save_button: Optional[QPushButton] = None
        self.cancel_button: Optional[QPushButton] = None
        self.test_connection_button: Optional[QPushButton] = None
        self.progress_bar: Optional[QProgressBar] = None

        # Setup UI and styling
        self.setup_ui()
        self.setup_styling()
        self.setup_validation()
        self.connect_signals()

        logger.info("SettingsWindow initialized")

    def setup_styling(self):
        """Apply theme styling to the window."""
        theme = self.current_settings.ui.theme if self.current_settings else "dark"
        stylesheet = load_stylesheet("settings", theme, "base")
        if stylesheet:
            self.setStyleSheet(stylesheet)
        else:
            logger.error(f"Failed to load stylesheet for settings/{theme}/base")

    def setup_ui(self):
        """Setup the main UI layout and components."""
        self.setWindowTitle("ExplainScreenshot Settings")
        self.setModal(True)
        self.resize(600, 550)
        self.setMinimumSize(550, 550)

        # Set window flags for modern appearance
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.WindowTitleHint |
            Qt.WindowType.WindowCloseButtonHint
        )

        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(15, 15, 15, 15)

        # Title
        title_label = QLabel("ExplainScreenshot Settings")
        title_label.setObjectName("title_label")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(title_label)

        # Progress bar (hidden by default)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        main_layout.addWidget(self.progress_bar)

        # Tab widget for organized settings
        tab_widget = QTabWidget()
        tab_widget.setObjectName("settings_tabs")

        # General tab
        general_tab = self.create_general_tab()
        tab_widget.addTab(general_tab, "General")

        # Hotkeys tab
        hotkeys_tab = self.create_hotkeys_tab()
        tab_widget.addTab(hotkeys_tab, "Hotkeys")

        # Advanced tab
        advanced_tab = self.create_advanced_tab()
        tab_widget.addTab(advanced_tab, "Advanced")

        main_layout.addWidget(tab_widget)

        # Button layout
        button_layout = self.create_button_layout()
        main_layout.addLayout(button_layout)

    def create_general_tab(self) -> QWidget:
        """Create the general settings tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # AI Model Group
        ai_group = QGroupBox("AI Model Configuration")
        ai_layout = QFormLayout(ai_group)

        # Ollama model dropdown
        self.model_dropdown = QComboBox()
        self.model_dropdown.setObjectName("model_dropdown")
        self.model_dropdown.setMinimumWidth(200)
        model_error_label = QLabel()
        model_error_label.setObjectName("error_label")
        model_error_label.hide()

        model_layout = QVBoxLayout()
        model_layout.addWidget(self.model_dropdown)
        model_layout.addWidget(model_error_label)
        ai_layout.addRow("Ollama Model:", model_layout)

        # Server URL
        self.server_url_field = QLineEdit()
        self.server_url_field.setObjectName("server_url_field")
        self.server_url_field.setPlaceholderText("http://localhost:11434")
        server_error_label = QLabel()
        server_error_label.setObjectName("error_label")
        server_error_label.hide()

        server_layout = QVBoxLayout()
        server_layout.addWidget(self.server_url_field)
        server_layout.addWidget(server_error_label)
        ai_layout.addRow("Server URL:", server_layout)

        # Connection test button
        self.test_connection_button = QPushButton("Test Connection")
        self.test_connection_button.setMaximumWidth(150)
        ai_layout.addRow("", self.test_connection_button)

        layout.addWidget(ai_group)

        # Screenshot Group
        screenshot_group = QGroupBox("Screenshot Configuration")
        screenshot_layout = QFormLayout(screenshot_group)

        # Directory selection
        directory_container = QHBoxLayout()
        self.directory_field = QLineEdit()
        self.directory_field.setObjectName("directory_field")
        self.directory_field.setPlaceholderText("Select screenshot directory...")
        browse_button = QPushButton("Browse...")
        browse_button.setMaximumWidth(80)
        browse_button.clicked.connect(self.browse_directory)

        directory_container.addWidget(self.directory_field)
        directory_container.addWidget(browse_button)

        directory_error_label = QLabel()
        directory_error_label.setObjectName("error_label")
        directory_error_label.hide()

        directory_layout = QVBoxLayout()
        directory_layout.addLayout(directory_container)
        directory_layout.addWidget(directory_error_label)
        screenshot_layout.addRow("Save Directory:", directory_layout)

        # Image format
        self.format_dropdown = QComboBox()
        self.format_dropdown.addItems(["PNG", "JPEG", "BMP", "TIFF"])
        screenshot_layout.addRow("Image Format:", self.format_dropdown)

        # Quality slider
        quality_container = QHBoxLayout()
        self.quality_slider = QSlider(Qt.Orientation.Horizontal)
        self.quality_slider.setRange(1, 100)
        self.quality_slider.setValue(95)
        self.quality_slider.valueChanged.connect(self.update_quality_label)

        self.quality_label = QLabel("95%")
        self.quality_label.setMinimumWidth(40)

        quality_container.addWidget(self.quality_slider)
        quality_container.addWidget(self.quality_label)
        screenshot_layout.addRow("Quality:", quality_container)

        layout.addWidget(screenshot_group)

        # Add validators
        model_validator = FieldValidator(self.model_dropdown, model_error_label)
        model_validator.set_validation(
            lambda x: bool(x and x.strip() and x != "Select a model..."),
            "Please select a valid Ollama model"
        )
        self.validators.append(model_validator)

        server_validator = FieldValidator(self.server_url_field, server_error_label)
        server_validator.set_validation(
            lambda x: bool(x and x.strip() and (x.startswith("http://") or x.startswith("https://"))),
            "Please enter a valid HTTP/HTTPS URL"
        )
        self.validators.append(server_validator)

        directory_validator = FieldValidator(self.directory_field, directory_error_label)
        directory_validator.set_validation(
            lambda x: Path(x.strip()).exists() if x and x.strip() else False,
            "Please select a valid directory"
        )
        self.validators.append(directory_validator)

        return tab

    def create_hotkeys_tab(self) -> QWidget:
        """Create the hotkeys configuration tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Hotkeys group
        hotkeys_group = QGroupBox("Global Hotkeys")
        hotkeys_layout = QFormLayout(hotkeys_group)

        # Screenshot capture hotkey
        self.capture_hotkey = QKeySequenceEdit()
        self.capture_hotkey.setObjectName("capture_hotkey")
        self.capture_hotkey.setMaximumSequenceLength(1)
        capture_error_label = QLabel()
        capture_error_label.setObjectName("error_label")
        capture_error_label.hide()

        capture_layout = QVBoxLayout()
        capture_layout.addWidget(self.capture_hotkey)
        capture_layout.addWidget(capture_error_label)
        hotkeys_layout.addRow("Screenshot Capture:", capture_layout)

        # Overlay toggle hotkey
        self.overlay_hotkey = QKeySequenceEdit()
        self.overlay_hotkey.setObjectName("overlay_hotkey")
        self.overlay_hotkey.setMaximumSequenceLength(1)
        overlay_error_label = QLabel()
        overlay_error_label.setObjectName("error_label")
        overlay_error_label.hide()

        overlay_layout = QVBoxLayout()
        overlay_layout.addWidget(self.overlay_hotkey)
        overlay_layout.addWidget(overlay_error_label)
        hotkeys_layout.addRow("Overlay Toggle:", overlay_layout)

        # Settings window hotkey
        self.settings_hotkey = QKeySequenceEdit()
        self.settings_hotkey.setObjectName("settings_hotkey")
        self.settings_hotkey.setMaximumSequenceLength(1)
        settings_error_label = QLabel()
        settings_error_label.setObjectName("error_label")
        settings_error_label.hide()

        settings_layout = QVBoxLayout()
        settings_layout.addWidget(self.settings_hotkey)
        settings_layout.addWidget(settings_error_label)
        hotkeys_layout.addRow("Settings Window:", settings_layout)

        layout.addWidget(hotkeys_group)

        # Add spacer
        layout.addItem(QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))

        # Add validators for hotkeys
        capture_validator = FieldValidator(self.capture_hotkey, capture_error_label)
        capture_validator.set_validation(
            lambda x: bool(x and x.strip()),
            "Please set a valid hotkey combination"
        )
        self.validators.append(capture_validator)

        overlay_validator = FieldValidator(self.overlay_hotkey, overlay_error_label)
        overlay_validator.set_validation(
            lambda x: bool(x and x.strip()),
            "Please set a valid hotkey combination"
        )
        self.validators.append(overlay_validator)

        settings_validator = FieldValidator(self.settings_hotkey, settings_error_label)
        settings_validator.set_validation(
            lambda x: bool(x and x.strip()),
            "Please set a valid hotkey combination"
        )
        self.validators.append(settings_validator)

        return tab

    def create_advanced_tab(self) -> QWidget:
        """Create the advanced settings tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # System integration group
        system_group = QGroupBox("System Integration")
        system_layout = QFormLayout(system_group)

        # Auto-start checkbox
        self.auto_start_checkbox = QCheckBox("Start with Windows")
        system_layout.addRow("Startup:", self.auto_start_checkbox)

        # Debug mode checkbox
        self.debug_mode_checkbox = QCheckBox("Enable debug logging")
        system_layout.addRow("Debugging:", self.debug_mode_checkbox)

        layout.addWidget(system_group)

        # Maintenance group
        maintenance_group = QGroupBox("Maintenance")
        maintenance_layout = QFormLayout(maintenance_group)

        # Cleanup days spinbox
        self.cleanup_days_spinbox = QSpinBox()
        self.cleanup_days_spinbox.setRange(1, 365)
        self.cleanup_days_spinbox.setValue(30)
        self.cleanup_days_spinbox.setSuffix(" days")
        maintenance_layout.addRow("Auto-cleanup after:", self.cleanup_days_spinbox)

        layout.addWidget(maintenance_group)

        # Add spacer
        layout.addItem(QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))

        return tab

    def create_button_layout(self) -> QHBoxLayout:
        """Create the bottom button layout."""
        button_layout = QHBoxLayout()

        # Add spacer to push buttons to the right
        button_layout.addItem(QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))

        # Reset button
        reset_button = QPushButton("Reset to Defaults")
        reset_button.clicked.connect(self.reset_to_defaults)
        button_layout.addWidget(reset_button)

        # Cancel button
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel_settings)
        button_layout.addWidget(self.cancel_button)

        # Save button
        self.save_button = QPushButton("Save Changes")
        self.save_button.clicked.connect(self.save_settings)
        self.save_button.setDefault(True)
        button_layout.addWidget(self.save_button)

        return button_layout

    def setup_validation(self):
        """Setup real-time validation for form fields."""
        # Connect validation events
        for validator in self.validators:
            if isinstance(validator.field_widget, QLineEdit):
                validator.field_widget.textChanged.connect(self.validate_form)
            elif isinstance(validator.field_widget, QComboBox):
                validator.field_widget.currentTextChanged.connect(self.validate_form)
            elif isinstance(validator.field_widget, QKeySequenceEdit):
                validator.field_widget.keySequenceChanged.connect(self.validate_form)

    def _create_validation_handler(self, validator):
        """Create a validation handler for a specific validator."""
        def handler():
            field_name = validator.field_widget.objectName() if hasattr(validator.field_widget, 'objectName') and validator.field_widget.objectName() else type(validator.field_widget).__name__
            logger.debug(f"Validation handler called for {field_name}")
            validator.validate()
            self.validate_form()
        return handler

    def connect_signals(self):
        """Connect internal signals and slots."""
        # Connect test connection button
        if self.test_connection_button:
            self.test_connection_button.clicked.connect(self.test_ollama_connection)

        # Connect quality slider
        if self.quality_slider:
            self.quality_slider.valueChanged.connect(self.update_quality_label)

        # Install event filters for hotkey visual feedback
        if self.capture_hotkey:
            self.capture_hotkey.installEventFilter(self)
        if self.overlay_hotkey:
            self.overlay_hotkey.installEventFilter(self)
        if self.settings_hotkey:
            self.settings_hotkey.installEventFilter(self)

    def eventFilter(self, a0, a1):
        """Event filter to handle focus events for hotkey fields."""
        from PyQt6.QtCore import QEvent

        if isinstance(a0, QKeySequenceEdit) and a1 is not None:
            if a1.type() == QEvent.Type.FocusIn:
                self._on_hotkey_focus_in(a0)
                return False  # Don't consume the event
            elif a1.type() == QEvent.Type.FocusOut:
                self._on_hotkey_focus_out(a0)
                return False  # Don't consume the event
            elif a1.type() == QEvent.Type.MouseButtonPress:
                # Also highlight on mouse press to handle re-clicking when already focused
                self._on_hotkey_focus_in(a0)
                return False  # Don't consume the event

        return super().eventFilter(a0, a1)

    def _on_hotkey_focus_in(self, hotkey_widget: QKeySequenceEdit):
        """Highlight hotkey field when it gains focus (listening for input)."""
        # Store original stylesheet to restore later
        if hotkey_widget not in self.original_stylesheets:
            self.original_stylesheets[hotkey_widget] = hotkey_widget.styleSheet()

        hotkey_widget.setStyleSheet("""
            QKeySequenceEdit {
                background-color: #FFFF99;
                border: 2px solid #FFA500;
                border-radius: 4px;
                padding: 4px;
                color: #000000;
                font-weight: bold;
            }
        """)
        logger.debug(f"Hotkey field {hotkey_widget.objectName()} is now listening for input")

    def _on_hotkey_focus_out(self, hotkey_widget: QKeySequenceEdit):
        """Reset hotkey field styling when it loses focus."""
        # Restore original stylesheet
        if hotkey_widget in self.original_stylesheets:
            hotkey_widget.setStyleSheet(self.original_stylesheets[hotkey_widget])
            del self.original_stylesheets[hotkey_widget]
        else:
            # Fallback: reset to normal styling
            hotkey_widget.setStyleSheet("""
                background-color: #444444;
                border: 1px solid #666666;
                border-radius: 4px;
                padding: 6px;
                color: #FFFFFF;
            """)
        logger.debug(f"Hotkey field {hotkey_widget.objectName()} stopped listening for input")

    async def initialize(self) -> bool:
        """
        Initialize the settings window with current data.

        Returns:
            True if initialization successful
        """
        try:
            logger.info("Initializing settings window...")

            # Show progress
            if self.progress_bar:
                self.progress_bar.setVisible(True)
                self.progress_bar.setRange(0, 0)  # Indeterminate progress

            # Load current settings
            self.current_settings = await self.settings_manager.load_settings()

            # Load Ollama models
            await self.load_ollama_models()

            # Populate form fields
            self.populate_form_fields()

            # Small delay to ensure all UI updates are processed
            await asyncio.sleep(0.1)

            # Validate form after populating
            self.validate_form()

            # Hide progress
            if self.progress_bar:
                self.progress_bar.setVisible(False)

            # Reset unsaved changes flag
            self.unsaved_changes = False

            logger.info("Settings window initialization complete")
            return True

        except Exception as e:
            logger.error(f"Settings window initialization failed: {e}")
            if self.progress_bar:
                self.progress_bar.setVisible(False)
            return False

    async def load_ollama_models(self):
        """Load available Ollama models into dropdown."""
        try:
            models = []

            if self.ollama_client and self.ollama_client.is_online():
                # Get models from real OllamaClient
                models = await self.ollama_client.get_available_models()
                logger.info(f"Retrieved {len(models)} Ollama models from server")
            else:
                # Fallback: use mock data when offline
                models = [
                    "gemma2:9b",
                    "llama3.1:8b",
                    "qwen2.5:7b",
                    "deepseek-r1:8b",
                    "mistral:7b"
                ]
                logger.info(f"Using fallback models (Ollama offline): {len(models)} models")

            if self.model_dropdown is not None:
                self.model_dropdown.clear()
                self.model_dropdown.addItem("Select a model...")
                self.model_dropdown.addItems(models)

        except Exception as e:
            logger.error(f"Failed to load Ollama models: {e}")
            if self.model_dropdown is not None:
                self.model_dropdown.clear()
                self.model_dropdown.addItem("Error loading models")

    def populate_form_fields(self):
        """Populate form fields with current settings."""
        if not self.current_settings:
            return

        try:
            # AI Model settings
            if self.model_dropdown is not None and self.current_settings.ollama.default_model:
                logger.debug(f"Trying to set model: {self.current_settings.ollama.default_model}")
                index = self.model_dropdown.findText(self.current_settings.ollama.default_model)
                logger.debug(f"Model index found: {index}, current text: {self.model_dropdown.currentText()}")
                if index >= 0:
                    self.model_dropdown.setCurrentIndex(index)
                    logger.debug(f"Set model to index {index}: {self.model_dropdown.currentText()}")
                else:
                    # If the default model is not found, try to find a valid model
                    for i in range(1, self.model_dropdown.count()):  # Skip index 0 ("Select a model...")
                        model_name = self.model_dropdown.itemText(i)
                        if model_name and model_name != "Select a model...":
                            self.model_dropdown.setCurrentIndex(i)
                            logger.debug(f"Fallback: Set model to index {i}: {model_name}")
                            break
                    logger.warning(f"Model '{self.current_settings.ollama.default_model}' not found in dropdown, using fallback")

            if self.server_url_field:
                self.server_url_field.setText(self.current_settings.ollama.server_url)

            # Screenshot settings
            if self.directory_field:
                self.directory_field.setText(self.current_settings.screenshot.save_directory)

            if self.format_dropdown:
                index = self.format_dropdown.findText(self.current_settings.screenshot.image_format.upper())
                if index >= 0:
                    self.format_dropdown.setCurrentIndex(index)

            if self.quality_slider:
                self.quality_slider.setValue(self.current_settings.screenshot.quality)
                self.update_quality_label()

            # Hotkey settings
            if self.capture_hotkey:
                key_seq = QKeySequence(self.current_settings.hotkeys.screenshot_capture)
                self.capture_hotkey.setKeySequence(key_seq)
                logger.debug(f"Set capture hotkey: {key_seq.toString()}, isEmpty: {key_seq.isEmpty()}")

            if self.overlay_hotkey:
                key_seq = QKeySequence(self.current_settings.hotkeys.overlay_toggle)
                self.overlay_hotkey.setKeySequence(key_seq)
                logger.debug(f"Set overlay hotkey: {key_seq.toString()}, isEmpty: {key_seq.isEmpty()}")

            if self.settings_hotkey:
                key_seq = QKeySequence(self.current_settings.hotkeys.settings_open)
                self.settings_hotkey.setKeySequence(key_seq)
                logger.debug(f"Set settings hotkey: {key_seq.toString()}, isEmpty: {key_seq.isEmpty()}")

            # Advanced settings
            if self.auto_start_checkbox:
                self.auto_start_checkbox.setChecked(self.current_settings.auto_start.enabled)

            if self.debug_mode_checkbox:
                self.debug_mode_checkbox.setChecked(self.current_settings.debug_mode)

            if self.cleanup_days_spinbox:
                self.cleanup_days_spinbox.setValue(self.current_settings.screenshot.auto_cleanup_days)

        except Exception as e:
            logger.error(f"Error populating form fields: {e}")

    def collect_form_data(self) -> Dict[str, Any]:
        """
        Collect all form data into a dictionary.

        Returns:
            Dictionary with current form values
        """
        try:
            data = {
                "ollama": {
                    "default_model": self.model_dropdown.currentText() if self.model_dropdown is not None else "",
                    "server_url": self.server_url_field.text() if self.server_url_field else "",
                },
                "screenshot": {
                    "save_directory": self.directory_field.text() if self.directory_field else "",
                    "image_format": self.format_dropdown.currentText() if self.format_dropdown else "PNG",
                    "quality": self.quality_slider.value() if self.quality_slider else 95,
                    "auto_cleanup_days": self.cleanup_days_spinbox.value() if self.cleanup_days_spinbox else 30,
                },
                "hotkeys": {
                    "screenshot_capture": self.capture_hotkey.keySequence().toString() if self.capture_hotkey else "",
                    "overlay_toggle": self.overlay_hotkey.keySequence().toString() if self.overlay_hotkey else "",
                    "settings_open": self.settings_hotkey.keySequence().toString() if self.settings_hotkey else "",
                },
                "advanced": {
                    "auto_start": self.auto_start_checkbox.isChecked() if self.auto_start_checkbox else False,
                    "debug_mode": self.debug_mode_checkbox.isChecked() if self.debug_mode_checkbox else False,
                }
            }

            return data

        except Exception as e:
            logger.error(f"Error collecting form data: {e}")
            return {}

    def validate_form(self) -> bool:
        """
        Validate all form fields.

        Returns:
            True if all fields are valid
        """
        logger.debug("validate_form() called")
        all_valid = True
        failed_validators = []

        for validator in self.validators:
            if not validator.validate():
                all_valid = False
                field_name = validator.field_widget.objectName() if hasattr(validator.field_widget, 'objectName') and validator.field_widget.objectName() else type(validator.field_widget).__name__
                failed_validators.append(field_name)

        logger.debug(f"Form validation: all_valid={all_valid}, failed={failed_validators}")

        # Enable/disable save button based on validation
        if self.save_button:
            self.save_button.setEnabled(all_valid)
            logger.debug(f"Save button enabled: {all_valid}")

        return all_valid

    def update_quality_label(self):
        """Update the quality percentage label."""
        if self.quality_slider and self.quality_label:
            value = self.quality_slider.value()
            self.quality_label.setText(f"{value}%")

    def browse_directory(self):
        """Open directory selection dialog."""
        try:
            current_dir = self.directory_field.text() if self.directory_field else ""
            if not current_dir or not Path(current_dir).exists():
                current_dir = str(Path.home() / "Screenshots")

            selected_dir = QFileDialog.getExistingDirectory(
                self,
                "Select Screenshot Directory",
                current_dir,
                QFileDialog.Option.ShowDirsOnly
            )

            if selected_dir and self.directory_field:
                self.directory_field.setText(selected_dir)
                self.unsaved_changes = True
                self.validate_form()

        except Exception as e:
            logger.error(f"Error in directory selection: {e}")

    def test_ollama_connection(self):
        """Test connection to Ollama server."""
        async def _test_connection():
            try:
                if self.test_connection_button:
                    self.test_connection_button.setEnabled(False)
                    self.test_connection_button.setText("Testing...")

                server_url = self.server_url_field.text() if self.server_url_field else ""

                if self.ollama_client:
                    # Test with real OllamaClient
                    try:
                        # Save current server URL and temporarily update it for testing
                        original_server = self.ollama_client.server_url
                        self.ollama_client.server_url = server_url

                        # Perform health check
                        success = await self.ollama_client._perform_health_check()

                        # Restore original server URL
                        self.ollama_client.server_url = original_server

                        if success:
                            models = self.ollama_client._available_models
                            QMessageBox.information(
                                self,
                                "Connection Test",
                                f"Connection successful!\n\nServer: {server_url}\nAvailable Models: {len(models)}\nModels: {', '.join(models[:3])}{'...' if len(models) > 3 else ''}"
                            )
                        else:
                            QMessageBox.warning(
                                self,
                                "Connection Test",
                                f"Connection failed!\n\nServer: {server_url}\nUnable to connect to Ollama server.\nPlease check that Ollama is running and accessible."
                            )
                    except Exception as e:
                        QMessageBox.warning(
                            self,
                            "Connection Test",
                            f"Connection failed!\n\nServer: {server_url}\nError: {str(e)}"
                        )
                else:
                    # Fallback when no OllamaClient available
                    QMessageBox.warning(
                        self,
                        "Connection Test",
                        f"Cannot test connection!\n\nOllamaClient not available.\nServer: {server_url}"
                    )

            except Exception as e:
                logger.error(f"Connection test error: {e}")
                QMessageBox.critical(
                    self,
                    "Connection Test",
                    f"Test failed with error:\n{str(e)}"
                )
            finally:
                if self.test_connection_button:
                    self.test_connection_button.setEnabled(True)
                    self.test_connection_button.setText("Test Connection")

        # Run async test
        asyncio.create_task(_test_connection())

    def save_settings(self):
        """Save current settings."""
        try:
            if not self.validate_form():
                QMessageBox.warning(
                    self,
                    "Validation Error",
                    "Please correct the validation errors before saving."
                )
                return

            # Collect form data
            form_data = self.collect_form_data()

            # Create a task to save settings asynchronously
            asyncio.create_task(self._save_settings_async(form_data))

        except Exception as e:
            logger.error(f"Error saving settings: {e}")
            QMessageBox.critical(
                self,
                "Save Error",
                f"Failed to save settings:\n{str(e)}"
            )

    async def _save_settings_async(self, form_data: Dict[str, Any]):
        """Save settings asynchronously."""
        try:
            # Update settings in SettingsManager
            success_count = 0
            total_updates = 0
            failed_updates = []

            # Update Ollama settings
            ollama_data = form_data.get("ollama", {})
            if ollama_data.get("default_model") and ollama_data["default_model"] != "Select a model...":
                total_updates += 1
                if await self.settings_manager.update_setting("ollama.default_model", ollama_data["default_model"]):
                    success_count += 1
                else:
                    failed_updates.append("ollama.default_model")

            if ollama_data.get("server_url"):
                total_updates += 1
                if await self.settings_manager.update_setting("ollama.server_url", ollama_data["server_url"]):
                    success_count += 1
                else:
                    failed_updates.append("ollama.server_url")

            # Update screenshot settings
            screenshot_data = form_data.get("screenshot", {})
            if screenshot_data.get("save_directory"):
                total_updates += 1
                if await self.settings_manager.update_setting("screenshot.save_directory", screenshot_data["save_directory"]):
                    success_count += 1
                else:
                    failed_updates.append("screenshot.save_directory")

            if screenshot_data.get("image_format"):
                total_updates += 1
                if await self.settings_manager.update_setting("screenshot.image_format", screenshot_data["image_format"]):
                    success_count += 1
                else:
                    failed_updates.append("screenshot.image_format")

            if "quality" in screenshot_data:
                total_updates += 1
                if await self.settings_manager.update_setting("screenshot.quality", screenshot_data["quality"]):
                    success_count += 1
                else:
                    failed_updates.append("screenshot.quality")

            if "auto_cleanup_days" in screenshot_data:
                total_updates += 1
                if await self.settings_manager.update_setting("screenshot.auto_cleanup_days", screenshot_data["auto_cleanup_days"]):
                    success_count += 1
                else:
                    failed_updates.append("screenshot.auto_cleanup_days")

            # Update hotkey settings
            hotkeys_data = form_data.get("hotkeys", {})
            if hotkeys_data.get("screenshot_capture"):
                total_updates += 1
                if await self.settings_manager.update_setting("hotkeys.screenshot_capture", hotkeys_data["screenshot_capture"]):
                    success_count += 1
                else:
                    failed_updates.append("hotkeys.screenshot_capture")

            if hotkeys_data.get("overlay_toggle"):
                total_updates += 1
                if await self.settings_manager.update_setting("hotkeys.overlay_toggle", hotkeys_data["overlay_toggle"]):
                    success_count += 1
                else:
                    failed_updates.append("hotkeys.overlay_toggle")

            if hotkeys_data.get("settings_open"):
                total_updates += 1
                if await self.settings_manager.update_setting("hotkeys.settings_open", hotkeys_data["settings_open"]):
                    success_count += 1
                else:
                    failed_updates.append("hotkeys.settings_open")

            # Update advanced settings
            advanced_data = form_data.get("advanced", {})
            if "auto_start" in advanced_data:
                total_updates += 1
                if await self.settings_manager.update_setting("auto_start.enabled", advanced_data["auto_start"]):
                    success_count += 1
                else:
                    failed_updates.append("auto_start.enabled")

            if "debug_mode" in advanced_data:
                total_updates += 1
                if await self.settings_manager.update_setting("debug_mode", advanced_data["debug_mode"]):
                    success_count += 1
                else:
                    failed_updates.append("debug_mode")

            # Save all settings to persist changes
            await self.settings_manager.save_settings()

            # Emit completion events
            await self.event_bus.emit(
                EventTypes.SETTINGS_SAVE_REQUESTED,
                form_data,
                source="SettingsWindow"
            )

            await self.event_bus.emit(
                EventTypes.SETTINGS_SAVED,
                {
                    "success_count": success_count,
                    "total_updates": total_updates,
                    "failed_updates": failed_updates,
                    "form_data": form_data
                },
                source="SettingsWindow"
            )

            # Show success message on main thread
            if failed_updates:
                QMessageBox.warning(
                    self,
                    "Partial Save",
                    f"Settings partially saved:\n\n{success_count}/{total_updates} settings updated successfully.\n\nFailed updates: {', '.join(failed_updates)}"
                )
            else:
                QMessageBox.information(
                    self,
                    "Settings Saved",
                    f"All settings saved successfully!\n\n{success_count} settings updated and persisted."
                )

            # Reset unsaved changes flag and close dialog
            self.unsaved_changes = False
            self.accept()

        except Exception as e:
            logger.error(f"Error in async settings save: {e}")
            QMessageBox.critical(
                self,
                "Save Error",
                f"Failed to save settings:\n{str(e)}"
            )

    def cancel_settings(self):
        """Cancel settings changes."""
        if self.unsaved_changes:
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                "You have unsaved changes. Are you sure you want to cancel?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )

            if reply != QMessageBox.StandardButton.Yes:
                return

        logger.info("Settings dialog cancelled")

        # Emit window closed event
        asyncio.create_task(self.event_bus.emit(
            EventTypes.SETTINGS_WINDOW_CLOSED,
            {"reason": "cancelled"},
            source="SettingsWindow"
        ))

        self.reject()

    def reset_to_defaults(self):
        """Reset all settings to defaults."""
        reply = QMessageBox.question(
            self,
            "Reset to Defaults",
            "This will reset all settings to their default values. Are you sure?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            # Create a task to reset settings asynchronously
            asyncio.create_task(self._reset_to_defaults_async())

    async def _reset_to_defaults_async(self):
        """Reset settings to defaults asynchronously."""
        try:
            logger.info("Resetting settings to defaults")

            # Reset all settings sections to defaults
            await self.settings_manager.reset_to_defaults()

            # Reload the current settings
            self.current_settings = await self.settings_manager.load_settings()

            # Repopulate form fields with default values
            self.populate_form_fields()

            # Reset validation state
            self.validate_form()

            # Reset unsaved changes flag
            self.unsaved_changes = False

            # Show success message
            QMessageBox.information(
                self,
                "Reset Complete",
                "All settings have been reset to their default values.\n\nChanges have been saved automatically."
            )

            logger.info("Settings reset to defaults completed")

        except Exception as e:
            logger.error(f"Error resetting settings to defaults: {e}")
            QMessageBox.critical(
                self,
                "Reset Error",
                f"Failed to reset settings to defaults:\n{str(e)}"
            )

    def closeEvent(self, a0):
        """Handle window close event."""
        if self.unsaved_changes:
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                "You have unsaved changes. Are you sure you want to close?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )

            if reply != QMessageBox.StandardButton.Yes:
                if a0:
                    a0.ignore()
                return

        logger.info("Settings window closed")
        if a0:
            a0.accept()
