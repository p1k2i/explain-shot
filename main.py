"""Top-level entry so `python main.py` and PyInstaller work unchanged."""

import sys

from explainshot.main import run

if __name__ == "__main__":
    sys.exit(run())
