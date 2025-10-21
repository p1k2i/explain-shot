"""
Hotkey Handler Module

Implements global hotkey registration, monitoring, and management using pynput.
Provides asynchronous hotkey detection with conflict resolution and dynamic
reconfiguration capabilities.
"""

import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional, Set, Any
from datetime import datetime
import time
from queue import Queue, Empty
import weakref

# Local imports
from src.controllers.event_bus import EventBus
from src.models.settings_manager import SettingsManager
from src import EventTypes

from pynput import keyboard

# Type aliases for consistent typing
KeyboardListener = keyboard.Listener

logger = logging.getLogger(__name__)


@dataclass
class HotkeyEvent:
    """Thread-safe hotkey event data structure."""
    hotkey_id: str
    combination: 'HotkeyCombo'
    action: str
    timestamp: float = field(default_factory=time.time)
    source: str = "hotkey"


class ThreadSafeEventQueue:
    """
    Thread-safe event queue for hotkey events.

    Bridges between pynput thread and asyncio event loop with proper synchronization.
    """

    def __init__(self, maxsize: int = 100):
        """Initialize the thread-safe event queue."""
        self._queue = Queue(maxsize=maxsize)
        self._shutdown = threading.Event()
        self._loop_ref: Optional[weakref.ReferenceType] = None

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Set the asyncio event loop for event processing."""
        self._loop_ref = weakref.ref(loop)

    def put_event(self, event: HotkeyEvent) -> bool:
        """
        Put an event in the queue from any thread.

        Args:
            event: HotkeyEvent to queue

        Returns:
            True if event was queued successfully
        """
        if self._shutdown.is_set():
            return False

        try:
            self._queue.put_nowait(event)
            return True
        except Exception as e:
            logger.error("Error queuing event: %s", e)
            return False

    def get_event(self, timeout: float = 0.1) -> Optional[HotkeyEvent]:
        """
        Get the next event from the queue (non-blocking for asyncio).

        Args:
            timeout: Maximum time to wait for an event

        Returns:
            Next HotkeyEvent or None if queue is empty
        """
        try:
            return self._queue.get(timeout=timeout)
        except Empty:
            return None

    def shutdown(self) -> None:
        """Shutdown the event queue."""
        self._shutdown.set()

        # Clear any remaining events
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except Empty:
                break


class HotkeyState(Enum):
    """Hotkey registration states."""
    UNREGISTERED = "unregistered"
    REGISTERING = "registering"
    REGISTERED = "registered"
    FAILED = "failed"
    CONFLICTED = "conflicted"


class ConflictResolution(Enum):
    """Conflict resolution strategies."""
    FALLBACK = "fallback"
    USER_PROMPT = "user_prompt"
    DISABLE = "disable"
    RETRY = "retry"


@dataclass
class HotkeyCombo:
    """Represents a hotkey combination."""
    modifiers: Set[str] = field(default_factory=set)
    key: str = ""
    display_name: str = ""
    raw_combination: str = ""

    def __post_init__(self):
        """Initialize computed fields."""
        if not self.display_name and self.raw_combination:
            self.display_name = self._format_display_name()

    def _format_display_name(self) -> str:
        """Format user-friendly display name."""
        if not self.modifiers or not self.key:
            return self.raw_combination

        # Sort modifiers for consistency
        mod_order = ['ctrl', 'alt', 'shift', 'win', 'cmd']
        sorted_mods = sorted(self.modifiers, key=lambda x: mod_order.index(x) if x in mod_order else 999)

        # Capitalize for display
        display_mods = [mod.title() for mod in sorted_mods]
        display_key = self.key.upper() if len(self.key) == 1 else self.key.title()

        return "+".join(display_mods + [display_key])

    def matches_event(self, pressed_keys: Set[str], key: str) -> bool:
        """Check if this combo matches a key event."""
        return self.modifiers == pressed_keys and self.key.lower() == key.lower()


@dataclass
class ConflictInfo:
    """Information about hotkey conflicts."""
    hotkey_id: str
    combination: HotkeyCombo
    conflict_source: str = "unknown"
    suggested_alternatives: List[HotkeyCombo] = field(default_factory=list)
    resolution_status: str = "unresolved"
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class HotkeyRegistration:
    """Hotkey registration information."""
    hotkey_id: str
    combination: HotkeyCombo
    action: str
    state: HotkeyState = HotkeyState.UNREGISTERED
    callback: Optional[Callable] = None
    conflict_info: Optional[ConflictInfo] = None
    registration_time: Optional[datetime] = None
    last_triggered: Optional[datetime] = None
    trigger_count: int = 0


class HotkeyValidationError(Exception):
    """Exception raised when hotkey validation fails."""
    pass


class HotkeyConflictError(Exception):
    """Exception raised when hotkey conflicts are detected."""
    pass


class HotkeyHandler:
    """
    Global hotkey handler with asynchronous event emission.

    Manages hotkey registration, monitoring, and conflict resolution
    using pynput for cross-platform global hotkey detection.
    """

    def __init__(
        self,
        event_bus: EventBus,
        settings_manager: SettingsManager,
        max_retries: int = 3,
        retry_delay: float = 1.0
    ):
        """
        Initialize HotkeyHandler.

        Args:
            event_bus: EventBus instance for event emission
            settings_manager: SettingsManager for configuration
            max_retries: Maximum registration retry attempts
            retry_delay: Delay between retry attempts
        """
        self.event_bus = event_bus
        self.settings_manager = settings_manager
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        # Registration state
        self._registrations: Dict[str, HotkeyRegistration] = {}
        self._active_listener: Optional[keyboard.Listener] = None
        self._listener_thread: Optional[threading.Thread] = None
        self._pressed_keys: Set[str] = set()
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None

        # Control flags
        self._initialized = False
        self._shutdown_requested = False
        self._registration_lock = asyncio.Lock()
        self._reload_scheduled = False

        # Thread-safe event queue for hotkey events
        self._event_queue = ThreadSafeEventQueue()

        # Thread executor for blocking operations
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="hotkey")

        # Validation rules
        self._validation_rules = self._setup_validation_rules()

        # Fallback key alternatives
        self._fallback_keys = ['f9', 'f10', 'f11', 'f12']
        self._used_fallbacks: Set[str] = set()

        # Current hotkey configuration
        self._hotkey_config: Optional[Any] = None

        logger.debug("HotkeyHandler initialized")

    def _setup_validation_rules(self) -> Dict[str, Callable[[HotkeyCombo], bool]]:
        """Setup hotkey validation rules."""
        forbidden_combinations = {
            'ctrl+alt+del',  # Windows security
            'win+l',         # Windows lock
            'alt+tab',       # Window switching
            'ctrl+shift+esc', # Task manager
            'win+r',         # Run dialog
        }

        def validate_modifiers(combo: HotkeyCombo) -> bool:
            """Validate modifier requirements."""
            return len(combo.modifiers) >= 1

        def validate_forbidden(combo: HotkeyCombo) -> bool:
            """Check against forbidden combinations."""
            normalized = combo.raw_combination.lower().replace(' ', '')
            return normalized not in forbidden_combinations

        def validate_key_format(combo: HotkeyCombo) -> bool:
            """Validate key format."""
            if not combo.key:
                return False

            # Allow single characters and function keys
            if len(combo.key) == 1:
                return combo.key.isalnum()

            # Allow function keys and special keys
            allowed_special = {
                'f1', 'f2', 'f3', 'f4', 'f5', 'f6',
                'f7', 'f8', 'f9', 'f10', 'f11', 'f12',
                'esc', 'tab', 'space', 'enter', 'backspace',
                'delete', 'home', 'end', 'page_up', 'page_down',
                'up', 'down', 'left', 'right'
            }

            return combo.key.lower() in allowed_special

        return {
            'modifiers': validate_modifiers,
            'forbidden': validate_forbidden,
            'key_format': validate_key_format,
        }

    async def initialize_handlers(self) -> bool:
        """
        Initialize hotkey handlers and load default configuration.

        Returns:
            True if initialization successful
        """
        if self._initialized:
            logger.warning("HotkeyHandler already initialized")
            return True

        try:
            logger.debug("Initializing hotkey handlers...")

            # Get the current event loop and set it in the event queue
            try:
                loop = asyncio.get_running_loop()
                self._event_queue.set_event_loop(loop)
                self._event_loop = loop
            except RuntimeError:
                logger.warning("No running event loop found during initialization")

            # Subscribe to settings updates
            await self.event_bus.subscribe(
                EventTypes.SETTINGS_UPDATED,
                self._handle_settings_updated,
                priority=100
            )

            # Load hotkey configuration
            await self._load_hotkey_configuration()

            # Register default hotkeys
            await self._register_default_hotkeys()

            # Start global listener
            await self._start_global_listener()

            # Start event queue processor
            asyncio.create_task(self._process_hotkey_events())

            self._initialized = True

            # Emit ready event
            await self.event_bus.emit(
                "hotkey.handler.ready",
                {
                    'registered_hotkeys': list(self._registrations.keys()),
                    'listener_active': self._active_listener is not None
                },
                source="HotkeyHandler"
            )

            logger.debug("HotkeyHandler initialization complete")
            return True

        except Exception as e:
            logger.error("Failed to initialize hotkey handlers: %s", e)
            await self.event_bus.emit(
                "hotkey.handler.error",
                {
                    'error_type': 'initialization_failed',
                    'error_message': str(e),
                    'recovery_action': 'manual_restart'
                },
                source="HotkeyHandler"
            )
            return False

    async def _load_hotkey_configuration(self) -> None:
        """Load hotkey configuration from settings."""
        try:
            settings = await self.settings_manager.load_settings()
            self._hotkey_config = settings.hotkeys

            logger.debug("Loaded hotkey configuration: %s", self._hotkey_config)

        except Exception as e:
            logger.error("Failed to load hotkey configuration: %s", e)
            # Use defaults if loading fails

    async def _register_default_hotkeys(self) -> None:
        """Register default application hotkeys."""
        # Use configured hotkeys from settings, or fall back to defaults
        if self._hotkey_config:
            hotkey_definitions = [
                {
                    'hotkey_id': 'screenshot_capture',
                    'combination': self._hotkey_config.screenshot_capture,
                    'action': 'capture_screenshot',
                    'description': 'Capture screenshot'
                },
                {
                    'hotkey_id': 'overlay_toggle',
                    'combination': self._hotkey_config.overlay_toggle,
                    'action': 'toggle_overlay',
                    'description': 'Toggle overlay window'
                },
                {
                    'hotkey_id': 'settings_open',
                    'combination': self._hotkey_config.settings_open,
                    'action': 'open_settings',
                    'description': 'Open settings window'
                }
            ]
        else:
            # Fallback to hardcoded defaults if config not loaded
            logger.warning("No hotkey configuration loaded, using defaults")
            hotkey_definitions = [
                {
                    'hotkey_id': 'screenshot_capture',
                    'combination': 'ctrl+shift+s',
                    'action': 'capture_screenshot',
                    'description': 'Capture screenshot'
                },
                {
                    'hotkey_id': 'overlay_toggle',
                    'combination': 'ctrl+shift+o',
                    'action': 'toggle_overlay',
                    'description': 'Toggle overlay window'
                },
                {
                    'hotkey_id': 'settings_open',
                    'combination': 'ctrl+shift+p',
                    'action': 'open_settings',
                    'description': 'Open settings window'
                }
            ]

        for hotkey_def in hotkey_definitions:
            try:
                combo = self._parse_hotkey_combination(hotkey_def['combination'])
                success = await self.register_hotkey(
                    hotkey_def['hotkey_id'],
                    combo,
                    hotkey_def['action']
                )

                if success:
                    logger.debug("Registered hotkey: %s -> %s",
                              combo.display_name, hotkey_def['action'])
                else:
                    logger.warning("Failed to register hotkey: %s", hotkey_def['hotkey_id'])

            except Exception as e:
                logger.error("Error registering default hotkey %s: %s",
                           hotkey_def['hotkey_id'], e)

    def _parse_hotkey_combination(self, combination: str) -> HotkeyCombo:
        """
        Parse hotkey combination string into HotkeyCombo.

        Args:
            combination: String like "ctrl+shift+s"

        Returns:
            HotkeyCombo object

        Raises:
            HotkeyValidationError: If combination is invalid
        """
        if not combination or not isinstance(combination, str):
            raise HotkeyValidationError("Invalid combination format")

        # Normalize and split
        parts = [part.strip().lower() for part in combination.split('+')]

        if len(parts) < 2:
            raise HotkeyValidationError("Hotkey must have at least one modifier and one key")

        # Separate modifiers and key
        key = parts[-1]
        modifiers = set(parts[:-1])

        # Validate modifiers
        valid_modifiers = {'ctrl', 'alt', 'shift', 'win', 'cmd', 'meta'}
        invalid_mods = modifiers - valid_modifiers
        if invalid_mods:
            raise HotkeyValidationError(f"Invalid modifiers: {invalid_mods}")

        combo = HotkeyCombo(
            modifiers=modifiers,
            key=key,
            raw_combination=combination
        )

        # Validate the combination
        self._validate_hotkey_combination(combo)

        return combo

    def _validate_hotkey_combination(self, combo: HotkeyCombo) -> None:
        """
        Validate hotkey combination against rules.

        Args:
            combo: HotkeyCombo to validate

        Raises:
            HotkeyValidationError: If validation fails
        """
        for rule_name, validator in self._validation_rules.items():
            try:
                if not validator(combo):
                    raise HotkeyValidationError(f"Validation failed: {rule_name}")
            except Exception as e:
                raise HotkeyValidationError(f"Validation error in {rule_name}: {e}")

    async def register_hotkey(
        self,
        hotkey_id: str,
        combination: HotkeyCombo,
        action: str
    ) -> bool:
        """
        Register a hotkey with conflict detection.

        Args:
            hotkey_id: Unique identifier for the hotkey
            combination: HotkeyCombo object
            action: Action to trigger

        Returns:
            True if registered successfully
        """
        async with self._registration_lock:
            try:
                logger.debug("Registering hotkey: %s -> %s",
                           hotkey_id, combination.display_name)

                # Check for existing registration
                if hotkey_id in self._registrations:
                    await self.unregister_hotkey(hotkey_id)

                # Create registration
                registration = HotkeyRegistration(
                    hotkey_id=hotkey_id,
                    combination=combination,
                    action=action,
                    state=HotkeyState.REGISTERING
                )

                # Test registration (mock implementation)
                success = await self._test_hotkey_registration(combination)

                if success:
                    registration.state = HotkeyState.REGISTERED
                    registration.registration_time = datetime.now()
                    self._registrations[hotkey_id] = registration

                    await self.event_bus.emit(
                        "hotkey.registration.success",
                        {
                            'hotkey_id': hotkey_id,
                            'combination': combination.display_name,
                            'action': action
                        },
                        source="HotkeyHandler"
                    )

                    return True
                else:
                    # Handle conflict
                    await self._handle_registration_conflict(registration)
                    return False

            except Exception as e:
                logger.error("Error registering hotkey %s: %s", hotkey_id, e)

                await self.event_bus.emit(
                    "hotkey.registration.failed",
                    {
                        'hotkey_id': hotkey_id,
                        'reason': str(e),
                        'suggestion': 'Try a different key combination'
                    },
                    source="HotkeyHandler"
                )

                return False

    async def _test_hotkey_registration(self, combination: HotkeyCombo) -> bool:
        """
        Test if hotkey can be registered (mock implementation).

        Args:
            combination: HotkeyCombo to test

        Returns:
            True if registration is possible
        """
        # Mock implementation - simulate some conflicts

        # Simulate conflict with common system hotkeys
        conflicting_combos = {
            'ctrl+shift+esc',  # Task Manager
            'alt+tab',         # Window switcher
            'win+l'            # Lock screen
        }

        if combination.raw_combination.lower() in conflicting_combos:
            logger.debug("Simulated conflict detected for: %s", combination.display_name)
            return False

        return True

    async def _handle_registration_conflict(self, registration: HotkeyRegistration) -> None:
        """
        Handle hotkey registration conflicts.

        Args:
            registration: Failed registration to handle
        """
        logger.warning("Hotkey conflict detected: %s", registration.combination.display_name)

        # Create conflict info
        conflict_info = ConflictInfo(
            hotkey_id=registration.hotkey_id,
            combination=registration.combination,
            conflict_source="system",
            suggested_alternatives=self._generate_alternatives(registration.combination)
        )

        registration.conflict_info = conflict_info
        registration.state = HotkeyState.CONFLICTED

        # Try automatic resolution with fallback
        resolved = await self._resolve_conflict_automatically(registration)

        if not resolved:
            # Emit conflict event for user resolution
            await self.event_bus.emit(
                "hotkey.conflict.detected",
                {
                    'hotkey_id': registration.hotkey_id,
                    'conflicting_combination': registration.combination.display_name,
                    'alternatives': [alt.display_name for alt in conflict_info.suggested_alternatives],
                    'resolution_options': ['fallback', 'user_select', 'disable']
                },
                source="HotkeyHandler"
            )

    def _generate_alternatives(self, original: HotkeyCombo) -> List[HotkeyCombo]:
        """
        Generate alternative hotkey combinations.

        Args:
            original: Original combination that failed

        Returns:
            List of alternative combinations
        """
        alternatives = []

        # Try different modifier combinations
        modifier_variations = [
            {'ctrl', 'alt'},
            {'ctrl', 'shift', 'alt'},
            {'win', 'shift'},
            {'ctrl', 'win'}
        ]

        for mods in modifier_variations:
            if mods != original.modifiers:
                alt_combo = HotkeyCombo(
                    modifiers=mods,
                    key=original.key,
                    raw_combination='+'.join(sorted(mods) + [original.key])
                )
                alternatives.append(alt_combo)

        # Try fallback function keys
        for fallback_key in self._fallback_keys:
            if fallback_key not in self._used_fallbacks:
                alt_combo = HotkeyCombo(
                    modifiers={'ctrl', 'shift'},
                    key=fallback_key,
                    raw_combination=f'ctrl+shift+{fallback_key}'
                )
                alternatives.append(alt_combo)

        return alternatives[:3]  # Limit to 3 alternatives

    async def _resolve_conflict_automatically(self, registration: HotkeyRegistration) -> bool:
        """
        Attempt automatic conflict resolution.

        Args:
            registration: Registration with conflict

        Returns:
            True if resolved automatically
        """
        if not registration.conflict_info or not registration.conflict_info.suggested_alternatives:
            return False

        # Try each alternative
        for alternative in registration.conflict_info.suggested_alternatives:
            if await self._test_hotkey_registration(alternative):
                logger.debug("Auto-resolved conflict: %s -> %s",
                          registration.combination.display_name,
                          alternative.display_name)

                # Update registration
                registration.combination = alternative
                registration.state = HotkeyState.REGISTERED
                registration.registration_time = datetime.now()
                registration.conflict_info.resolution_status = "auto_resolved"

                self._registrations[registration.hotkey_id] = registration

                # Mark fallback as used if applicable
                if alternative.key in self._fallback_keys:
                    self._used_fallbacks.add(alternative.key)

                await self.event_bus.emit(
                    "hotkey.conflict.resolved",
                    {
                        'hotkey_id': registration.hotkey_id,
                        'original_combination': registration.conflict_info.combination.display_name,
                        'resolved_combination': alternative.display_name,
                        'resolution_method': 'automatic'
                    },
                    source="HotkeyHandler"
                )

                return True

        return False

    async def unregister_hotkey(self, hotkey_id: str) -> bool:
        """
        Unregister a hotkey.

        Args:
            hotkey_id: ID of hotkey to unregister

        Returns:
            True if unregistered successfully
        """
        async with self._registration_lock:
            if hotkey_id not in self._registrations:
                logger.warning("Hotkey not found for unregistration: %s", hotkey_id)
                return False

            registration = self._registrations[hotkey_id]

            # Remove from fallback tracking if applicable
            if registration.combination.key in self._used_fallbacks:
                self._used_fallbacks.discard(registration.combination.key)

            # Remove registration
            del self._registrations[hotkey_id]

            logger.debug("Unregistered hotkey: %s", hotkey_id)
            return True

    async def unregister_all_hotkeys(self) -> None:
        """Unregister all hotkeys."""
        try:
            async with self._registration_lock:
                hotkey_ids = list(self._registrations.keys())

                for hotkey_id in hotkey_ids:
                    registration = self._registrations.get(hotkey_id)
                    if registration:
                        # Remove from fallback tracking if applicable
                        if registration.combination.key in self._used_fallbacks:
                            self._used_fallbacks.discard(registration.combination.key)

                        # Remove registration
                        del self._registrations[hotkey_id]

                self._used_fallbacks.clear()
                logger.debug("All hotkeys unregistered")
        except Exception as e:
            logger.error("Error unregistering all hotkeys: %s", e)

    async def reload_configuration(self) -> bool:
        """
        Reload hotkey configuration from settings.

        Returns:
            True if reloaded successfully
        """
        try:
            logger.debug("Reloading hotkey configuration")

            # Unregister current hotkeys
            await self.unregister_all_hotkeys()

            # Reload configuration
            await self._load_hotkey_configuration()

            # Re-register default hotkeys
            await self._register_default_hotkeys()

            await self.event_bus.emit(
                "hotkey.configuration.reloaded",
                {
                    'registered_count': len(self._registrations),
                    'active_hotkeys': list(self._registrations.keys())
                },
                source="HotkeyHandler"
            )

            return True

        except Exception as e:
            logger.error("Failed to reload hotkey configuration: %s", e)
            return False

    async def _start_global_listener(self) -> None:
        """Start the global hotkey listener."""
        if self._active_listener is not None:
            logger.warning("Global listener already active")
            return

        try:
            # Create listener in thread executor to avoid blocking
            loop = asyncio.get_event_loop()
            self._event_loop = loop
            self._active_listener = await loop.run_in_executor(
                self._executor,
                self._create_listener
            )

            # Start listener in background thread
            self._listener_thread = threading.Thread(
                target=self._run_listener,
                name="HotkeyListener",
                daemon=True
            )
            self._listener_thread.start()

            logger.debug("Global hotkey listener started")

        except Exception as e:
            logger.error("Failed to start global listener: %s", e)
            self._active_listener = None

    def _create_listener(self) -> keyboard.Listener:
        """Create pynput keyboard listener."""
        return keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
            suppress=False  # Don't suppress key events
        )

    def _run_listener(self) -> None:
        """Run the keyboard listener."""
        if self._active_listener is None:
            return

        try:
            self._active_listener.start()
            self._active_listener.join()
        except Exception as e:
            logger.error("Listener thread error: %s", e)
        finally:
            self._active_listener = None

    def _on_key_press(self, key) -> None:
        """Handle key press events."""
        try:
            # Convert key to string
            key_str = self._key_to_string(key)

            # Skip control characters and unknown keys
            if key_str in {'unknown', ''} or (len(key_str) == 1 and ord(key_str) < 32):
                return

            # Track modifier keys
            if key_str in {'ctrl', 'alt', 'shift', 'win', 'cmd'}:
                self._pressed_keys.add(key_str)
            else:
                # Check for hotkey matches
                self._check_hotkey_match(key_str)

        except Exception as e:
            logger.error("Error handling key press: %s", e)

    def _on_key_release(self, key) -> None:
        """Handle key release events."""
        try:
            key_str = self._key_to_string(key)

            # Remove from pressed keys
            self._pressed_keys.discard(key_str)

        except Exception as e:
            logger.error("Error handling key release: %s", e)

    def _key_to_string(self, key) -> str:
        """Convert pynput key to string."""
        try:
            # First try to get the key name (more reliable for modified keys)
            if hasattr(key, 'name') and key.name:
                # Map special keys and handle modified key names
                key_map = {
                    'ctrl_l': 'ctrl',
                    'ctrl_r': 'ctrl',
                    'alt_l': 'alt',
                    'alt_r': 'alt',
                    'shift_l': 'shift',
                    'shift_r': 'shift',
                    'cmd': 'win',
                    'cmd_l': 'win',
                    'cmd_r': 'win',
                }

                # If it's a direct key name like 'o', return it
                if key.name in key_map:
                    return key_map[key.name]
                elif len(key.name) == 1:
                    return key.name.lower()
                else:
                    return key.name.lower()

            # Handle control characters that appear when Ctrl is held
            if hasattr(key, 'char') and key.char is not None:
                char_code = ord(key.char)
                # Map control characters back to their original keys
                # Ctrl+A = 1, Ctrl+B = 2, ..., Ctrl+O = 15, etc.
                if 1 <= char_code <= 26:
                    # Convert control character back to letter (A=65, so 1->A, 2->B, etc.)
                    original_key = chr(char_code + 64).lower()
                    return original_key
                # Filter out other control characters
                elif 32 <= char_code <= 126:
                    return key.char.lower()

            # Last resort
            return str(key).lower()

        except Exception:
            return 'unknown'

    def _check_hotkey_match(self, key: str) -> None:
        """
        Check if current key combination matches any registered hotkey.

        Args:
            key: The pressed key
        """
        try:
            current_modifiers = self._pressed_keys.copy()

            # Check each registered hotkey
            for hotkey_id, registration in self._registrations.items():
                if registration.state != HotkeyState.REGISTERED:
                    continue

                if registration.combination.matches_event(current_modifiers, key):
                    # Found a match - add to thread-safe queue
                    hotkey_event = HotkeyEvent(
                        hotkey_id=registration.hotkey_id,
                        combination=registration.combination,
                        action=registration.action
                    )

                    # Queue the event for processing in the asyncio loop
                    self._event_queue.put_event(hotkey_event)

                    logger.debug("Hotkey queued for processing: %s (%s)",
                              registration.hotkey_id, registration.combination.display_name)
                    break

        except Exception as e:
            logger.error("Error checking hotkey match: %s", e)

    async def _process_hotkey_events(self) -> None:
        """
        Process hotkey events from the thread-safe queue.

        Runs continuously in the asyncio event loop.
        """
        while not self._shutdown_requested:
            try:
                # Check for events with a short timeout to avoid blocking
                event = self._event_queue.get_event(timeout=0.1)

                if event is not None:
                    await self._handle_hotkey_event(event)

                # Short sleep to yield control
                await asyncio.sleep(0.01)

            except Exception as e:
                logger.error("Error processing hotkey events: %s", e)
                await asyncio.sleep(0.1)

    async def _handle_hotkey_event(self, event: HotkeyEvent) -> None:
        """
        Handle a hotkey event in the asyncio context.

        Args:
            event: HotkeyEvent to process
        """
        try:
            # Get the registration to update statistics
            registration = self._registrations.get(event.hotkey_id)
            if registration:
                registration.last_triggered = datetime.now()
                registration.trigger_count += 1

            # Emit events based on action (same as before but cleaner)
            await self._emit_hotkey_action(event)

        except Exception as e:
            logger.error("Error handling hotkey event %s: %s", event.hotkey_id, e)

    async def _emit_hotkey_action(self, event: HotkeyEvent) -> None:
        """
        Emit appropriate events for hotkey actions.

        Args:
            event: HotkeyEvent to emit for
        """
        try:
            if event.action == 'capture_screenshot':
                await self.event_bus.emit(
                    EventTypes.HOTKEY_SCREENSHOT_CAPTURE,
                    {
                        'hotkey_id': event.hotkey_id,
                        'combination': event.combination.display_name,
                        'timestamp': event.timestamp,
                        'mock_action': 'screenshot_capture_requested'
                    },
                    source="HotkeyHandler"
                )

            elif event.action == 'toggle_overlay':
                await self.event_bus.emit(
                    EventTypes.HOTKEY_OVERLAY_TOGGLE,
                    {
                        'hotkey_id': event.hotkey_id,
                        'combination': event.combination.display_name,
                        'timestamp': event.timestamp,
                        'mock_action': 'overlay_toggle_requested'
                    },
                    source="HotkeyHandler"
                )

            elif event.action == 'open_settings':
                await self.event_bus.emit(
                    EventTypes.HOTKEY_SETTINGS_OPEN,
                    {
                        'hotkey_id': event.hotkey_id,
                        'combination': event.combination.display_name,
                        'timestamp': event.timestamp,
                        'mock_action': 'settings_open_requested'
                    },
                    source="HotkeyHandler"
                )

            else:
                # Generic hotkey event
                await self.event_bus.emit(
                    f"hotkey.{event.action}",
                    {
                        'hotkey_id': event.hotkey_id,
                        'combination': event.combination.display_name,
                        'action': event.action,
                        'timestamp': event.timestamp
                    },
                    source="HotkeyHandler"
                )

        except Exception as e:
            logger.error("Error emitting hotkey action %s: %s", event.action, e)

    async def _handle_settings_updated(self, event_data) -> None:
        """Handle settings update events."""
        try:
            if (event_data.data and
                isinstance(event_data.data, dict) and
                'key' in event_data.data and
                event_data.data['key'].startswith('hotkeys.')):

                is_full_save = event_data.data.get("full_save", False)
                if not is_full_save:  # Only schedule reload on individual updates, not full saves
                    # Schedule a reload with debouncing to avoid multiple reloads for batch updates
                    if not hasattr(self, '_reload_scheduled') or not self._reload_scheduled:
                        self._reload_scheduled = True
                        # Schedule reload after a short delay to batch multiple updates
                        asyncio.create_task(self._delayed_reload())
                else:
                    logger.debug("Hotkey settings full save, skipping individual reload")

        except Exception as e:
            logger.error("Error handling settings update: %s", e)

    async def _delayed_reload(self) -> None:
        """Delayed reload to batch multiple hotkey setting updates."""
        try:
            await asyncio.sleep(0.1)  # Short delay to batch updates
            if self._reload_scheduled:
                self._reload_scheduled = False
                logger.debug("Hotkey settings updated, reloading configuration")
                await self.reload_configuration()
        except Exception as e:
            logger.error("Error in delayed reload: %s", e)
            self._reload_scheduled = False

    def get_registered_hotkeys(self) -> Dict[str, HotkeyCombo]:
        """
        Get all registered hotkeys.

        Returns:
            Dictionary mapping hotkey_id to HotkeyCombo
        """
        return {
            hotkey_id: reg.combination
            for hotkey_id, reg in self._registrations.items()
            if reg.state == HotkeyState.REGISTERED
        }

    def is_handler_active(self) -> bool:
        """
        Check if hotkey handler is active.

        Returns:
            True if handler is active and listening
        """
        return (self._initialized and
                self._active_listener is not None and
                not self._shutdown_requested)

    def get_conflict_report(self) -> List[ConflictInfo]:
        """
        Get report of all hotkey conflicts.

        Returns:
            List of conflict information
        """
        conflicts = []

        for registration in self._registrations.values():
            if (registration.state == HotkeyState.CONFLICTED and
                registration.conflict_info is not None):
                conflicts.append(registration.conflict_info)

        return conflicts

    async def check_hotkey_availability(self, combination: HotkeyCombo) -> bool:
        """
        Check if a hotkey combination is available.

        Args:
            combination: HotkeyCombo to check

        Returns:
            True if available
        """
        try:
            # Validate the combination first
            self._validate_hotkey_combination(combination)

            # Test registration
            return await self._test_hotkey_registration(combination)

        except HotkeyValidationError:
            return False
        except Exception as e:
            logger.error("Error checking hotkey availability: %s", e)
            return False

    async def shutdown_handlers(self) -> None:
        """Shutdown hotkey handlers gracefully."""
        if self._shutdown_requested:
            return

        logger.debug("Shutting down HotkeyHandler")
        self._shutdown_requested = True

        try:
            # Unregister all hotkeys
            await self.unregister_all_hotkeys()

            # Shutdown event queue
            self._event_queue.shutdown()

            # Stop global listener
            if self._active_listener is not None:
                self._active_listener.stop()
                self._active_listener = None

            # Wait for listener thread to finish
            if self._listener_thread is not None and self._listener_thread.is_alive():
                self._listener_thread.join(timeout=2.0)

            # Shutdown thread executor
            if hasattr(self, '_executor'):
                self._executor.shutdown(wait=True)

            # Clear event loop reference
            self._event_loop = None

            await self.event_bus.emit(
                "hotkey.handler.shutdown",
                source="HotkeyHandler"
            )

            logger.debug("HotkeyHandler shutdown complete")

        except Exception as e:
            logger.error("Error during HotkeyHandler shutdown: %s", e)

    def __str__(self) -> str:
        """String representation."""
        return (f"HotkeyHandler(initialized={self._initialized}, "
                f"registered={len(self._registrations)}, "
                f"active={self.is_handler_active()})")
