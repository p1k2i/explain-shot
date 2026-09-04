"""Windows autostart via HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run.

The old code had two methods (registry + startup-folder shortcut) with
automatic selection, permission checks, status enums, three exception
classes. The registry entry works for every user without elevation; that
is the only method we keep.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .. import APP_NAME

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


class AutoStart:
    def __init__(self, app_name: str = APP_NAME) -> None:
        self.app_name = app_name

    def is_enabled(self) -> bool:
        if sys.platform != "win32":
            return False
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
                value, _ = winreg.QueryValueEx(key, self.app_name)
                return bool(value)
        except FileNotFoundError:
            return False
        except OSError:
            return False

    def enable(self) -> bool:
        if sys.platform != "win32":
            return False
        import winreg
        command = self._current_command()
        try:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
                winreg.SetValueEx(key, self.app_name, 0, winreg.REG_SZ, command)
            return True
        except OSError:
            return False

    def disable(self) -> bool:
        if sys.platform != "win32":
            return False
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_ALL_ACCESS) as key:
                winreg.DeleteValue(key, self.app_name)
            return True
        except FileNotFoundError:
            return True
        except OSError:
            return False

    def set(self, enabled: bool) -> bool:
        return self.enable() if enabled else self.disable()

    @staticmethod
    def _current_command() -> str:
        if getattr(sys, "frozen", False):
            return f'"{sys.executable}" --minimized'
        script = Path(sys.argv[0]).resolve()
        return f'"{sys.executable}" "{script}" --minimized'
