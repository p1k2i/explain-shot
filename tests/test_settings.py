#!/usr/bin/env python3
"""
Simple test script to verify settings window functionality.
"""

import asyncio
import sys
import logging
from pathlib import Path

# Add the project root to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from PyQt6.QtWidgets import QApplication
from src.controllers.event_bus import EventBus
from src.models.settings_manager import SettingsManager
from src.views.settings_window import SettingsWindow

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def test_settings_window():
    """Test the settings window functionality."""
    print("Testing Settings Window...")

    # Create QApplication
    app = QApplication([])

    # Create required components
    event_bus = EventBus()

    settings_manager = SettingsManager()

    # Create settings window
    settings_window = SettingsWindow(
        event_bus=event_bus,
        settings_manager=settings_manager
    )

    # Initialize the window
    print("Initializing settings window...")
    if await settings_window.initialize():
        print("✓ Settings window initialized successfully")

        # Show the window
        settings_window.show()
        print("✓ Settings window shown")

        # Let the user interact with it
        print("Settings window is now visible. Test the following:")
        print("1. Check that all form fields are populated")
        print("2. Try changing some values")
        print("3. Test the 'Test Connection' button (should show mock success/failure)")
        print("4. Test validation by entering invalid values")
        print("5. Try saving settings (should show mock success message)")
        print("6. Close the window when done")

        # Run the Qt event loop
        app.exec()

    else:
        print("✗ Failed to initialize settings window")

    print("Test completed")

if __name__ == "__main__":
    asyncio.run(test_settings_window())
