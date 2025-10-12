"""
Mock integration test for screenshot functionality.

This module demonstrates and tests the screenshot capture workflow
with mock components and provides a simple test harness.
"""

import asyncio
import logging
import os
import tempfile
from pathlib import Path
import shutil

# Import our modules
from src.models.screenshot_manager import ScreenshotManager
from src.models.database_manager import DatabaseManager
from src.models.settings_manager import SettingsManager
from src.controllers.event_bus import EventBus

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


class MockController:
    """Mock controller to demonstrate screenshot capture workflow."""

    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.temp_dir = None
        self.db_manager = None
        self.settings_manager = None
        self.event_bus = None
        self.screenshot_manager = None

        # Event tracking
        self.captured_events = []

    async def initialize(self) -> None:
        """Initialize all components."""
        self.logger.info("Initializing MockController...")

        # Create temporary directory for test
        self.temp_dir = tempfile.mkdtemp(prefix="screenshot_test_")
        self.logger.info(f"Created temp directory: {self.temp_dir}")

        # Initialize EventBus
        self.event_bus = EventBus()
        await self.event_bus.subscribe("screenshot.*", self._handle_screenshot_event)
        await self.event_bus.subscribe("error.*", self._handle_error_event)

        # Initialize DatabaseManager
        db_path = os.path.join(self.temp_dir, "test_app.db")
        self.db_manager = DatabaseManager(db_path=db_path)
        await self.db_manager.initialize_database()

        # Initialize SettingsManager
        self.settings_manager = SettingsManager(
            db_path=Path(db_path),
            auto_create=True
        )
        await self.settings_manager.initialize_database()

        # Set screenshot directory
        screenshot_dir = os.path.join(self.temp_dir, "screenshots")
        await self.settings_manager.update_setting("screenshot_directory", screenshot_dir)
        await self.settings_manager.update_setting("filename_format", "test_screenshot_%Y%m%d_%H%M%S_%f")

        # Initialize ScreenshotManager
        self.screenshot_manager = ScreenshotManager(
            database_manager=self.db_manager,
            settings_manager=self.settings_manager,
            event_bus=self.event_bus,
            logger=self.logger
        )

        await self.screenshot_manager.initialize()

        self.logger.info("MockController initialization complete")

    async def _handle_screenshot_event(self, event_data) -> None:
        """Handle screenshot-related events."""
        self.captured_events.append(event_data)
        event_type = event_data.event_type if hasattr(event_data, 'event_type') else 'unknown'
        data = event_data.data if hasattr(event_data, 'data') else event_data
        self.logger.info(f"Screenshot event: {event_type}")
        if isinstance(data, dict) and 'metadata' in data:
            metadata = data['metadata']
            if isinstance(metadata, dict) and 'filename' in metadata:
                self.logger.info(f"  Screenshot file: {metadata['filename']}")

    async def _handle_error_event(self, event_data) -> None:
        """Handle error events."""
        self.captured_events.append(event_data)
        event_type = event_data.event_type if hasattr(event_data, 'event_type') else 'unknown'
        data = event_data.data if hasattr(event_data, 'data') else event_data
        self.logger.error(f"Error event: {event_type} - {data}")

    async def test_screenshot_capture(self) -> bool:
        """Test screenshot capture functionality."""
        self.logger.info("Testing screenshot capture...")

        try:
            # Attempt to capture a screenshot
            result = await self.screenshot_manager.capture_screenshot()

            if result.success:
                self.logger.info("Screenshot captured successfully!")
                self.logger.info(f"  File: {result.metadata.filename}")
                self.logger.info(f"  Path: {result.metadata.full_path}")
                self.logger.info(f"  Size: {result.metadata.file_size} bytes")
                self.logger.info(f"  Resolution: {result.metadata.resolution}")
                self.logger.info(f"  Capture time: {result.capture_duration:.3f}s")
                self.logger.info(f"  Save time: {result.save_duration:.3f}s")

                # Verify file exists
                if os.path.exists(result.metadata.full_path):
                    self.logger.info("✓ Screenshot file exists on disk")
                else:
                    self.logger.error("✗ Screenshot file not found on disk")
                    return False

                return True
            else:
                self.logger.error(f"Screenshot capture failed: {result.error_message}")
                return False

        except Exception as e:
            self.logger.error(f"Screenshot capture exception: {e}")
            return False

    async def test_recent_screenshots(self) -> bool:
        """Test retrieving recent screenshots."""
        self.logger.info("Testing recent screenshots retrieval...")

        try:
            recent = await self.screenshot_manager.get_recent_screenshots(limit=5)
            self.logger.info(f"Found {len(recent)} recent screenshots")

            for i, screenshot in enumerate(recent):
                self.logger.info(f"  {i+1}. {screenshot.filename} ({screenshot.file_size} bytes)")

            return True

        except Exception as e:
            self.logger.error(f"Recent screenshots test failed: {e}")
            return False

    async def test_storage_statistics(self) -> bool:
        """Test storage statistics."""
        self.logger.info("Testing storage statistics...")

        try:
            stats = await self.screenshot_manager.get_storage_statistics()
            self.logger.info("Storage statistics:")
            self.logger.info(f"  Total screenshots: {stats.total_screenshots}")
            self.logger.info(f"  Total size: {stats.total_size_mb:.2f} MB")
            self.logger.info(f"  Directory size: {stats.directory_size_mb:.2f} MB")
            if stats.oldest_screenshot:
                self.logger.info(f"  Oldest: {stats.oldest_screenshot}")
            if stats.newest_screenshot:
                self.logger.info(f"  Newest: {stats.newest_screenshot}")

            return True

        except Exception as e:
            self.logger.error(f"Storage statistics test failed: {e}")
            return False

    async def test_directory_validation(self) -> bool:
        """Test directory validation."""
        self.logger.info("Testing directory validation...")

        try:
            # Test current directory
            current_dir = self.screenshot_manager.current_directory
            validation = self.screenshot_manager.validate_directory(current_dir)

            self.logger.info(f"Directory validation for {current_dir}:")
            self.logger.info(f"  Valid: {validation.is_valid}")
            self.logger.info(f"  Can write: {validation.can_write}")
            self.logger.info(f"  Available space: {validation.available_space / (1024*1024):.1f} MB")

            if validation.error_messages:
                for msg in validation.error_messages:
                    self.logger.info(f"  Message: {msg}")

            # Test invalid directory
            invalid_dir = "/definitely/does/not/exist/path"
            invalid_validation = self.screenshot_manager.validate_directory(invalid_dir)
            self.logger.info(f"Invalid directory test - Valid: {invalid_validation.is_valid}")

            return True

        except Exception as e:
            self.logger.error(f"Directory validation test failed: {e}")
            return False

    async def test_database_operations(self) -> bool:
        """Test database operations."""
        self.logger.info("Testing database operations...")

        try:
            # Get database stats
            stats = await self.db_manager.get_database_stats()
            self.logger.info("Database statistics:")
            for key, value in stats.items():
                self.logger.info(f"  {key}: {value}")

            # Test screenshot count
            count = await self.db_manager.get_screenshot_count()
            self.logger.info(f"Screenshot count: {count}")

            return True

        except Exception as e:
            self.logger.error(f"Database operations test failed: {e}")
            return False

    async def test_event_system(self) -> bool:
        """Test event system functionality."""
        self.logger.info("Testing event system...")

        try:
            # Check captured events
            self.logger.info(f"Captured {len(self.captured_events)} events")

            event_types = {}
            for event in self.captured_events:
                event_type = event.event_type if hasattr(event, 'event_type') else 'unknown'
                event_types[event_type] = event_types.get(event_type, 0) + 1

            for event_type, count in event_types.items():
                self.logger.info(f"  {event_type}: {count} times")

            # Get event bus metrics
            metrics = await self.event_bus.get_metrics()
            self.logger.info("EventBus metrics:")
            for key, value in metrics.items():
                self.logger.info(f"  {key}: {value}")

            return True

        except Exception as e:
            self.logger.error(f"Event system test failed: {e}")
            return False

    async def run_all_tests(self) -> bool:
        """Run all tests."""
        self.logger.info("=" * 60)
        self.logger.info("STARTING SCREENSHOT FUNCTIONALITY TESTS")
        self.logger.info("=" * 60)

        tests = [
            ("Directory Validation", self.test_directory_validation),
            ("Database Operations", self.test_database_operations),
            ("Screenshot Capture", self.test_screenshot_capture),
            ("Recent Screenshots", self.test_recent_screenshots),
            ("Storage Statistics", self.test_storage_statistics),
            ("Event System", self.test_event_system),
        ]

        results = []

        for test_name, test_func in tests:
            self.logger.info(f"\n--- {test_name} ---")
            try:
                result = await test_func()
                results.append((test_name, result))
                status = "PASS" if result else "FAIL"
                self.logger.info(f"{test_name}: {status}")
            except Exception as e:
                self.logger.error(f"{test_name}: ERROR - {e}")
                results.append((test_name, False))

        # Summary
        passed = sum(1 for _, result in results if result)
        total = len(results)

        self.logger.info("\n" + "=" * 60)
        self.logger.info("TEST SUMMARY")
        self.logger.info("=" * 60)

        for test_name, result in results:
            status = "PASS" if result else "FAIL"
            self.logger.info(f"{test_name}: {status}")

        self.logger.info(f"\nOverall: {passed}/{total} tests passed")

        return passed == total

    async def cleanup(self) -> None:
        """Cleanup test resources."""
        self.logger.info("Cleaning up test resources...")

        try:
            # Shutdown components
            if self.screenshot_manager:
                await self.screenshot_manager.shutdown()

            if self.db_manager:
                await self.db_manager.close()

            if self.event_bus:
                await self.event_bus.shutdown()

            # Remove temporary directory
            if self.temp_dir and os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
                self.logger.info(f"Removed temp directory: {self.temp_dir}")

        except Exception as e:
            self.logger.error(f"Cleanup error: {e}")


async def main():
    """Main test function."""
    controller = MockController()

    try:
        await controller.initialize()
        success = await controller.run_all_tests()

        if success:
            print("\n🎉 All tests passed! Screenshot functionality is working correctly.")
        else:
            print("\n❌ Some tests failed. Check the logs for details.")

        return success

    except Exception as e:
        logging.error(f"Test runner failed: {e}")
        return False

    finally:
        await controller.cleanup()


if __name__ == "__main__":
    # Run the test
    success = asyncio.run(main())
    exit(0 if success else 1)
