"""
Test Tray Icon Module

Simple test script to verify pystray functionality with a basic tray icon,
context menu, and debug logging.
"""

import logging
import sys
from PIL import Image, ImageDraw
import pystray
from pystray import MenuItem as Item

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def create_simple_icon(size=(64, 64)):
    """
    Create a simple test icon (red square).

    Args:
        size: Icon size tuple (width, height)

    Returns:
        PIL Image object
    """
    logger.debug("Creating simple test icon with size %s", size)
    image = Image.new('RGB', size, color='white')
    draw = ImageDraw.Draw(image)
    draw.rectangle([10, 10, size[0]-10, size[1]-10], fill='red')
    return image


def on_exit(icon, item):
    """Handle exit menu item click."""
    logger.debug("Exit menu item clicked")
    icon.stop()
    logger.info("Tray icon stopped, exiting application")
    sys.exit(0)


def main():
    """Main entry point for the test tray application."""
    logger.info("Initializing test tray application")

    # Create simple icon
    icon_image = create_simple_icon()

    # Create menu
    menu = pystray.Menu(
        Item('Exit', on_exit)
    )
    logger.debug("Context menu created with exit option")

    # Create tray icon
    icon = pystray.Icon(
        "test_tray",
        icon_image,
        "Test Tray Icon",
        menu=menu
    )
    logger.info("Tray icon created and ready")

    # Run the icon (blocks until stopped)
    logger.info("Starting tray icon event loop")
    icon.run()
    logger.info("Tray icon event loop ended")


if __name__ == "__main__":
    main()
