"""ExplainShot entry point.

The old main.py polled Qt events in a tight asyncio loop
(`await asyncio.sleep(0)` around `qt_app.processEvents()`), which pegged a
CPU core when idle and could still miss GUI events during heavy work. We
use qasync instead — it runs the Qt event loop as the asyncio loop, so
signals, coroutines, and hotkey callbacks all live on the same thread with
no bridging needed.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

import qasync
from PyQt6.QtWidgets import QApplication

from . import APP_NAME, APP_VERSION
from .app import Application
from .core.logging import setup_logging
from .util.singleton import SingleInstance

log = logging.getLogger(__name__)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog=APP_NAME.lower(),
        description=f"{APP_NAME} — capture the screen, ask an AI to explain it.",
    )
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {APP_VERSION}")
    parser.add_argument("--minimized", action="store_true", help="Start in the tray without opening a window.")
    parser.add_argument("--debug", action="store_true", help="Verbose logging.")
    return parser.parse_args(argv)


def run(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    setup_logging(level="DEBUG" if args.debug else "INFO", console=not args.minimized)
    log.info("starting %s %s", APP_NAME, APP_VERSION)

    lock = SingleInstance()
    if not lock.acquire():
        log.warning("another instance is already running")
        return 1

    try:
        qt_app = QApplication(sys.argv)
        loop = qasync.QEventLoop(qt_app)
        asyncio.set_event_loop(loop)

        application = Application(qt_app)
        application.start()

        if not args.minimized:
            application.show_gallery()

        with loop:
            loop.run_forever()
        return 0
    finally:
        lock.release()


if __name__ == "__main__":
    sys.exit(run())
