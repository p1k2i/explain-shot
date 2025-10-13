"""
Test script to create sample screenshots for gallery testing.
"""

import asyncio
import sys
import logging
from pathlib import Path
from datetime import datetime
import os

# Add the src directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("PIL not available, install with: pip install Pillow")
    sys.exit(1)

from PyQt6.QtWidgets import QApplication

# Import our components
from src.controllers.event_bus import EventBus
from src.models.settings_manager import SettingsManager
from src.models.database_manager import DatabaseManager
from src.models.screenshot_manager import ScreenshotManager
from src.models.screenshot_models import ScreenshotMetadata
from src.views.gallery_window import GalleryWindow

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def create_sample_screenshots():
    """Create sample screenshots for testing."""
    try:
        # Create screenshots directory
        screenshots_dir = Path("screenshots")
        screenshots_dir.mkdir(exist_ok=True)

        # Sample screenshot data
        samples = [
            ("Sample UI Window", (800, 600), "#4A90E2"),
            ("Error Dialog", (400, 200), "#E74C3C"),
            ("Settings Panel", (600, 500), "#27AE60"),
            ("Login Form", (350, 280), "#9B59B6"),
            ("Dashboard", (1000, 700), "#F39C12")
        ]

        created_files = []

        for i, (title, size, color) in enumerate(samples, 1):
            # Create a simple test image
            img = Image.new('RGB', size, color)
            draw = ImageDraw.Draw(img)

            # Add some text
            try:
                font = ImageFont.load_default()
            except Exception:
                font = None

            text_color = "#FFFFFF" if color != "#F39C12" else "#000000"
            draw.text((20, 20), title, fill=text_color, font=font)
            draw.text((20, 50), f"Sample Screenshot {i}", fill=text_color, font=font)
            draw.text((20, 80), f"Size: {size[0]}x{size[1]}", fill=text_color, font=font)
            draw.text((20, 110), f"Created: {datetime.now().strftime('%Y-%m-%d %H:%M')}", fill=text_color, font=font)

            # Add some shapes for visual interest
            draw.rectangle([20, 140, 100, 180], outline="#FFFFFF", width=2)
            draw.ellipse([120, 140, 200, 220], outline="#FFFFFF", width=2)

            # Save the image
            filename = f"sample_{i:02d}_{title.lower().replace(' ', '_')}.png"
            file_path = screenshots_dir / filename
            img.save(file_path)

            created_files.append((filename, str(file_path), size))
            logger.info(f"Created sample screenshot: {filename}")

        return created_files

    except Exception as e:
        logger.error(f"Failed to create sample screenshots: {e}")
        return []

async def populate_database_with_samples():
    """Populate database with sample screenshot metadata."""
    try:
        logger.info("Creating sample screenshots and database entries...")

        # Create components
        event_bus = EventBus()
        settings_manager = SettingsManager()
        database_manager = DatabaseManager("test_gallery.db")
        screenshot_manager = ScreenshotManager(
            database_manager=database_manager,
            settings_manager=settings_manager,
            event_bus=event_bus
        )

        # Initialize components
        await settings_manager.initialize_database()
        await database_manager.initialize_database()
        await screenshot_manager.initialize()

        # Create sample screenshot files
        sample_files = await create_sample_screenshots()

        # Add them to the database
        for i, (filename, full_path, size) in enumerate(sample_files):
            metadata = ScreenshotMetadata(
                filename=filename,
                full_path=full_path,
                timestamp=datetime.now(),
                file_size=os.path.getsize(full_path) if os.path.exists(full_path) else 0,
                resolution=size,
                format="PNG"
            )

            # Add to database
            screenshot_id = await database_manager.create_screenshot(metadata)
            logger.info(f"Added screenshot to database: {filename} (ID: {screenshot_id})")

        logger.info(f"Successfully created {len(sample_files)} sample screenshots")
        return True

    except Exception as e:
        logger.error(f"Failed to populate database: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_gallery_with_data():
    """Test the gallery with sample data."""
    try:
        logger.info("Testing gallery with sample data...")

        # Create Qt application
        app = QApplication([])

        # Create components
        event_bus = EventBus()
        settings_manager = SettingsManager()
        database_manager = DatabaseManager("test_gallery.db")
        screenshot_manager = ScreenshotManager(
            database_manager=database_manager,
            settings_manager=settings_manager,
            event_bus=event_bus
        )

        # Initialize components
        await settings_manager.initialize_database()
        await database_manager.initialize_database()
        await screenshot_manager.initialize()

        # Create gallery window
        gallery = GalleryWindow(
            event_bus=event_bus,
            screenshot_manager=screenshot_manager,
            database_manager=database_manager,
            settings_manager=settings_manager
        )

        # Initialize and show gallery
        if await gallery.initialize():
            await gallery.show_gallery()
            logger.info("Gallery window with sample data shown successfully")
        else:
            logger.error("Failed to initialize gallery")
            return False

        # Keep running for manual testing
        logger.info("Gallery is running. Close the window to exit or wait 60 seconds...")

        def close_app():
            logger.info("Closing gallery test")
            gallery.close()
            app.quit()

        # Auto-close after 60 seconds
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(60000, close_app)

        # Run the Qt event loop
        app.exec()
        return True

    except Exception as e:
        logger.error(f"Gallery test with data failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Main test function."""
    try:
        logger.info("=== Gallery Test with Sample Data ===")

        # First populate with sample data
        logger.info("Step 1: Creating sample screenshots and database entries...")
        success = asyncio.run(populate_database_with_samples())

        if success:
            logger.info("Step 2: Testing gallery with sample data...")
            asyncio.run(test_gallery_with_data())
        else:
            logger.error("Failed to create sample data")
            sys.exit(1)

    except KeyboardInterrupt:
        logger.info("Test interrupted by user")
    except Exception as e:
        logger.error(f"Test failed with exception: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
