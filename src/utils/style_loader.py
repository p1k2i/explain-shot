"""
Style Loader Utility

Provides functionality to load CSS stylesheets for different components and themes.
"""

import logging
import sys
from pathlib import Path
from typing import Optional, List, Union
from PyQt6.QtCore import QFile

logger = logging.getLogger(__name__)


def _get_resource_path(relative_path: str) -> str:
    """
    Get the absolute path to a resource file.

    Works both in development and when packaged with PyInstaller.

    Args:
        relative_path: Path relative to the project root (e.g., "resources/...")

    Returns:
        Absolute path to the resource
    """
    if getattr(sys, 'frozen', False):
        # Running as PyInstaller executable
        # Resources are in the _internal directory
        base_path = Path(getattr(sys, '_MEIPASS')) / relative_path
    else:
        # Running in development mode
        base_path = Path(__file__).parent.parent.parent / relative_path

    return str(base_path)


def load_stylesheet(component: str, theme: str, element: str) -> Optional[str]:
    """
    Load a CSS stylesheet for a given component, theme, and element.

    Args:
        component: The component name (e.g., "overlay", "gallery")
        theme: The theme name (e.g., "dark", "light")
        element: The element name (e.g., "base", "custom")

    Returns:
        The CSS content as a string, or None if loading failed
    """
    relative_css_path = f"resources/{component}/styles/{theme}/{element}.css"
    css_file_path = _get_resource_path(relative_css_path)

    file = QFile(css_file_path)
    if file.open(QFile.OpenModeFlag.ReadOnly | QFile.OpenModeFlag.Text):
        try:
            content = file.readAll().data().decode('utf-8')
            logger.debug(f"Successfully loaded stylesheet: {css_file_path}")
            return content
        except Exception as e:
            logger.error(f"Error reading stylesheet {css_file_path}: {e}")
            return None
        finally:
            file.close()
    else:
        logger.error(f"Could not open stylesheet: {css_file_path}")
        logger.debug(f"Resource path resolution: {Path(css_file_path).exists()}")
        return None


def load_stylesheets(component: str, theme: str, elements: List[str]) -> Optional[str]:
    """
    Load multiple CSS stylesheets and combine them.

    Args:
        component: The component name (e.g., "overlay", "gallery")
        theme: The theme name (e.g., "dark", "light")
        elements: List of element names (e.g., ["base", "validation", "states"])

    Returns:
        The combined CSS content as a string, or None if all files failed to load
    """
    combined_css = []

    for element in elements:
        css_content = load_stylesheet(component, theme, element)
        if css_content:
            combined_css.append(f"/* {element}.css */")
            combined_css.append(css_content)
            combined_css.append("")  # Add spacing between files

    if combined_css:
        return "\n".join(combined_css)
    else:
        logger.warning(f"No stylesheets could be loaded for {component}/{theme} with elements: {elements}")
        return None


def get_dynamic_css(css_class: str, styles: dict) -> str:
    """
    Generate dynamic CSS from a dictionary of styles.

    Args:
        css_class: CSS class or selector
        styles: Dictionary of CSS properties and values

    Returns:
        Generated CSS string
    """
    if not styles:
        return ""

    css_lines = [f"{css_class} {{"]
    for property_name, value in styles.items():
        css_lines.append(f"    {property_name}: {value};")
    css_lines.append("}")

    return "\n".join(css_lines)


def combine_css(*css_contents: Union[str, None]) -> str:
    """
    Combine multiple CSS content strings, ignoring None values.

    Args:
        *css_contents: Variable number of CSS content strings

    Returns:
        Combined CSS string
    """
    valid_contents = [content for content in css_contents if content is not None]
    return "\n\n".join(valid_contents)


def apply_dynamic_css_to_widget(widget, css_content: str) -> None:
    """
    Apply CSS to a widget and force a style refresh.

    Args:
        widget: The Qt widget to apply CSS to
        css_content: The CSS content to apply
    """
    if css_content:
        current_stylesheet = widget.styleSheet()
        combined_stylesheet = combine_css(current_stylesheet, css_content)
        widget.setStyleSheet(combined_stylesheet)

        # Force style refresh
        style = widget.style()
        if style:
            style.polish(widget)


def refresh_widget_style(widget) -> None:
    """
    Force a widget to refresh its styling by calling polish().

    Args:
        widget: The Qt widget to refresh
    """
    style = widget.style()
    if style:
        style.polish(widget)


class DynamicStyleManager:
    """
    Manages dynamic CSS loading and application for gallery components.
    """

    def __init__(self, component: str, theme: str):
        self.component = component
        self.theme = theme
        self._base_css = None
        self._state_css_cache = {}

    def load_base_styles(self) -> str:
        """Load and cache base styles for the component."""
        if self._base_css is None:
            elements = ["base", "screenshot-items", "preset-items", "chat-widget"]
            self._base_css = load_stylesheets(self.component, self.theme, elements)
        return self._base_css or ""

    def get_state_css(self, state: str) -> str:
        """
        Get CSS for a specific state (e.g., 'selection-states', 'hover-states').

        Args:
            state: The state name

        Returns:
            CSS content for the state
        """
        if state not in self._state_css_cache:
            css_content = load_stylesheet(self.component, self.theme, state)
            self._state_css_cache[state] = css_content or ""
        return self._state_css_cache[state]

    def apply_base_styles(self, widget) -> None:
        """Apply base styles to a widget."""
        base_css = self.load_base_styles()
        if base_css:
            widget.setStyleSheet(base_css)

    def apply_state_styles(self, widget, states: List[str]) -> None:
        """
        Apply multiple state styles to a widget along with base styles.

        Args:
            widget: The Qt widget
            states: List of state names to apply
        """
        base_css = self.load_base_styles()
        state_css_list = [self.get_state_css(state) for state in states]

        combined_css = combine_css(base_css, *state_css_list)
        widget.setStyleSheet(combined_css)
        refresh_widget_style(widget)

    def apply_screenshot_item_state(self, widget, state: str) -> None:
        """
        Apply a specific state CSS to a screenshot item widget.

        Args:
            widget: The screenshot item widget
            state: The state to apply ('normal', 'hover', 'selected', 'selected-hover')
        """
        if state == 'normal':
            css_content = self.get_state_css('screenshot-items')
        else:
            css_content = self.get_state_css(f'screenshot-items-{state}')

        if css_content:
            widget.setStyleSheet(css_content)
            refresh_widget_style(widget)

    def refresh_theme(self, new_theme: str) -> None:
        """
        Change theme and clear cache.

        Args:
            new_theme: New theme name
        """
        if new_theme != self.theme:
            self.theme = new_theme
            self._base_css = None
            self._state_css_cache.clear()


class ScreenshotItemStyleManager:
    """
    Specialized style manager for screenshot items with state management.
    """

    def __init__(self, style_manager: DynamicStyleManager):
        self.style_manager = style_manager

    def apply_state(self, widget, is_selected: bool, is_hovered: bool) -> None:
        """
        Apply the appropriate state CSS based on selection and hover states.

        Args:
            widget: The screenshot item widget
            is_selected: Whether the item is selected
            is_hovered: Whether the item is hovered
        """
        if is_selected and is_hovered:
            state = 'selected-hover'
        elif is_selected:
            state = 'selected'
        elif is_hovered:
            state = 'hover'
        else:
            state = 'normal'

        self.style_manager.apply_screenshot_item_state(widget, state)
