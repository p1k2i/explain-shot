"""
Views package for Explain Screenshot Application

This package contains the View layer components following the MVC pattern:
- TrayManager: System tray icon and menu management
- UIManager: PyQt6 window management and coordination
- OverlayManager: Overlay window lifecycle management
- OverlayWindow: Frameless overlay window implementation
- Window components: Settings, Gallery windows (planned)
"""

from .tray_manager import TrayManager
from .ui_manager import UIManager
from .overlay_manager import OverlayManager
from .overlay_window import OverlayWindow

__all__ = [
    'TrayManager',
    'UIManager',
    'OverlayManager',
    'OverlayWindow'
]
