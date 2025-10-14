"""
Overlay Window Module

Implements the frameless overlay window with dual lists for app functions
and recent screenshots. Handles user interactions and auto-dismiss behavior.
"""

import logging
from typing import Dict, Any, List, Optional
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QEvent
from PyQt6.QtGui import QFont, QKeyEvent, QMouseEvent, QFocusEvent, QEnterEvent
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QListWidget, QListWidgetItem,
    QFrame, QLabel
)

from ..utils.style_loader import load_stylesheet
from ..controllers.event_bus import EventBus

logger = logging.getLogger(__name__)


class OverlayWindow(QWidget):
    """
    Frameless overlay window displaying app functions and recent screenshots.

    Features:
    - Dark themed frameless window with transparency
    - Two scrollable lists separated by visual divider
    - Auto-dismiss on focus loss or item selection
    - Keyboard navigation support
    - Responsive layout with proper sizing
    """

    # Signals for communication
    item_selected = pyqtSignal(str, dict)  # item_type, item_data
    overlay_dismissed = pyqtSignal(str)    # reason

    def __init__(
        self,
        event_bus: EventBus,
        config: Dict[str, Any],
        parent: Optional[QWidget] = None
    ):
        """
        Initialize overlay window.

        Args:
            event_bus: EventBus instance for communication
            config: Configuration dictionary
            parent: Parent widget (should be None for frameless)
        """
        super().__init__(parent)

        self.event_bus = event_bus
        self.config = config

        # State management
        self._auto_hide_timer: Optional[QTimer] = None
        self._is_mouse_over = False

        # Widget references
        self.app_functions_list: Optional[QListWidget] = None
        self.screenshots_list: Optional[QListWidget] = None
        self.separator: Optional[QFrame] = None

        # Initialize window
        self._setup_window()
        self._create_layout()
        self._apply_styling()
        self._setup_auto_hide()

        # Connect dismiss signal to close/hide
        self.overlay_dismissed.connect(self._on_overlay_dismissed)

        logger.info("OverlayWindow initialized")

    def _on_overlay_dismissed(self, reason: str) -> None:
        """Handle overlay dismissed signal by closing/hiding window."""
        logger.info(f"Overlay dismissed: {reason}")
        self.hide()
        self.close()

    def _setup_window(self) -> None:
        """Setup window properties and behavior."""
        try:
            # Window flags for frameless, topmost window
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint |
                Qt.WindowType.WindowStaysOnTopHint |
                Qt.WindowType.Tool |
                Qt.WindowType.X11BypassWindowManagerHint
            )

            # Window properties
            width = self.config.get("overlay.width", 280)
            height = self.config.get("overlay.height", 400)
            opacity = self.config.get("overlay.opacity", 0.92)

            self.setFixedSize(width, height)
            self.setWindowOpacity(opacity)

            # Enable mouse tracking for hover events
            self.setMouseTracking(True)

            # Accept focus for keyboard navigation
            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

            logger.debug(f"Window setup complete: {width}x{height}, opacity={opacity}")

        except Exception as e:
            logger.error(f"Error setting up window: {e}")
            raise

    def _create_layout(self) -> None:
        """Create the window layout with two lists and separator."""
        try:
            logger.info("Creating overlay layout...")

            # Main vertical layout
            main_layout = QVBoxLayout(self)
            main_layout.setContentsMargins(8, 8, 8, 8)
            main_layout.setSpacing(4)

            # App functions section
            functions_label = QLabel("App Functions")
            functions_label.setObjectName("sectionLabel")
            main_layout.addWidget(functions_label)

            self.app_functions_list = QListWidget()
            self.app_functions_list.setObjectName("appFunctionsList")
            self.app_functions_list.setFixedHeight(70)  # Fixed height for ~2 items
            self.app_functions_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self.app_functions_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.app_functions_list.itemClicked.connect(self._on_function_item_clicked)
            main_layout.addWidget(self.app_functions_list)
            logger.info("App functions list created")

            # Separator
            self.separator = QFrame()
            self.separator.setFrameShape(QFrame.Shape.HLine)
            self.separator.setFrameShadow(QFrame.Shadow.Sunken)
            self.separator.setObjectName("separator")
            self.separator.setFixedHeight(2)
            main_layout.addWidget(self.separator)

            # Recent screenshots section
            screenshots_label = QLabel("Recent Screenshots")
            screenshots_label.setObjectName("sectionLabel")
            main_layout.addWidget(screenshots_label)

            self.screenshots_list = QListWidget()
            self.screenshots_list.setObjectName("screenshotsList")
            self.screenshots_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self.screenshots_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.screenshots_list.itemClicked.connect(self._on_screenshot_item_clicked)
            main_layout.addWidget(self.screenshots_list)

            self.setLayout(main_layout)

            logger.info("Layout created successfully")

        except Exception as e:
            logger.error(f"Error creating layout: {e}")
            raise

    def _apply_styling(self) -> None:
        """Apply theme styling to the window."""
        try:
            theme = self.config.get("overlay.theme", "dark")
            stylesheet = load_stylesheet("overlay", theme, "base")
            if stylesheet:
                self.setStyleSheet(stylesheet)
            else:
                logger.error(f"Failed to load stylesheet for overlay/{theme}/base")

            # Set font
            font = QFont("Segoe UI", 9)
            self.setFont(font)

            logger.debug(f"Applied {theme} theme styling")

        except Exception as e:
            logger.error(f"Error applying styling: {e}")

    def _setup_auto_hide(self) -> None:
        """Setup auto-hide timer."""
        try:
            timeout = self.config.get("overlay.auto_hide_timeout", 10000)

            if timeout > 0:
                self._auto_hide_timer = QTimer()
                self._auto_hide_timer.setSingleShot(True)
                self._auto_hide_timer.timeout.connect(self._on_auto_hide_timeout)

                logger.debug(f"Auto-hide timer setup with {timeout}ms timeout")

        except Exception as e:
            logger.error(f"Error setting up auto-hide timer: {e}")

    def populate_lists(
        self,
        app_functions: List[Dict[str, Any]],
        screenshots: List[Dict[str, Any]]
    ) -> None:
        """
        Populate the lists with data.

        Args:
            app_functions: List of app function data
            screenshots: List of screenshot data
        """
        try:
            # Clear existing items
            if self.app_functions_list is not None:
                self.app_functions_list.clear()
            if self.screenshots_list is not None:
                self.screenshots_list.clear()

            # Populate app functions
            if self.app_functions_list is not None:
                for func_data in app_functions:
                    item = QListWidgetItem(func_data.get("title", "Unknown Function"))
                    item.setData(Qt.ItemDataRole.UserRole, func_data)
                    self.app_functions_list.addItem(item)

            # Populate screenshots
            if self.screenshots_list is not None:
                if screenshots:
                    for screenshot_data in screenshots:
                        # Format display text
                        filename = screenshot_data.get("filename", "Unknown")
                        resolution = screenshot_data.get("resolution", "")

                        # Create display text with metadata
                        display_text = f"📸 {filename}"
                        if resolution:
                            display_text += f" ({resolution})"

                        item = QListWidgetItem(display_text)
                        item.setData(Qt.ItemDataRole.UserRole, screenshot_data)
                        self.screenshots_list.addItem(item)
                else:
                    # Show empty state
                    empty_item = QListWidgetItem("No screenshots available")
                    empty_item.setFlags(Qt.ItemFlag.NoItemFlags)  # Make it non-selectable
                    self.screenshots_list.addItem(empty_item)

            logger.debug(f"Lists populated: {len(app_functions)} functions, {len(screenshots)} screenshots")

        except Exception as e:
            logger.error(f"Error populating lists: {e}")

    def apply_configuration(self, config: Dict[str, Any]) -> None:
        """
        Apply new configuration to the window.

        Args:
            config: Updated configuration dictionary
        """
        try:
            self.config = config

            # Update window properties
            width = config.get("overlay.width", 280)
            height = config.get("overlay.height", 400)
            opacity = config.get("overlay.opacity", 0.92)

            self.setFixedSize(width, height)
            self.setWindowOpacity(opacity)

            # Reapply styling
            self._apply_styling()

            logger.debug("Configuration applied to overlay window")

        except Exception as e:
            logger.error(f"Error applying configuration: {e}")

    def _on_function_item_clicked(self, item: QListWidgetItem) -> None:
        """
        Handle app function item click.

        Args:
            item: Clicked list item
        """
        try:
            item_data = item.data(Qt.ItemDataRole.UserRole)
            if item_data:
                logger.info(f"Function item selected: {item_data.get('title', 'Unknown')}")
                self.item_selected.emit("function", item_data)

        except Exception as e:
            logger.error(f"Error handling function item click: {e}")

    def _on_screenshot_item_clicked(self, item: QListWidgetItem) -> None:
        """
        Handle screenshot item click.

        Args:
            item: Clicked list item
        """
        try:
            item_data = item.data(Qt.ItemDataRole.UserRole)
            if item_data:
                logger.info(f"Screenshot item selected: {item_data.get('filename', 'Unknown')}")
                self.item_selected.emit("screenshot", item_data)

        except Exception as e:
            logger.error(f"Error handling screenshot item click: {e}")

    def _on_auto_hide_timeout(self) -> None:
        """Handle auto-hide timeout."""
        try:
            if not self._is_mouse_over:
                logger.debug("Auto-hide timeout triggered")
                self.overlay_dismissed.emit("timeout")
            else:
                # Restart timer if mouse is still over window
                if self._auto_hide_timer:
                    self._auto_hide_timer.start()

        except Exception as e:
            logger.error(f"Error in auto-hide timeout handler: {e}")

    def show(self) -> None:
        """Show the overlay window and start auto-hide timer."""
        try:
            super().show()

            # Start auto-hide timer
            if self._auto_hide_timer:
                timeout = self.config.get("overlay.auto_hide_timeout", 10000)
                self._auto_hide_timer.start(timeout)

            # Ensure window gets focus to avoid stuck state
            self.activateWindow()
            self.raise_()
            self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

            logger.debug("Overlay window shown")

        except Exception as e:
            logger.error(f"Error showing overlay window: {e}")

    def hide(self) -> None:
        """Hide the overlay window and stop auto-hide timer."""
        try:
            super().hide()

            # Stop auto-hide timer
            if self._auto_hide_timer:
                self._auto_hide_timer.stop()

            logger.debug("Overlay window hidden")

        except Exception as e:
            logger.error(f"Error hiding overlay window: {e}")

    def focusOutEvent(self, a0: Optional[QFocusEvent]) -> None:
        """Handle focus out events for auto-dismiss."""
        try:
            if a0 is None:
                return
            super().focusOutEvent(a0)

            # Simple focus loss detection
            logger.debug("Focus lost from overlay window")
            QTimer.singleShot(100, lambda: self._check_focus_loss())

        except Exception as e:
            logger.error(f"Error in focus out event handler: {e}")

    def enterEvent(self, event: Optional[QEnterEvent]) -> None:
        """Handle mouse enter events."""
        try:
            if event is None:
                return
            super().enterEvent(event)
            self._is_mouse_over = True

        except Exception as e:
            logger.error(f"Error in mouse enter event handler: {e}")

    def leaveEvent(self, a0: Optional[QEvent]) -> None:
        """Handle mouse leave events."""
        try:
            if a0 is None:
                return
            super().leaveEvent(a0)
            self._is_mouse_over = False

        except Exception as e:
            logger.error(f"Error in mouse leave event handler: {e}")

    def keyPressEvent(self, a0: Optional[QKeyEvent]) -> None:
        """Handle keyboard navigation."""
        try:
            if a0 is None:
                return
            key = a0.key()

            if key == Qt.Key.Key_Escape:
                logger.debug("Escape key pressed")
                self.overlay_dismissed.emit("escape_key")

            elif key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
                # Handle enter key on current selection
                current_widget = self.focusWidget()
                if isinstance(current_widget, QListWidget):
                    current_item = current_widget.currentItem()
                    if current_item:
                        if current_widget == self.app_functions_list:
                            self._on_function_item_clicked(current_item)
                        elif current_widget == self.screenshots_list:
                            self._on_screenshot_item_clicked(current_item)

            elif key == Qt.Key.Key_Tab:
                # Tab between lists
                if self.app_functions_list and self.app_functions_list.hasFocus():
                    if self.screenshots_list:
                        self.screenshots_list.setFocus()
                elif self.screenshots_list and self.screenshots_list.hasFocus():
                    if self.app_functions_list:
                        self.app_functions_list.setFocus()
                else:
                    # Default to first list
                    if self.app_functions_list:
                        self.app_functions_list.setFocus()

                a0.accept()
                return

            super().keyPressEvent(a0)

        except Exception as e:
            logger.error(f"Error handling key press event: {e}")

    def mousePressEvent(self, a0: Optional[QMouseEvent]) -> None:
        """Handle mouse press events."""
        try:
            if a0 is None:
                return
            super().mousePressEvent(a0)

            # Close on click outside lists (on background)
            widget_at_pos = self.childAt(a0.pos())
            if widget_at_pos is None or widget_at_pos == self:
                logger.debug("Clicked on background")
                self.overlay_dismissed.emit("background_click")

        except Exception as e:
            logger.error(f"Error handling mouse press event: {e}")

    def changeEvent(self, a0: Optional[QEvent]) -> None:
        """Handle window state changes."""
        try:
            if a0 is None:
                return
            super().changeEvent(a0)

            if a0.type() == QEvent.Type.ActivationChange:
                if not self.isActiveWindow():
                    logger.debug("Window lost activation")
                    # Small delay to allow for window switching
                    QTimer.singleShot(100, lambda: self._check_focus_loss())

        except Exception as e:
            logger.error(f"Error handling change event: {e}")

    def _check_focus_loss(self) -> None:
        """Check if focus was truly lost to external application."""
        try:
            if not self.isActiveWindow() and not self._is_mouse_over:
                logger.debug("Confirmed focus loss")
                self.overlay_dismissed.emit("focus_lost")

        except Exception as e:
            logger.error(f"Error checking focus loss: {e}")
