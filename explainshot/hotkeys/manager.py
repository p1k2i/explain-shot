"""Global hotkey manager.

Replaces the ~1200-line hotkey_handler with a thin wrapper over pynput.
The pynput listener runs in its own daemon thread; we translate its
callbacks into Qt signals. Every consumer connects with QueuedConnection
so callbacks land back on the main thread — QueuedConnection is Qt's
default when signal and receiver live in different threads, so we get
that automatically without extra work.
"""

from __future__ import annotations

import logging
from typing import Callable

from pynput import keyboard

from ..config.settings import HotkeyConfig
from ..core.signals import AppSignals

log = logging.getLogger(__name__)


def _normalize(combination: str) -> str:
    """Convert "ctrl+shift+s" style to pynput's "<ctrl>+<shift>+s" style."""
    tokens = [t.strip().lower() for t in combination.split("+") if t.strip()]
    aliases = {
        "ctrl": "<ctrl>",
        "control": "<ctrl>",
        "shift": "<shift>",
        "alt": "<alt>",
        "cmd": "<cmd>",
        "win": "<cmd>",
        "super": "<cmd>",
    }
    return "+".join(aliases.get(t, t) for t in tokens)


class HotkeyManager:
    def __init__(self, config: HotkeyConfig, signals: AppSignals) -> None:
        self.config = config
        self.signals = signals
        self._listener: keyboard.GlobalHotKeys | None = None

    def start(self) -> None:
        self.stop()
        try:
            bindings = self._build_bindings()
            self._listener = keyboard.GlobalHotKeys(bindings)
            self._listener.daemon = True
            self._listener.start()
            log.info("hotkeys registered: %s", list(bindings))
        except Exception as exc:
            log.error("failed to register hotkeys: %s", exc)

    def stop(self) -> None:
        if self._listener:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None

    def reload(self, config: HotkeyConfig) -> None:
        self.config = config
        self.start()

    # -- internal --------------------------------------------------------------

    def _build_bindings(self) -> dict[str, Callable[[], None]]:
        signals = self.signals
        return {
            _normalize(self.config.capture_region): signals.hotkey_capture_region.emit,
            _normalize(self.config.toggle_gallery): signals.hotkey_toggle_gallery.emit,
            _normalize(self.config.open_settings): signals.hotkey_open_settings.emit,
        }
