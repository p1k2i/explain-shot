"""Logging setup. Console for dev, rotating file for everything else."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from ..config.paths import logs_dir


def setup_logging(level: str = "INFO", console: bool = True) -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())

    # Wipe any pre-existing handlers (matters when the app is re-initialized in tests).
    for h in list(root.handlers):
        root.removeHandler(h)

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-5s %(name)s: %(message)s",
        "%H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        logs_dir() / "explainshot.log",
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    if console:
        stream = logging.StreamHandler()
        stream.setFormatter(fmt)
        root.addHandler(stream)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("PIL").setLevel(logging.WARNING)
