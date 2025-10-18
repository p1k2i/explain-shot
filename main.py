"""
Main Application Entry Point

Implements the async main function with signal handling, module initialization,
and PyInstaller compatibility for the ExplainShot application.
"""

import asyncio
import logging
import signal
import sys
from pathlib import Path
from typing import Optional
import argparse

# PyQt6 imports
from PyQt6.QtWidgets import QApplication

# Import core modules
from src.controllers.event_bus import get_event_bus, EventBus
from src.controllers.main_controller import MainController
from src.utils.logging_config import setup_logging, get_logger
from src.models.settings_manager import SettingsManager
from src.models.database_manager import DatabaseManager
from src.models.screenshot_manager import ScreenshotManager
from src.models.ollama_client import OllamaClient
from src.views.tray_manager import TrayManager
from src.views.ui_manager import UIManager
from src.utils.auto_start import get_auto_start_manager, AutoStartManager
from src import EventTypes, AppState, APP_NAME, APP_VERSION

logger = get_logger(__name__)


class Application:
    """
    Main application class that orchestrates all components.

    Handles initialization, lifecycle management, and graceful shutdown
    of all application modules following the MVC pattern.
    """

    def __init__(self):
        """Initialize the application."""
        self.app_name = APP_NAME
        self.version = APP_VERSION
        self.state = AppState.STARTING

        # Core components
        self.event_bus: Optional[EventBus] = None
        self.settings_manager: Optional[SettingsManager] = None
        self.database_manager: Optional[DatabaseManager] = None
        self.screenshot_manager: Optional[ScreenshotManager] = None
        self.ollama_client: Optional[OllamaClient] = None
        self.tray_manager: Optional[TrayManager] = None
        self.ui_manager: Optional[UIManager] = None
        self.auto_start_manager: Optional[AutoStartManager] = None
        self.main_controller: Optional[MainController] = None

        # PyQt6 application instance
        self.qt_app: Optional[QApplication] = None

        # Control flags
        self._shutdown_event = asyncio.Event()
        self.initialization_complete = False

        # Signal handling
        self.original_handlers = {}

        # Lock file for single instance checking
        self._lock_file = None

    async def initialize(self) -> bool:
        """
        Initialize all application components.

        Returns:
            True if initialization was successful
        """
        try:
            logger.info("Initializing %s v%s", self.app_name, self.version)

            # Initialize EventBus
            self.event_bus = get_event_bus()
            await self._subscribe_to_events()

            # Initialize DatabaseManager
            self.database_manager = DatabaseManager()
            await self.database_manager.initialize_database()

            # Initialize SettingsManager
            self.settings_manager = SettingsManager(database_manager=self.database_manager)
            await self.settings_manager.initialize_database()
            settings = await self.settings_manager.load_settings()

            # Initialize ScreenshotManager
            self.screenshot_manager = ScreenshotManager(
                database_manager=self.database_manager,
                settings_manager=self.settings_manager,
                event_bus=self.event_bus
            )
            await self.screenshot_manager.initialize()

            # Initialize OllamaClient
            self.ollama_client = OllamaClient(
                event_bus=self.event_bus,
                database_manager=self.database_manager,
                settings_manager=self.settings_manager
            )
            await self.ollama_client.initialize()

            # Initialize AutoStartManager
            self.auto_start_manager = get_auto_start_manager(self.app_name)

            # Check and configure auto-start if enabled
            if settings.auto_start.enabled:
                await self._configure_auto_start()

            # Initialize TrayManager
            self.tray_manager = TrayManager(
                app_name=self.app_name,
                tooltip=f"{self.app_name} v{self.version}",
                shutdown_event=self._shutdown_event
            )

            if not self.tray_manager.initialize():
                logger.warning("Tray manager initialization failed - continuing without tray")

            # Initialize PyQt6 Application
            existing_app = QApplication.instance()
            if existing_app is None:
                self.qt_app = QApplication(sys.argv)
                logger.info("Created new QApplication instance")
            else:
                # Safely cast since we know it's a QApplication if it exists
                self.qt_app = existing_app  # type: ignore
                logger.info("Using existing QApplication instance")

            # Initialize UIManager
            self.ui_manager = UIManager(
                event_bus=self.event_bus,
                settings_manager=self.settings_manager,
                screenshot_manager=self.screenshot_manager,
                database_manager=self.database_manager,
                ollama_client=self.ollama_client
            )

            # Initialize MainController with all components
            self.main_controller = MainController(
                event_bus=self.event_bus,
                settings_manager=self.settings_manager,
                database_manager=self.database_manager,
                screenshot_manager=self.screenshot_manager,
                tray_manager=self.tray_manager,
                ui_manager=self.ui_manager,
                auto_start_manager=self.auto_start_manager
            )

            # Initialize the main controller (this will setup hotkeys)
            if not await self.main_controller.initialize():
                logger.error("Main controller initialization failed")
                return False

            # Setup signal handlers
            self._setup_signal_handlers()

            # Mark initialization complete
            self.initialization_complete = True
            self.state = AppState.READY

            # Emit ready event
            await self.event_bus.emit(
                EventTypes.APP_READY,
                {'state': self.state},
                source="application"
            )

            logger.info("Application initialization complete")
            return True

        except Exception as e:
            logger.error("Application initialization failed: %s", e)
            self.state = AppState.ERROR
            return False

    async def _subscribe_to_events(self) -> None:
        """Subscribe to application-level events."""
        if self.event_bus is None:
            raise RuntimeError("EventBus not initialized")

        await self.event_bus.subscribe(
            EventTypes.APP_SHUTDOWN_REQUESTED,
            self._handle_shutdown_request
        )

        await self.event_bus.subscribe(
            EventTypes.SETTINGS_UPDATED,
            self._handle_settings_updated
        )

    async def _configure_auto_start(self) -> None:
        """Configure auto-start if enabled in settings."""
        if self.auto_start_manager is None:
            logger.warning("Auto-start manager not initialized")
            return

        try:
            # Check current auto-start status
            status = await self.auto_start_manager.get_auto_start_status()

            if status['overall_status'].value != 'enabled':
                logger.info("Configuring auto-start...")

                # Enable auto-start with minimal startup options
                success, method = await self.auto_start_manager.enable_auto_start(
                    args="--minimized"
                )

                if success:
                    logger.info("Auto-start configured successfully using %s", method.value)
                else:
                    logger.warning("Failed to configure auto-start")

        except Exception as e:
            logger.error("Error configuring auto-start: %s", e)

    def _setup_signal_handlers(self) -> None:
        """Set up signal handlers for graceful shutdown."""
        if sys.platform == "win32":
            # Windows signal handling
            signal.signal(signal.SIGINT, self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)
        else:
            # Unix-like systems
            signal.signal(signal.SIGINT, self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)
            signal.signal(signal.SIGHUP, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        logger.info("Received signal %d, initiating shutdown", signum)

        # Set shutdown event
        self._shutdown_event.set()

    async def _handle_shutdown_request(self, event_data) -> None:
        """Handle shutdown request events."""
        logger.info("Shutdown requested by %s", event_data.source)

        # Set shutdown event
        self._shutdown_event.set()

    async def _handle_settings_updated(self, event_data) -> None:
        """Handle settings update events."""
        if event_data.data and 'key' in event_data.data:
            key = event_data.data['key']
            value = event_data.data['value']

            # Note: Settings are already updated by SettingsManager, no need to update again
            logger.debug("Settings updated notification: %s = %s", key, value)

    async def run(self) -> int:
        """
        Run the main application loop.

        Returns:
            Exit code (0 for success, non-zero for error)
        """
        try:
            # Initialize application
            if not await self.initialize():
                return 1

            logger.info("Application started successfully")

            # Setup Qt event processing in asyncio
            qt_event_task = asyncio.create_task(self._process_qt_events())

            # Main event loop - wait for shutdown event
            await self._shutdown_event.wait()

            logger.info("Application shutting down")

            # Cancel Qt event processing
            qt_event_task.cancel()
            try:
                await qt_event_task
            except asyncio.CancelledError:
                pass

            # Perform shutdown
            await self._shutdown()

            return 0

        except KeyboardInterrupt:
            logger.info("Application interrupted by user")
            return 0

        except Exception as e:
            logger.error("Unexpected error in main loop: %s", e)
            return 1

        finally:
            # Ensure cleanup happens
            if not self._shutdown_event.is_set():
                await self._shutdown()

    async def _process_qt_events(self) -> None:
        """Process Qt events in asyncio loop."""
        try:
            while not self._shutdown_event.is_set():
                if self.qt_app:
                    self.qt_app.processEvents()
                await asyncio.sleep(0)

        except asyncio.CancelledError:
            logger.info("Qt event processing cancelled")
        except Exception as e:
            logger.error(f"Error processing Qt events: {e}")

    async def _shutdown(self) -> None:
        """Perform graceful shutdown of all components."""
        if self.state == AppState.SHUTTING_DOWN:
            return

        self.state = AppState.SHUTTING_DOWN
        logger.info("Starting application shutdown")

        try:
            # Emit shutdown starting event
            if self.event_bus and not self.event_bus.is_shutdown():
                await self.event_bus.emit(
                    EventTypes.APP_SHUTDOWN_STARTING,
                    source="application"
                )

            # Shutdown MainController (this will shutdown hotkeys)
            if self.main_controller:
                await self.main_controller.shutdown()

            # Shutdown ScreenshotManager
            if self.screenshot_manager:
                await self.screenshot_manager.shutdown()

            # Shutdown OllamaClient
            if self.ollama_client:
                await self.ollama_client.shutdown()

            # Shutdown TrayManager
            if self.tray_manager:
                self.tray_manager.shutdown()

            # Save settings
            if self.settings_manager:
                try:
                    await self.settings_manager.save_settings()
                except Exception as e:
                    logger.error("Error saving settings during shutdown: %s", e)

            # Shutdown EventBus (this should be last)
            if self.event_bus:
                await self.event_bus.shutdown()

            logger.info("Application shutdown complete")

            # Release lock file
            if self._lock_file:
                try:
                    if sys.platform == 'win32':
                        import msvcrt
                        msvcrt.locking(self._lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                    self._lock_file.close()
                except Exception as e:
                    logger.debug("Error releasing lock file: %s", e)

            # Force exit to ensure the application terminates
            # (needed because the tray's detached thread may keep the process alive)
            sys.exit(0)

        except Exception as e:
            logger.error("Error during shutdown: %s", e)

    def is_single_instance(self) -> bool:
        """
        Check if this is the only instance of the application using file locking.

        Returns:
            True if this is the only instance
        """
        import os
        from pathlib import Path

        try:
            # Create a lock file in the user's AppData directory
            appdata = os.getenv('APPDATA')
            if not appdata:
                logger.warning("APPDATA environment variable not set")
                return True

            app_data = Path(appdata) / 'ExplainShot'
            app_data.mkdir(parents=True, exist_ok=True)

            lock_file = app_data / 'explain-shot.lock'

            # Try to open the lock file exclusively
            # This will fail if another instance has it locked
            try:
                self._lock_file = open(lock_file, 'w')
                # Try to get an exclusive lock on Windows
                if sys.platform == 'win32':
                    import msvcrt
                    try:
                        msvcrt.locking(self._lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                    except (OSError, IOError):
                        # Lock failed - another instance is running
                        self._lock_file.close()
                        return False

                # Write current PID to lock file
                self._lock_file.write(str(os.getpid()))
                self._lock_file.flush()
                return True

            except (OSError, IOError) as e:
                logger.debug("Could not acquire lock: %s", e)
                return False

        except Exception as e:
            logger.warning("Error checking single instance: %s", e)
            # If lock check fails, allow multiple instances
            return True


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description=f"{APP_NAME} v{APP_VERSION} - AI-powered screenshot explanation tool"
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"{APP_NAME} {APP_VERSION}"
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )

    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
        help="Set logging level"
    )

    parser.add_argument(
        "--log-dir",
        type=Path,
        help="Directory for log files"
    )

    parser.add_argument(
        "--minimized",
        action="store_true",
        help="Start minimized (used for auto-start)"
    )

    parser.add_argument(
        "--no-tray",
        action="store_true",
        help="Disable system tray (fallback mode)"
    )

    return parser.parse_args()


async def main() -> int:
    """
    Main application entry point.

    Returns:
        Exit code
    """
    # Parse command line arguments
    args = parse_arguments()

    # Setup logging
    log_level = "DEBUG" if args.debug else args.log_level
    setup_logging(
        log_dir=args.log_dir,
        log_level=log_level,
        enable_console=not args.minimized,
        enable_json=True
    )

    logger = get_logger(__name__)
    logger.info("Starting %s v%s", APP_NAME, APP_VERSION)

    # Check for single instance
    app = Application()
    if not app.is_single_instance():
        logger.warning("Another instance is already running")
        return 1

    # Run application
    try:
        return await app.run()
    except Exception as e:
        logger.error("Fatal error: %s", e)
        return 1
    finally:
        # Cleanup logging
        logging.shutdown()


def run_app():
    """Synchronous entry point for PyInstaller."""
    try:
        # Run the async main function
        return asyncio.run(main())

    except KeyboardInterrupt:
        print("Application interrupted")
        return 0

    except Exception as e:
        print(f"Fatal error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(run_app())
