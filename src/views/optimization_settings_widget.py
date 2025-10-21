"""
Optimization Settings UI Extension.

This module provides UI components for configuring performance
optimization settings in the settings window.
"""

import logging
from typing import Optional, Any, TYPE_CHECKING
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QCheckBox, QSpinBox, QDoubleSpinBox, QSlider, QLabel,
    QPushButton, QTabWidget, QScrollArea
)
from PyQt6.QtCore import Qt, pyqtSignal

if TYPE_CHECKING:
    from ..models.settings_manager import SettingsManager, OptimizationConfig

logger = logging.getLogger(__name__)


class OptimizationSettingsWidget(QWidget):
    """
    Widget for configuring performance optimization settings.

    Provides a tabbed interface for different optimization categories
    with real-time validation and preview of changes.
    """

    settings_changed = pyqtSignal(str, object)  # setting_key, value
    optimization_test_requested = pyqtSignal()

    def __init__(self, settings_manager: 'SettingsManager', parent=None):
        """
        Initialize optimization settings widget.

        Args:
            settings_manager: SettingsManager instance
            parent: Parent widget
        """
        super().__init__(parent)
        self.settings_manager = settings_manager
        self.logger = logger

        # Current optimization config
        self.optimization_config: Optional['OptimizationConfig'] = None

        # UI components
        self.storage_widgets = {}
        self.thumbnail_widgets = {}
        self.request_widgets = {}

        self.setup_ui()
        self.connect_signals()

    def setup_ui(self) -> None:
        """Setup the user interface."""
        layout = QVBoxLayout(self)

        # Create tabbed interface
        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget)

        # Add optimization tabs
        self.setup_storage_tab()
        self.setup_thumbnail_tab()
        self.setup_request_tab()

        # Add control buttons
        self.setup_control_buttons(layout)

    def setup_storage_tab(self) -> None:
        """Setup storage management settings tab."""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)

        storage_widget = QWidget()
        layout = QVBoxLayout(storage_widget)

        # Storage management group
        storage_group = QGroupBox("Storage Management")
        storage_layout = QFormLayout(storage_group)

        # Storage management enabled
        self.storage_widgets['enabled'] = QCheckBox("Enable automatic storage management")
        self.storage_widgets['enabled'].setToolTip("Automatically clean up old screenshots")
        storage_layout.addRow(self.storage_widgets['enabled'])

        # Max storage GB
        self.storage_widgets['max_gb'] = QDoubleSpinBox()
        self.storage_widgets['max_gb'].setRange(1.0, 100.0)
        self.storage_widgets['max_gb'].setSuffix(" GB")
        self.storage_widgets['max_gb'].setDecimals(1)
        self.storage_widgets['max_gb'].setToolTip("Maximum storage space for screenshots")
        storage_layout.addRow("Storage Limit:", self.storage_widgets['max_gb'])

        # Max file count
        self.storage_widgets['max_files'] = QSpinBox()
        self.storage_widgets['max_files'].setRange(100, 50000)
        self.storage_widgets['max_files'].setToolTip("Maximum number of screenshot files")
        storage_layout.addRow("Max Files:", self.storage_widgets['max_files'])

        # Cleanup interval
        self.storage_widgets['cleanup_interval'] = QSpinBox()
        self.storage_widgets['cleanup_interval'].setRange(1, 168)
        self.storage_widgets['cleanup_interval'].setSuffix(" hours")
        self.storage_widgets['cleanup_interval'].setToolTip("How often to check for cleanup")
        storage_layout.addRow("Cleanup Interval:", self.storage_widgets['cleanup_interval'])

        # Auto cleanup enabled
        self.storage_widgets['auto_cleanup'] = QCheckBox("Enable automatic cleanup")
        self.storage_widgets['auto_cleanup'].setToolTip("Automatically remove old files when limits exceeded")
        storage_layout.addRow(self.storage_widgets['auto_cleanup'])

        layout.addWidget(storage_group)

        # Storage statistics group
        stats_group = QGroupBox("Storage Statistics")
        stats_layout = QFormLayout(stats_group)

        self.storage_used_label = QLabel("--")
        self.storage_files_label = QLabel("--")
        self.storage_oldest_label = QLabel("--")

        stats_layout.addRow("Storage Used:", self.storage_used_label)
        stats_layout.addRow("Total Files:", self.storage_files_label)
        stats_layout.addRow("Oldest File:", self.storage_oldest_label)

        # Cleanup now button
        cleanup_btn = QPushButton("Run Cleanup Now")
        cleanup_btn.clicked.connect(self.run_storage_cleanup)
        stats_layout.addRow(cleanup_btn)

        layout.addWidget(stats_group)
        layout.addStretch()

        scroll_area.setWidget(storage_widget)
        self.tab_widget.addTab(scroll_area, "Storage")

    def setup_thumbnail_tab(self) -> None:
        """Setup thumbnail optimization settings tab."""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)

        thumbnail_widget = QWidget()
        layout = QVBoxLayout(thumbnail_widget)

        # Thumbnail settings group
        thumb_group = QGroupBox("Thumbnail Optimization")
        thumb_layout = QFormLayout(thumb_group)

        # Thumbnail cache enabled
        self.thumbnail_widgets['enabled'] = QCheckBox("Enable thumbnail caching")
        self.thumbnail_widgets['enabled'].setToolTip("Cache thumbnails for faster gallery loading")
        thumb_layout.addRow(self.thumbnail_widgets['enabled'])

        # Cache size
        self.thumbnail_widgets['cache_size'] = QSpinBox()
        self.thumbnail_widgets['cache_size'].setRange(10, 1000)
        self.thumbnail_widgets['cache_size'].setToolTip("Number of thumbnails to keep in memory")
        thumb_layout.addRow("Cache Size:", self.thumbnail_widgets['cache_size'])

        # Thumbnail quality
        self.thumbnail_widgets['quality'] = QSlider(Qt.Orientation.Horizontal)
        # Allow lower quality down to 25% for cases where memory savings are desired
        self.thumbnail_widgets['quality'].setRange(25, 100)
        self.thumbnail_widgets['quality'].setToolTip("Thumbnail image quality (higher = better quality, more memory)")

        quality_layout = QHBoxLayout()
        quality_layout.addWidget(QLabel("Low"))
        quality_layout.addWidget(self.thumbnail_widgets['quality'])
        quality_layout.addWidget(QLabel("High"))

        self.thumbnail_quality_label = QLabel("85%")
        self.thumbnail_widgets['quality'].valueChanged.connect(
            lambda v: self.thumbnail_quality_label.setText(f"{v}%")
        )

        thumb_layout.addRow("Thumbnail Quality:", quality_layout)
        thumb_layout.addRow("", self.thumbnail_quality_label)

        # Preload count
        self.thumbnail_widgets['preload'] = QSpinBox()
        self.thumbnail_widgets['preload'].setRange(1, 20)
        self.thumbnail_widgets['preload'].setToolTip("Number of adjacent thumbnails to preload")
        thumb_layout.addRow("Preload Count:", self.thumbnail_widgets['preload'])

        layout.addWidget(thumb_group)
        layout.addStretch()

        scroll_area.setWidget(thumbnail_widget)
        self.tab_widget.addTab(scroll_area, "Thumbnails")

    def setup_request_tab(self) -> None:
        """Setup request optimization settings tab."""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)

        request_widget = QWidget()
        layout = QVBoxLayout(request_widget)

        # Request settings group
        request_group = QGroupBox("Request Optimization")
        request_layout = QFormLayout(request_group)

        # Request pooling enabled
        self.request_widgets['pooling'] = QCheckBox("Enable request pooling")
        self.request_widgets['pooling'].setToolTip("Pool and queue AI requests for better performance")
        request_layout.addRow(self.request_widgets['pooling'])

        # Max concurrent requests
        self.request_widgets['max_concurrent'] = QSpinBox()
        self.request_widgets['max_concurrent'].setRange(1, 10)
        self.request_widgets['max_concurrent'].setToolTip("Maximum simultaneous AI requests")
        request_layout.addRow("Max Concurrent:", self.request_widgets['max_concurrent'])

        # Request timeout
        self.request_widgets['timeout'] = QDoubleSpinBox()
        self.request_widgets['timeout'].setRange(5.0, 300.0)
        self.request_widgets['timeout'].setSuffix(" seconds")
        self.request_widgets['timeout'].setDecimals(1)
        self.request_widgets['timeout'].setToolTip("Timeout for individual AI requests")
        request_layout.addRow("Request Timeout:", self.request_widgets['timeout'])

        # Retry attempts
        self.request_widgets['retries'] = QSpinBox()
        self.request_widgets['retries'].setRange(0, 5)
        self.request_widgets['retries'].setToolTip("Number of retry attempts for failed requests")
        request_layout.addRow("Retry Attempts:", self.request_widgets['retries'])

        layout.addWidget(request_group)
        layout.addStretch()

        scroll_area.setWidget(request_widget)
        self.tab_widget.addTab(scroll_area, "Requests")

    def setup_control_buttons(self, layout: QVBoxLayout) -> None:
        """Setup control buttons at bottom of widget."""
        button_layout = QHBoxLayout()

        # Test optimization button
        test_btn = QPushButton("Test Optimization")
        test_btn.setToolTip("Test current optimization settings")
        test_btn.clicked.connect(self.optimization_test_requested.emit)
        button_layout.addWidget(test_btn)

        # Reset to defaults button
        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.setToolTip("Reset all optimization settings to defaults")
        reset_btn.clicked.connect(self.reset_to_defaults)
        button_layout.addWidget(reset_btn)

        button_layout.addStretch()

        # Save and apply buttons would be handled by parent settings window
        layout.addLayout(button_layout)

    def connect_signals(self) -> None:
        """Connect widget signals to handlers."""
        # Storage widgets
        for key, widget in self.storage_widgets.items():
            if isinstance(widget, QCheckBox):
                widget.toggled.connect(lambda checked, k=key: self.on_setting_changed(f'storage_{k}', checked))
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                widget.valueChanged.connect(lambda value, k=key: self.on_setting_changed(f'storage_{k}', value))

        # Thumbnail widgets
        for key, widget in self.thumbnail_widgets.items():
            if isinstance(widget, QCheckBox):
                widget.toggled.connect(lambda checked, k=key: self.on_setting_changed(f'thumbnail_{k}', checked))
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox, QSlider)):
                widget.valueChanged.connect(lambda value, k=key: self.on_setting_changed(f'thumbnail_{k}', value))

        # Request widgets
        for key, widget in self.request_widgets.items():
            if isinstance(widget, QCheckBox):
                widget.toggled.connect(lambda checked, k=key: self.on_setting_changed(f'request_{k}', checked))
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                widget.valueChanged.connect(lambda value, k=key: self.on_setting_changed(f'request_{k}', value))

    def on_setting_changed(self, setting_key: str, value: Any) -> None:
        """Handle setting change."""
        self.settings_changed.emit(setting_key, value)

    async def load_optimization_config(self) -> None:
        """Load current optimization configuration."""
        try:
            settings = await self.settings_manager.load_settings()
            self.optimization_config = settings.optimization
            self.update_ui_from_config()

        except Exception as e:
            self.logger.error(f"Error loading optimization config: {e}")

    def update_ui_from_config(self) -> None:
        """Update UI widgets from current configuration."""
        if not self.optimization_config:
            return

        try:
            # Update storage widgets
            self.storage_widgets['enabled'].setChecked(self.optimization_config.storage_management_enabled)
            self.storage_widgets['max_gb'].setValue(self.optimization_config.max_storage_gb)
            self.storage_widgets['max_files'].setValue(self.optimization_config.max_file_count)
            self.storage_widgets['cleanup_interval'].setValue(self.optimization_config.cleanup_interval_hours)
            self.storage_widgets['auto_cleanup'].setChecked(self.optimization_config.auto_cleanup_enabled)

            # Update thumbnail widgets
            self.thumbnail_widgets['enabled'].setChecked(self.optimization_config.thumbnail_cache_enabled)
            self.thumbnail_widgets['cache_size'].setValue(self.optimization_config.thumbnail_cache_size)
            self.thumbnail_widgets['quality'].setValue(self.optimization_config.thumbnail_quality)
            self.thumbnail_widgets['preload'].setValue(self.optimization_config.preload_count)

            # Update request widgets
            self.request_widgets['pooling'].setChecked(self.optimization_config.request_pooling_enabled)
            self.request_widgets['max_concurrent'].setValue(self.optimization_config.max_concurrent_requests)
            self.request_widgets['timeout'].setValue(self.optimization_config.request_timeout)
            self.request_widgets['retries'].setValue(self.optimization_config.retry_attempts)

        except Exception as e:
            self.logger.error(f"Error updating UI from config: {e}")

    def run_storage_cleanup(self) -> None:
        """Run storage cleanup immediately."""
        # This would trigger storage cleanup in the optimization manager
        self.logger.info("Storage cleanup requested")

    def reset_to_defaults(self) -> None:
        """Reset optimization settings to defaults."""
        try:
            from ..models.settings_manager import OptimizationConfig
            default_config = OptimizationConfig()
            self.optimization_config = default_config
            self.update_ui_from_config()
            self.logger.info("Optimization settings reset to defaults")

        except Exception as e:
            self.logger.error(f"Error resetting to defaults: {e}")

    async def update_statistics(self) -> None:
        """Update statistics displays."""
        try:
            # This would get statistics from optimization components
            # and update the statistics labels
            pass

        except Exception as e:
            self.logger.error(f"Error updating statistics: {e}")


def create_optimization_settings_widget(settings_manager: 'SettingsManager') -> OptimizationSettingsWidget:
    """
    Create optimization settings widget.

    Args:
        settings_manager: SettingsManager instance

    Returns:
        OptimizationSettingsWidget instance
    """
    return OptimizationSettingsWidget(settings_manager)
