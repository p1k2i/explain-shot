"""
Auto-Start Implementation Module

Handles Windows startup integration using both registry and startup folder methods.
Provides automatic method selection based on permissions and user preferences.
"""

import logging
import os
import sys
import winreg
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
from enum import Enum
import subprocess

logger = logging.getLogger(__name__)


class AutoStartStatus(Enum):
    """Auto-start status enumeration."""
    ENABLED = "enabled"
    DISABLED = "disabled"
    PARTIAL = "partial"  # Enabled but may not work
    ERROR = "error"
    UNKNOWN = "unknown"


class AutoStartMethod(Enum):
    """Auto-start implementation methods."""
    REGISTRY = "registry"
    STARTUP_FOLDER = "startup_folder"
    AUTO = "auto"


class AutoStartError(Exception):
    """Base exception for auto-start related errors."""
    pass


class PermissionError(AutoStartError):
    """Exception raised when insufficient permissions."""
    pass


class AutoStartManager:
    """
    Windows auto-start functionality manager.

    Handles automatic startup configuration using multiple methods:
    1. Registry (HKEY_CURRENT_USER\\...\\Run)
    2. Startup folder shortcut
    3. Automatic method selection
    """

    def __init__(self, app_name: str = "ExplainShot", executable_path: Optional[str] = None):
        """
        Initialize AutoStartManager.

        Args:
            app_name: Application name for registry and shortcut
            executable_path: Path to executable (auto-detected if None)
        """
        self.app_name = app_name
        self.executable_path = executable_path or self._get_executable_path()

        # Registry configuration
        self.registry_key = winreg.HKEY_CURRENT_USER
        self.registry_subkey = r"Software\Microsoft\Windows\CurrentVersion\Run"

        # Startup folder configuration
        self.startup_folder = self._get_startup_folder()
        self.shortcut_path = self.startup_folder / f"{self.app_name}.lnk"

        logger.info(
            "AutoStartManager initialized: app=%s, exe=%s",
            self.app_name, self.executable_path
        )

    def _get_executable_path(self) -> str:
        """Get the current executable path."""
        if getattr(sys, 'frozen', False):
            # Running as PyInstaller executable
            return sys.executable
        else:
            # Running as Python script - return the Python executable
            return sys.executable

    def _get_startup_folder(self) -> Path:
        """Get the Windows startup folder path."""
        startup_path = os.path.expandvars(
            r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
        )
        return Path(startup_path)

    async def check_registry_permissions(self) -> bool:
        """
        Check if we have permissions to write to the registry.

        Returns:
            True if registry access is available
        """
        try:
            # Try to open the registry key for writing
            with winreg.OpenKey(
                self.registry_key,
                self.registry_subkey,
                0,
                winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE
            ) as key:
                # Try to write a test value
                test_key = f"{self.app_name}_test"
                winreg.SetValueEx(key, test_key, 0, winreg.REG_SZ, "test")

                # Clean up test value
                try:
                    winreg.DeleteValue(key, test_key)
                except FileNotFoundError:
                    pass

                return True

        except (OSError, PermissionError) as e:
            logger.debug("Registry permission check failed: %s", e)
            return False

    async def check_startup_folder_permissions(self) -> bool:
        """
        Check if we have permissions to write to the startup folder.

        Returns:
            True if startup folder access is available
        """
        try:
            # Ensure startup folder exists
            self.startup_folder.mkdir(parents=True, exist_ok=True)

            # Try to create a test file
            test_file = self.startup_folder / f"{self.app_name}_test.tmp"
            test_file.write_text("test")

            # Clean up test file
            test_file.unlink()

            return True

        except (OSError, PermissionError) as e:
            logger.debug("Startup folder permission check failed: %s", e)
            return False

    async def enable_registry_startup(self, args: Optional[str] = None) -> bool:
        """
        Enable auto-start using registry method.

        Args:
            args: Additional command line arguments

        Returns:
            True if successfully enabled
        """
        try:
            # Construct command line
            command = f'"{self.executable_path}"'
            if args:
                command += f" {args}"

            # Open registry key
            with winreg.OpenKey(
                self.registry_key,
                self.registry_subkey,
                0,
                winreg.KEY_SET_VALUE
            ) as key:
                # Set the registry value
                winreg.SetValueEx(
                    key,
                    self.app_name,
                    0,
                    winreg.REG_SZ,
                    command
                )

            logger.info("Registry auto-start enabled: %s", command)
            return True

        except Exception as e:
            logger.error("Failed to enable registry auto-start: %s", e)
            return False

    async def disable_registry_startup(self) -> bool:
        """
        Disable auto-start from registry.

        Returns:
            True if successfully disabled
        """
        try:
            with winreg.OpenKey(
                self.registry_key,
                self.registry_subkey,
                0,
                winreg.KEY_SET_VALUE
            ) as key:
                try:
                    winreg.DeleteValue(key, self.app_name)
                    logger.info("Registry auto-start disabled")
                    return True
                except FileNotFoundError:
                    # Value doesn't exist, consider it disabled
                    return True

        except Exception as e:
            logger.error("Failed to disable registry auto-start: %s", e)
            return False

    async def enable_startup_folder(self, args: Optional[str] = None) -> bool:
        """
        Enable auto-start using startup folder shortcut.

        Args:
            args: Additional command line arguments

        Returns:
            True if successfully enabled
        """
        try:
            # Ensure startup folder exists
            self.startup_folder.mkdir(parents=True, exist_ok=True)

            # Create shortcut using Windows shell
            shortcut_target = self.executable_path
            if args:
                shortcut_args = args
            else:
                shortcut_args = ""

            # Use PowerShell to create shortcut
            powershell_script = f'''
$WshShell = New-Object -comObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("{self.shortcut_path}")
$Shortcut.TargetPath = "{shortcut_target}"
$Shortcut.Arguments = "{shortcut_args}"
$Shortcut.WorkingDirectory = "{Path(self.executable_path).parent}"
$Shortcut.Description = "{self.app_name} Auto-Start"
$Shortcut.Save()
'''

            # Execute PowerShell script
            result = subprocess.run(
                ["powershell", "-Command", powershell_script],
                capture_output=True,
                text=True,
                check=False
            )

            if result.returncode == 0 and self.shortcut_path.exists():
                logger.info("Startup folder shortcut created: %s", self.shortcut_path)
                return True
            else:
                logger.error(
                    "Failed to create shortcut. PowerShell output: %s, error: %s",
                    result.stdout, result.stderr
                )
                return False

        except Exception as e:
            logger.error("Failed to enable startup folder auto-start: %s", e)
            return False

    async def disable_startup_folder(self) -> bool:
        """
        Disable auto-start from startup folder.

        Returns:
            True if successfully disabled
        """
        try:
            if self.shortcut_path.exists():
                self.shortcut_path.unlink()
                logger.info("Startup folder shortcut removed")

            return True

        except Exception as e:
            logger.error("Failed to disable startup folder auto-start: %s", e)
            return False

    async def check_registry_status(self) -> AutoStartStatus:
        """
        Check if auto-start is enabled in registry.

        Returns:
            Current auto-start status
        """
        try:
            with winreg.OpenKey(
                self.registry_key,
                self.registry_subkey,
                0,
                winreg.KEY_QUERY_VALUE
            ) as key:
                try:
                    value, _ = winreg.QueryValueEx(key, self.app_name)
                    if value and self.executable_path in value:
                        return AutoStartStatus.ENABLED
                    else:
                        return AutoStartStatus.PARTIAL
                except FileNotFoundError:
                    return AutoStartStatus.DISABLED

        except Exception as e:
            logger.error("Error checking registry auto-start status: %s", e)
            return AutoStartStatus.ERROR

    async def check_startup_folder_status(self) -> AutoStartStatus:
        """
        Check if auto-start is enabled in startup folder.

        Returns:
            Current auto-start status
        """
        try:
            if not self.shortcut_path.exists():
                return AutoStartStatus.DISABLED

            # TODO: Could check if shortcut target matches current executable
            return AutoStartStatus.ENABLED

        except Exception as e:
            logger.error("Error checking startup folder auto-start status: %s", e)
            return AutoStartStatus.ERROR

    async def get_auto_start_status(self) -> Dict[str, Any]:
        """
        Get comprehensive auto-start status.

        Returns:
            Dictionary with status information
        """
        registry_status = await self.check_registry_status()
        folder_status = await self.check_startup_folder_status()

        # Determine overall status
        if (registry_status == AutoStartStatus.ENABLED or
            folder_status == AutoStartStatus.ENABLED):
            overall_status = AutoStartStatus.ENABLED
        elif (registry_status == AutoStartStatus.PARTIAL or
              folder_status == AutoStartStatus.PARTIAL):
            overall_status = AutoStartStatus.PARTIAL
        elif (registry_status == AutoStartStatus.ERROR or
              folder_status == AutoStartStatus.ERROR):
            overall_status = AutoStartStatus.ERROR
        else:
            overall_status = AutoStartStatus.DISABLED

        return {
            'overall_status': overall_status,
            'registry_status': registry_status,
            'startup_folder_status': folder_status,
            'registry_available': await self.check_registry_permissions(),
            'startup_folder_available': await self.check_startup_folder_permissions(),
            'executable_path': self.executable_path,
            'shortcut_path': str(self.shortcut_path)
        }

    async def enable_auto_start(
        self,
        method: AutoStartMethod = AutoStartMethod.AUTO,
        args: Optional[str] = None
    ) -> Tuple[bool, AutoStartMethod]:
        """
        Enable auto-start using specified or best available method.

        Args:
            method: Preferred auto-start method
            args: Additional command line arguments

        Returns:
            Tuple of (success, actual_method_used)
        """
        if method == AutoStartMethod.AUTO:
            # Choose best available method
            if await self.check_registry_permissions():
                method = AutoStartMethod.REGISTRY
            elif await self.check_startup_folder_permissions():
                method = AutoStartMethod.STARTUP_FOLDER
            else:
                logger.error("No auto-start methods available due to permissions")
                return False, method

        # Try the specified method
        if method == AutoStartMethod.REGISTRY:
            if await self.check_registry_permissions():
                success = await self.enable_registry_startup(args)
                if success:
                    return True, AutoStartMethod.REGISTRY

            # Fallback to startup folder if registry fails
            if await self.check_startup_folder_permissions():
                logger.info("Registry method failed, falling back to startup folder")
                success = await self.enable_startup_folder(args)
                return success, AutoStartMethod.STARTUP_FOLDER

        elif method == AutoStartMethod.STARTUP_FOLDER:
            if await self.check_startup_folder_permissions():
                success = await self.enable_startup_folder(args)
                if success:
                    return True, AutoStartMethod.STARTUP_FOLDER

            # Fallback to registry if startup folder fails
            if await self.check_registry_permissions():
                logger.info("Startup folder method failed, falling back to registry")
                success = await self.enable_registry_startup(args)
                return success, AutoStartMethod.REGISTRY

        return False, method

    async def disable_auto_start(self, method: Optional[AutoStartMethod] = None) -> bool:
        """
        Disable auto-start from specified or all methods.

        Args:
            method: Specific method to disable (all if None)

        Returns:
            True if successfully disabled
        """
        success = True

        if method is None or method == AutoStartMethod.REGISTRY:
            registry_success = await self.disable_registry_startup()
            success = success and registry_success

        if method is None or method == AutoStartMethod.STARTUP_FOLDER:
            folder_success = await self.disable_startup_folder()
            success = success and folder_success

        return success

    async def update_auto_start_command(
        self,
        args: Optional[str] = None,
        method: Optional[AutoStartMethod] = None
    ) -> bool:
        """
        Update auto-start command arguments.

        Args:
            args: New command line arguments
            method: Specific method to update (all active if None)

        Returns:
            True if successfully updated
        """
        status = await self.get_auto_start_status()
        success = True

        # Update registry if enabled
        if (method is None or method == AutoStartMethod.REGISTRY) and \
           status['registry_status'] == AutoStartStatus.ENABLED:
            registry_success = await self.enable_registry_startup(args)
            success = success and registry_success

        # Update startup folder if enabled
        if (method is None or method == AutoStartMethod.STARTUP_FOLDER) and \
           status['startup_folder_status'] == AutoStartStatus.ENABLED:
            folder_success = await self.enable_startup_folder(args)
            success = success and folder_success

        return success

    async def verify_auto_start(self) -> Dict[str, Any]:
        """
        Verify that auto-start is working correctly.

        Returns:
            Dictionary with verification results
        """
        status = await self.get_auto_start_status()

        verification = {
            'overall_working': False,
            'registry_working': False,
            'startup_folder_working': False,
            'issues': []
        }

        # Check registry
        if status['registry_status'] == AutoStartStatus.ENABLED:
            # Verify executable exists and is accessible
            if Path(self.executable_path).exists():
                verification['registry_working'] = True
            else:
                verification['issues'].append("Registry points to non-existent executable")

        # Check startup folder
        if status['startup_folder_status'] == AutoStartStatus.ENABLED:
            if self.shortcut_path.exists():
                verification['startup_folder_working'] = True
            else:
                verification['issues'].append("Startup folder shortcut missing")

        # Overall status
        verification['overall_working'] = (
            verification['registry_working'] or
            verification['startup_folder_working']
        )

        return verification


# Global auto-start manager instance
_auto_start_manager: Optional[AutoStartManager] = None


def get_auto_start_manager(app_name: str = "ExplainShot") -> AutoStartManager:
    """
    Get the global AutoStartManager instance.

    Args:
        app_name: Application name for auto-start entries

    Returns:
        AutoStartManager instance
    """
    global _auto_start_manager
    if _auto_start_manager is None:
        _auto_start_manager = AutoStartManager(app_name)
    return _auto_start_manager


def set_auto_start_manager(manager: AutoStartManager) -> None:
    """
    Set the global AutoStartManager instance.

    Args:
        manager: AutoStartManager instance to use globally
    """
    global _auto_start_manager
    _auto_start_manager = manager
