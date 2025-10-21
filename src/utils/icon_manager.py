"""
Icon Resource Manager

Handles icon loading, conversion, and management for different DPI settings
and application states. Provides fallback mechanisms for missing icons.
"""

import logging
from pathlib import Path
from typing import Dict, Optional, Any
import sys
import io
from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)


class IconState:
    """Icon state enumeration."""
    IDLE = "idle"
    CAPTURING = "capturing"
    PROCESSING = "processing"
    ERROR = "error"
    DISABLED = "disabled"


class IconManager:
    """
    Icon resource manager for system tray and UI components.

    Handles icon loading, scaling, and fallback generation for different
    application states and DPI settings.
    """

    def __init__(self, resource_dir: Optional[Path] = None):
        """
        Initialize IconManager.

        Args:
            resource_dir: Directory containing icon resources
        """
        self.resource_dir = resource_dir or self._get_resource_dir()
        self.icon_cache: Dict[str, Any] = {}
        self.fallback_enabled = True

        # Standard icon sizes
        self.icon_sizes = {
            'small': (16, 16),
            'medium': (24, 24),
            'large': (32, 32),
            'tray': (16, 16)  # System tray standard size
        }

        logger.debug("IconManager initialized with resource directory: %s", self.resource_dir)

    def _get_resource_dir(self) -> Path:
        """Get the resource directory path."""
        if getattr(sys, 'frozen', False):
            # Running as PyInstaller executable
            base_dir = Path(getattr(sys, '_MEIPASS', Path(__file__).parent.parent.parent))
        else:
            # Running as script
            base_dir = Path(__file__).parent.parent.parent

        return base_dir / "resources" / "icons"

    def get_icon_path(self, state: str, size: str = "medium") -> Optional[Path]:
        """
        Get the path to an icon file.

        Args:
            state: Icon state (idle, capturing, processing, error, disabled)
            size: Icon size category

        Returns:
            Path to icon file or None if not found
        """
        # Try different file formats
        formats = ['png', 'ico', 'svg']
        size_suffix = f"_{self.icon_sizes[size][0]}" if size != "medium" else ""

        for fmt in formats:
            icon_path = self.resource_dir / f"icon_{state}{size_suffix}.{fmt}"
            if icon_path.exists():
                return icon_path

        # Try without size suffix
        for fmt in formats:
            icon_path = self.resource_dir / f"icon_{state}.{fmt}"
            if icon_path.exists():
                return icon_path

        return None

    def load_icon(self, state: str, size: str = "medium") -> Optional[bytes]:
        """
        Load icon as bytes for pystray.

        Args:
            state: Icon state
            size: Icon size category

        Returns:
            Icon data as bytes or None if failed
        """
        cache_key = f"{state}_{size}"

        # Check cache first
        if cache_key in self.icon_cache:
            return self.icon_cache[cache_key]

        try:
            icon_path = self.get_icon_path(state, size)

            if icon_path is None:
                if self.fallback_enabled:
                    logger.warning("Icon not found for state '%s', generating fallback", state)
                    icon_data = self._generate_fallback_icon(state, size)
                else:
                    return None
            else:
                # Load and convert icon
                icon_data = self._load_and_convert_icon(icon_path, size)

            # Cache the result
            if icon_data:
                self.icon_cache[cache_key] = icon_data

            return icon_data

        except Exception as e:
            logger.error("Failed to load icon for state '%s': %s", state, e)

            if self.fallback_enabled:
                return self._generate_fallback_icon(state, size)

            return None

    def _load_and_convert_icon(self, icon_path: Path, size: str) -> Optional[bytes]:
        """
        Load and convert icon to appropriate format.

        Args:
            icon_path: Path to icon file
            size: Target size category

        Returns:
            Icon data as bytes
        """
        target_size = self.icon_sizes[size]

        try:
            if icon_path.suffix.lower() == '.svg':
                # Convert SVG to PNG (requires additional dependencies in full implementation)
                # For now, return None to trigger fallback
                logger.warning("SVG icons not yet supported, using fallback")
                return None
            else:
                # Load with PIL
                with Image.open(icon_path) as img:
                    # Convert to RGBA if needed
                    if img.mode != 'RGBA':
                        img = img.convert('RGBA')

                    # Resize if needed
                    if img.size != target_size:
                        img = img.resize(target_size, Image.Resampling.LANCZOS)

                    # Convert to bytes
                    bio = io.BytesIO()
                    img.save(bio, format='PNG')
                    return bio.getvalue()

        except Exception as e:
            logger.error("Failed to convert icon '%s': %s", icon_path, e)
            return None

    def _generate_fallback_icon(self, state: str, size: str) -> bytes:
        """
        Generate a fallback icon when the actual icon is not available.

        Args:
            state: Icon state
            size: Icon size category

        Returns:
            Generated icon as bytes
        """
        target_size = self.icon_sizes[size]

        # Create new image
        img = Image.new('RGBA', target_size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Define colors for different states
        colors = {
            IconState.IDLE: '#666666',
            IconState.CAPTURING: '#4CAF50',
            IconState.PROCESSING: '#2196F3',
            IconState.ERROR: '#F44336',
            IconState.DISABLED: '#9E9E9E'
        }

        color = colors.get(state, '#666666')

        # Draw simple geometric shape based on state
        margin = max(2, target_size[0] // 8)

        if state == IconState.CAPTURING:
            # Camera-like shape
            # Outer rectangle
            draw.rectangle(
                [margin, margin + 2, target_size[0] - margin, target_size[1] - margin],
                outline=color,
                width=2
            )
            # Lens
            center_x, center_y = target_size[0] // 2, target_size[1] // 2
            lens_radius = min(target_size) // 4
            draw.ellipse(
                [center_x - lens_radius, center_y - lens_radius,
                 center_x + lens_radius, center_y + lens_radius],
                outline=color,
                width=1
            )

        elif state == IconState.PROCESSING:
            # Rotating dots
            center_x, center_y = target_size[0] // 2, target_size[1] // 2
            radius = min(target_size) // 3
            for i in range(3):
                x = center_x + int(radius * 0.7 * (1 if i == 0 else 0.5))
                y = center_y + int(radius * 0.7 * (0 if i == 0 else (1 if i == 1 else -1)))
                dot_radius = 2 if i == 0 else 1
                draw.ellipse(
                    [x - dot_radius, y - dot_radius, x + dot_radius, y + dot_radius],
                    fill=color
                )

        elif state == IconState.ERROR:
            # X mark
            draw.line(
                [margin + 2, margin + 2, target_size[0] - margin - 2, target_size[1] - margin - 2],
                fill=color,
                width=2
            )
            draw.line(
                [target_size[0] - margin - 2, margin + 2, margin + 2, target_size[1] - margin - 2],
                fill=color,
                width=2
            )

        elif state == IconState.DISABLED:
            # Crossed out rectangle
            draw.rectangle(
                [margin, margin, target_size[0] - margin, target_size[1] - margin],
                outline=color,
                width=1
            )
            draw.line(
                [margin, margin, target_size[0] - margin, target_size[1] - margin],
                fill=color,
                width=2
            )

        else:  # IDLE or default
            # Simple rectangle with dot
            draw.rectangle(
                [margin, margin, target_size[0] - margin, target_size[1] - margin],
                outline=color,
                width=2
            )
            center_x, center_y = target_size[0] // 2, target_size[1] // 2
            draw.ellipse(
                [center_x - 2, center_y - 2, center_x + 2, center_y + 2],
                fill=color
            )

        # Convert to bytes
        bio = io.BytesIO()
        img.save(bio, format='PNG')
        return bio.getvalue()

    def get_pil_image(self, state: str, size: str = "medium") -> Optional[Image.Image]:
        """
        Get icon as PIL Image object.

        Args:
            state: Icon state
            size: Icon size category

        Returns:
            PIL Image object or None
        """
        icon_data = self.load_icon(state, size)
        if icon_data:
            return Image.open(io.BytesIO(icon_data))
        return None

    def clear_cache(self) -> None:
        """Clear the icon cache."""
        self.icon_cache.clear()
        logger.debug("Icon cache cleared")

    def preload_icons(self, states: Optional[list] = None, sizes: Optional[list] = None) -> None:
        """
        Preload icons into cache.

        Args:
            states: List of states to preload (all if None)
            sizes: List of sizes to preload (all if None)
        """
        if states is None:
            states = [IconState.IDLE, IconState.CAPTURING, IconState.PROCESSING,
                     IconState.ERROR, IconState.DISABLED]

        if sizes is None:
            sizes = list(self.icon_sizes.keys())

        for state in states:
            for size in sizes:
                self.load_icon(state, size)

        logger.debug("Preloaded %d icons", len(states) * len(sizes))

    def get_icon_info(self) -> Dict[str, Any]:
        """
        Get information about available icons.

        Returns:
            Dictionary with icon information
        """
        info = {
            'resource_directory': str(self.resource_dir),
            'cache_size': len(self.icon_cache),
            'supported_sizes': self.icon_sizes,
            'available_icons': {},
            'fallback_enabled': self.fallback_enabled
        }

        # Check which icons are available
        states = [IconState.IDLE, IconState.CAPTURING, IconState.PROCESSING,
                 IconState.ERROR, IconState.DISABLED]

        for state in states:
            info['available_icons'][state] = {}
            for size in self.icon_sizes:
                icon_path = self.get_icon_path(state, size)
                info['available_icons'][state][size] = {
                    'available': icon_path is not None,
                    'path': str(icon_path) if icon_path else None
                }

        return info

    def get_app_icon_path(self) -> Optional[Path]:
        """
        Get the path to the application icon file.

        Returns:
            Path to app.ico or None if not found
        """
        icon_path = self.resource_dir / "app.ico"
        if icon_path.exists():
            return icon_path

        return None

    def get_app_icon(self) -> Optional[Any]:
        """
        Get the application icon as a QIcon.

        Returns:
            QIcon instance or None if icon not found
        """
        try:
            from PyQt6.QtGui import QIcon
            icon_path = self.get_app_icon_path()
            if icon_path:
                return QIcon(str(icon_path))
        except ImportError:
            logger.warning("PyQt6 not available for QIcon creation")
        except Exception as e:
            logger.error(f"Failed to create app icon: {e}")

        return None


# Global icon manager instance
_icon_manager: Optional[IconManager] = None


def get_icon_manager() -> IconManager:
    """
    Get the global IconManager instance.

    Returns:
        IconManager instance
    """
    global _icon_manager
    if _icon_manager is None:
        _icon_manager = IconManager()
    return _icon_manager


def set_icon_manager(manager: IconManager) -> None:
    """
    Set the global IconManager instance.

    Args:
        manager: IconManager instance to use globally
    """
    global _icon_manager
    _icon_manager = manager
