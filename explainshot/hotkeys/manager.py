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
import time
from typing import Callable

from pynput import keyboard

from ..config.settings import HotkeyConfig
from ..core.signals import AppSignals

log = logging.getLogger(__name__)


_ALIASES = {
    # Modifier keys
    "ctrl": "<ctrl>",
    "control": "<ctrl>",
    "shift": "<shift>",
    "alt": "<alt>",
    "cmd": "<cmd>",
    "win": "<cmd>",
    "super": "<cmd>",
    "meta": "<cmd>",
    # Named special keys — includes every form Qt's QKeySequenceEdit
    # produces so the settings picker round-trips cleanly with pynput.
    "print": "<print_screen>",
    "print_screen": "<print_screen>",
    "printscreen": "<print_screen>",
    "prtscr": "<print_screen>",
    "prtsc": "<print_screen>",
    "esc": "<esc>",
    "escape": "<esc>",
    "space": "<space>",
    "return": "<enter>",
    "enter": "<enter>",
    "tab": "<tab>",
    "backspace": "<backspace>",
    "delete": "<delete>",
    "del": "<delete>",
    "insert": "<insert>",
    "ins": "<insert>",
    "home": "<home>",
    "end": "<end>",
    "page_up": "<page_up>",
    "pageup": "<page_up>",
    "page_down": "<page_down>",
    "pagedown": "<page_down>",
    "up": "<up>",
    "down": "<down>",
    "left": "<left>",
    "right": "<right>",
    "f1": "<f1>", "f2": "<f2>", "f3": "<f3>", "f4": "<f4>",
    "f5": "<f5>", "f6": "<f6>", "f7": "<f7>", "f8": "<f8>",
    "f9": "<f9>", "f10": "<f10>", "f11": "<f11>", "f12": "<f12>",
}


def _normalize(combination: str) -> str:
    """Convert "ctrl+shift+s" style to pynput's "<ctrl>+<shift>+s" style.
    Handles both plain human names ("print_screen") and Qt's key-sequence
    form ("Print") that the settings picker produces."""
    tokens = [t.strip().lower() for t in combination.split("+") if t.strip()]
    return "+".join(_ALIASES.get(t, t) for t in tokens)


class HotkeyManager:
    def __init__(self, config: HotkeyConfig, signals: AppSignals) -> None:
        self.config = config
        self.signals = signals
        self._listener: keyboard.GlobalHotKeys | None = None
        # Monotonic time the full-screen hotkey last fired. Used to swallow the
        # region hotkey that pynput fires for the SAME Ctrl+Print press.
        self._fullscreen_at = 0.0

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
        bindings: dict[str, Callable[[], None]] = {}
        # Full-screen FIRST so its wrapper records the timestamp before the
        # region hotkey — which shares the Print Screen key — is evaluated for
        # the same press (pynput fires every matching hotkey independently).
        if self.config.capture_fullscreen.strip():
            bindings[_normalize(self.config.capture_fullscreen)] = self._emit_fullscreen
        bindings[_normalize(self.config.capture_region)] = self._emit_region
        bindings[_normalize(self.config.toggle_gallery)] = signals.hotkey_toggle_gallery.emit
        bindings[_normalize(self.config.open_settings)] = signals.hotkey_open_settings.emit
        return bindings

    def _emit_fullscreen(self) -> None:
        self._fullscreen_at = time.monotonic()
        self.signals.hotkey_capture_fullscreen.emit()

    def _emit_region(self) -> None:
        # On Ctrl+Print, pynput fires BOTH the bare-Print (region) and the
        # Ctrl+Print (full-screen) hotkeys. When the more-specific full-screen
        # one just fired for this same physical press, the user meant full
        # screen — swallow the region trigger. Same-press fires are microseconds
        # apart, so a tiny window reliably tells them from two separate presses.
        if time.monotonic() - self._fullscreen_at < 0.05:
            return
        self.signals.hotkey_capture_region.emit()
