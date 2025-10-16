#!/usr/bin/env python3
"""
Test script for the updated settings window with optimization settings.
"""

import sys
import asyncio
from pathlib import Path

# Add the src directory to the Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QEventLoop

from src.models.settings_manager import SettingsManager
from src.views.settings_window import SettingsWindow
from src.controllers.event_bus import EventBus


async def test_settings_window():
    """Test the settings window with optimization settings."""

    # Create Qt application
    app = QApplication(sys.argv)

    # Create event loop for asyncio integration
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    try:
        # Initialize components
        event_bus = EventBus()
        settings_manager = SettingsManager(event_bus)

        # Load settings
        await settings_manager.load_settings()

        # Create settings window
        settings_window = SettingsWindow(event_bus, settings_manager)

        # Show the window
        settings_window.show()

        print("Settings window opened successfully!")
        print("Check that the Performance tab is present with optimization settings.")
        print("Close the window to exit the test.")

        # Run the Qt event loop
        with loop:
            loop.exec()

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

    finally:
        app.quit()


if __name__ == "__main__":
    asyncio.run(test_settings_window())
