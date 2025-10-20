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
    QSpacerItem, QSizePolicy, QMessageBox, QScrollArea
)
from PyQt6.QtGui import QKeySequence

from src.utils.style_loader import load_stylesheets
from src.utils.icon_manager import get_icon_manager

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
            # Apply normal field styling using CSS class
            self.field_widget.setProperty("error", False)
            self.error_label.setText("")
            self.error_label.hide()
        else:
            # Apply error styling using CSS class
            self.field_widget.setProperty("error", True)
            self.error_label.setText(self.error_message)
            self.error_label.show()

        # Force style refresh
        style = self.field_widget.style()
        if style:
            style.polish(self.field_widget)


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

        # Optimization settings widgets
        self.opt_storage_enabled: Optional[QCheckBox] = None
        self.opt_max_storage_gb: Optional[QSpinBox] = None
        self.opt_max_file_count: Optional[QSpinBox] = None
        self.opt_auto_cleanup: Optional[QCheckBox] = None
        self.opt_thumbnail_enabled: Optional[QCheckBox] = None
        self.opt_thumbnail_cache_size: Optional[QSpinBox] = None
        self.opt_thumbnail_quality: Optional[QSlider] = None
        self.opt_thumbnail_quality_label: Optional[QLabel] = None
        self.opt_request_pooling: Optional[QCheckBox] = None
        self.opt_max_concurrent: Optional[QSpinBox] = None
        self.opt_request_timeout: Optional[QSpinBox] = None

        # Setup UI and styling
        self.setup_ui()
        self.setup_styling()
        self.setup_validation()
        self.connect_signals()

        logger.info("SettingsWindow initialized")

    def setup_styling(self):
        """Apply theme styling to the window."""
        theme = self.current_settings.ui.theme if self.current_settings else "dark"
        stylesheet = load_stylesheets("settings", theme, ["base", "validation"])
        if stylesheet:
            self.setStyleSheet(stylesheet)
        else:
            logger.error(f"Failed to load stylesheets for settings/{theme}")

    def setup_ui(self):
        """Setup the main UI layout and components."""
        self.setWindowTitle("ExplainShot Settings")

        # Set window icon
        icon_manager = get_icon_manager()
        app_icon = icon_manager.get_app_icon()
        if app_icon:
            self.setWindowIcon(app_icon)

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
        title_label = QLabel("ExplainShot Settings")
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

        # Optimization tab
        optimization_tab = self.create_optimization_tab()
        tab_widget.addTab(optimization_tab, "Performance")

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

        # UI Group
        ui_group = QGroupBox("User Interface")
        ui_layout = QFormLayout(ui_group)

        # Gallery opacity slider
        gallery_opacity_container = QHBoxLayout()
        self.gallery_opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.gallery_opacity_slider.setRange(75, 100)
        self.gallery_opacity_slider.setValue(93)
        self.gallery_opacity_slider.valueChanged.connect(self.update_gallery_opacity_label)

        self.gallery_opacity_label = QLabel("93%")
        self.gallery_opacity_label.setMinimumWidth(40)

        gallery_opacity_container.addWidget(self.gallery_opacity_slider)
        gallery_opacity_container.addWidget(self.gallery_opacity_label)
        ui_layout.addRow("Gallery Transparency:", gallery_opacity_container)

        layout.addWidget(ui_group)
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

    def create_optimization_tab(self) -> QWidget:
        """Create the performance optimization settings tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Create scroll area for the optimization settings
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)

        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)

        # Storage Management Group
        storage_group = QGroupBox("Storage Management")
        storage_layout = QFormLayout(storage_group)

        # Storage management enabled
        self.opt_storage_enabled = QCheckBox("Enable automatic storage management")
        self.opt_storage_enabled.setToolTip("Automatically manage screenshot storage with configurable limits")
        storage_layout.addRow(self.opt_storage_enabled)

        # Max storage
        self.opt_max_storage_gb = QSpinBox()
        self.opt_max_storage_gb.setRange(1, 100)
        self.opt_max_storage_gb.setValue(10)
        self.opt_max_storage_gb.setSuffix(" GB")
        self.opt_max_storage_gb.setToolTip("Maximum storage space for screenshots (1-100 GB)")
        storage_layout.addRow("Storage Limit:", self.opt_max_storage_gb)

        # Max file count
        self.opt_max_file_count = QSpinBox()
        self.opt_max_file_count.setRange(100, 50000)
        self.opt_max_file_count.setValue(1000)
        self.opt_max_file_count.setToolTip("Maximum number of screenshot files (100-50,000)")
        storage_layout.addRow("Max Files:", self.opt_max_file_count)

        # Auto cleanup
        self.opt_auto_cleanup = QCheckBox("Enable automatic cleanup")
        self.opt_auto_cleanup.setToolTip("Automatically remove old screenshots when limits are exceeded")
        storage_layout.addRow(self.opt_auto_cleanup)

        scroll_layout.addWidget(storage_group)

        # Thumbnail Optimization Group
        thumbnail_group = QGroupBox("Thumbnail Optimization")
        thumbnail_layout = QFormLayout(thumbnail_group)

        # Thumbnail cache enabled
        self.opt_thumbnail_enabled = QCheckBox("Enable thumbnail caching")
        self.opt_thumbnail_enabled.setToolTip("Cache thumbnails for faster gallery loading")
        thumbnail_layout.addRow(self.opt_thumbnail_enabled)

        # Thumbnail cache size
        self.opt_thumbnail_cache_size = QSpinBox()
        self.opt_thumbnail_cache_size.setRange(10, 1000)
        self.opt_thumbnail_cache_size.setValue(100)
        self.opt_thumbnail_cache_size.setToolTip("Number of thumbnails to keep in memory")
        thumbnail_layout.addRow("Cache Size:", self.opt_thumbnail_cache_size)

        # Thumbnail quality slider
        thumbnail_quality_container = QHBoxLayout()
        self.opt_thumbnail_quality = QSlider(Qt.Orientation.Horizontal)
        self.opt_thumbnail_quality.setRange(50, 100)
        self.opt_thumbnail_quality.setValue(85)
        self.opt_thumbnail_quality.setToolTip("Thumbnail image quality (higher = better quality, more memory)")
        self.opt_thumbnail_quality.valueChanged.connect(self.update_thumbnail_quality_label)

        self.opt_thumbnail_quality_label = QLabel("85%")
        self.opt_thumbnail_quality_label.setMinimumWidth(40)

        thumbnail_quality_container.addWidget(QLabel("Low"))
        thumbnail_quality_container.addWidget(self.opt_thumbnail_quality)
        thumbnail_quality_container.addWidget(QLabel("High"))
        thumbnail_quality_container.addWidget(self.opt_thumbnail_quality_label)

        thumbnail_layout.addRow("Thumbnail Quality:", thumbnail_quality_container)

        scroll_layout.addWidget(thumbnail_group)

        # Request Optimization Group
        request_group = QGroupBox("Request Optimization")
        request_layout = QFormLayout(request_group)

        # Request pooling
        self.opt_request_pooling = QCheckBox("Enable request pooling")
        self.opt_request_pooling.setToolTip("Pool and queue AI requests for better performance")
        request_layout.addRow(self.opt_request_pooling)

        # Max concurrent requests
        self.opt_max_concurrent = QSpinBox()
        self.opt_max_concurrent.setRange(1, 10)
        self.opt_max_concurrent.setValue(3)
        self.opt_max_concurrent.setToolTip("Maximum simultaneous AI requests (1-10)")
        request_layout.addRow("Max Concurrent:", self.opt_max_concurrent)

        # Request timeout
        self.opt_request_timeout = QSpinBox()
        self.opt_request_timeout.setRange(5, 300)
        self.opt_request_timeout.setValue(30)
        self.opt_request_timeout.setSuffix(" seconds")
        self.opt_request_timeout.setToolTip("Timeout for individual AI requests (5-300 seconds)")
        request_layout.addRow("Request Timeout:", self.opt_request_timeout)

        scroll_layout.addWidget(request_group)

        # Add stretch to push everything to the top
        scroll_layout.addStretch()

        scroll_area.setWidget(scroll_widget)
        layout.addWidget(scroll_area)

        # Setup optimization settings validation
        self.setup_optimization_validation()

        return tab

    def setup_optimization_validation(self):
        """Setup validation for optimization settings."""
        # Add validators for optimization settings if needed
        # Most optimization settings have built-in range validation via QSpinBox
        pass

    def update_thumbnail_quality_label(self):
        """Update the thumbnail quality percentage label."""
        if self.opt_thumbnail_quality and self.opt_thumbnail_quality_label:
            value = self.opt_thumbnail_quality.value()
            self.opt_thumbnail_quality_label.setText(f"{value}%")

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
        hotkey_widget.setProperty("listening", True)
        # Force style refresh
        style = hotkey_widget.style()
        if style:
            style.polish(hotkey_widget)
        logger.debug(f"Hotkey field {hotkey_widget.objectName()} is now listening for input")

    def _on_hotkey_focus_out(self, hotkey_widget: QKeySequenceEdit):
        """Reset hotkey field styling when it loses focus."""
        hotkey_widget.setProperty("listening", False)
        # Force style refresh
        style = hotkey_widget.style()
        if style:
            style.polish(hotkey_widget)
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
                self.progress_bar.setRange(0, 0) # Indeterminate progress

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

            if self.gallery_opacity_slider:
                opacity_value = int(self.current_settings.ui.gallery_opacity * 100)
                self.gallery_opacity_slider.setValue(opacity_value)
                self.update_gallery_opacity_label()

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

            # Optimization settings
            if hasattr(self.current_settings, 'optimization'):
                opt = self.current_settings.optimization

                # Storage settings
                if self.opt_storage_enabled:
                    self.opt_storage_enabled.setChecked(opt.storage_management_enabled)
                if self.opt_max_storage_gb:
                    self.opt_max_storage_gb.setValue(int(opt.max_storage_gb))
                if self.opt_max_file_count:
                    self.opt_max_file_count.setValue(opt.max_file_count)
                if self.opt_auto_cleanup:
                    self.opt_auto_cleanup.setChecked(opt.auto_cleanup_enabled)

                # Thumbnail settings
                if self.opt_thumbnail_enabled:
                    self.opt_thumbnail_enabled.setChecked(opt.thumbnail_cache_enabled)
                if self.opt_thumbnail_cache_size:
                    self.opt_thumbnail_cache_size.setValue(opt.thumbnail_cache_size)
                if self.opt_thumbnail_quality:
                    self.opt_thumbnail_quality.setValue(opt.thumbnail_quality)
                    self.update_thumbnail_quality_label()

                # Request settings
                if self.opt_request_pooling:
                    self.opt_request_pooling.setChecked(opt.request_pooling_enabled)
                if self.opt_max_concurrent:
                    self.opt_max_concurrent.setValue(opt.max_concurrent_requests)
                if self.opt_request_timeout:
                    self.opt_request_timeout.setValue(int(opt.request_timeout))

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
                "ui": {
                    "gallery_opacity": (self.gallery_opacity_slider.value() / 100.0) if self.gallery_opacity_slider else 0.95,
                },
                "hotkeys": {
                    "screenshot_capture": self.capture_hotkey.keySequence().toString() if self.capture_hotkey else "",
                    "overlay_toggle": self.overlay_hotkey.keySequence().toString() if self.overlay_hotkey else "",
                    "settings_open": self.settings_hotkey.keySequence().toString() if self.settings_hotkey else "",
                },
                "advanced": {
                    "auto_start": self.auto_start_checkbox.isChecked() if self.auto_start_checkbox else False,
                    "debug_mode": self.debug_mode_checkbox.isChecked() if self.debug_mode_checkbox else False,
                },
                "optimization": {
                    # Storage settings
                    "storage_management_enabled": self.opt_storage_enabled.isChecked() if self.opt_storage_enabled else True,
                    "max_storage_gb": float(self.opt_max_storage_gb.value()) if self.opt_max_storage_gb else 10.0,
                    "max_file_count": self.opt_max_file_count.value() if self.opt_max_file_count else 1000,
                    "auto_cleanup_enabled": self.opt_auto_cleanup.isChecked() if self.opt_auto_cleanup else True,

                    # Thumbnail settings
                    "thumbnail_cache_enabled": self.opt_thumbnail_enabled.isChecked() if self.opt_thumbnail_enabled else True,
                    "thumbnail_cache_size": self.opt_thumbnail_cache_size.value() if self.opt_thumbnail_cache_size else 100,
                    "thumbnail_quality": self.opt_thumbnail_quality.value() if self.opt_thumbnail_quality else 85,

                    # Request settings
                    "request_pooling_enabled": self.opt_request_pooling.isChecked() if self.opt_request_pooling else True,
                    "max_concurrent_requests": self.opt_max_concurrent.value() if self.opt_max_concurrent else 3,
                    "request_timeout": float(self.opt_request_timeout.value()) if self.opt_request_timeout else 30.0,
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

    def update_gallery_opacity_label(self):
        """Update the gallery opacity percentage label."""
        if self.gallery_opacity_slider and self.gallery_opacity_label:
            value = self.gallery_opacity_slider.value()
            self.gallery_opacity_label.setText(f"{value}%")

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

            # Update UI settings
            ui_data = form_data.get("ui", {})
            if "gallery_opacity" in ui_data:
                total_updates += 1
                if await self.settings_manager.update_setting("ui.gallery_opacity", ui_data["gallery_opacity"]):
                    success_count += 1
                else:
                    failed_updates.append("ui.gallery_opacity")

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
