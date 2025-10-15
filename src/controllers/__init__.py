"""
Controllers package for ExplainShot Application

This package contains the Controller layer components following the MVC pattern:
- MainController: Application orchestration and business logic
- EventBus: Asynchronous event distribution system
- HotkeyHandler: Global hotkey monitoring and processing
"""

from .event_bus import EventBus, get_event_bus, set_event_bus
from .main_controller import MainController
from .hotkey_handler import HotkeyHandler, HotkeyCombo, ConflictInfo

__all__ = [
    'EventBus',
    'get_event_bus',
    'set_event_bus',
    'MainController',
    'HotkeyHandler',
    'HotkeyCombo',
    'ConflictInfo'
]
