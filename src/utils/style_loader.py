"""
Style Loader Utility

Provides functionality to load CSS stylesheets for different components and themes.
"""

import logging
from typing import Optional
from PyQt6.QtCore import QFile

logger = logging.getLogger(__name__)


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
    css_file_path = f"resources/{component}/styles/{theme}/{element}.css"

    file = QFile(css_file_path)
    if file.open(QFile.OpenModeFlag.ReadOnly | QFile.OpenModeFlag.Text):
        try:
            content = file.readAll().data().decode('utf-8')
            return content
        finally:
            file.close()
    else:
        logger.error(f"Could not load stylesheet: {css_file_path}")
        return None
