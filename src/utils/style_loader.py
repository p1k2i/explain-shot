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
