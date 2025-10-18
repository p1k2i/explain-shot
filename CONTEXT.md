# ExplainShot: Project Context Document

## Executive Summary

**ExplainShot** is a lightweight, cross-platform desktop application designed to capture screenshots and provide AI-powered explanations of their content. Built with Python 3.12, it follows the MVC (Model-View-Controller) architectural pattern with a strong emphasis on modularity, loose coupling, and event-driven communication. The application runs as a background daemon with system tray integration and uses asynchronous programming throughout for responsive, non-blocking operations.

---

## 1. Project Overview

### Purpose and Goals

ExplainShot addresses the need for intelligent screenshot analysis without heavyweight workflows. Its primary goals are:

- **Efficient Screenshot Capture**: Capture full-screen or region-specific screenshots with minimal overhead
- **AI-Powered Analysis**: Integrate local AI models (via Ollama) for intelligent screenshot explanation
- **Minimal Resource Footprint**: Operate as a background daemon with <50MB memory usage and <0.1% CPU when idle
- **User-Centric Interface**: Provide an intuitive tray-based UI with hotkey shortcuts and configurable settings
- **Privacy-First Design**: Process screenshots locally without requiring external cloud services
- **Extensibility**: Support multiple AI models, custom prompts, and user presets for analysis

### Key Characteristics

- **Lightweight Architecture**: Minimal external dependencies while maintaining rich functionality
- **Async-First Design**: Leverages Python's asyncio for responsive, non-blocking operations
- **Event-Driven**: Components communicate through a centralized EventBus, enabling loose coupling
- **Cross-Platform Target**: Windows primary with macOS and Linux compatibility considerations
- **Local-Only Processing**: All AI inference runs on the user's machine via Ollama
- **Configurable Deployment**: Supports single-executable distribution via PyInstaller

---

## 2. Architecture

### 2.1 High-Level Architecture Overview

ExplainShot implements a **layered MVC architecture** with event-driven communication:

```
┌────────────────────────────────────────────────────────────┐
│                   Application Layer                         │
│        (Main Application, Lifecycle, Signal Handling)       │
└────────────────────────────────────────────────────────────┘
                              ▼
┌────────────────────────────────────────────────────────────┐
│                   Controller Layer                          │
│   EventBus │ MainController │ HotkeyHandler │ Orchestration │
└────────────────────────────────────────────────────────────┘
         ▲                                          ▲
         │ Event Emission & Subscription            │
         │                                          │
┌────────────────────────────────────────────────────────────┐
│                      View Layer                            │
│   TrayManager │ UIManager │ OverlayWindow │ SettingsWindow │
│   GalleryWindow │ IconManager                              │
└────────────────────────────────────────────────────────────┘
         ▲                                          ▲
         │ Query & Display State                    │
         │                                          │
┌────────────────────────────────────────────────────────────┐
│                      Model Layer                           │
│   ScreenshotManager │ SettingsManager │ DatabaseManager    │
│   OllamaClient │ AutoStartManager                          │
└────────────────────────────────────────────────────────────┘
         ▲                                          ▲
         │ Data Access & Persistence                │
         │                                          │
┌────────────────────────────────────────────────────────────┐
│                   Utility Layer                            │
│   Logging │ Icon Management │ Auto-Start │ Validation      │
└────────────────────────────────────────────────────────────┘
```

### 2.2 MVC Pattern Implementation

#### Model Layer (Data & Business Logic)

The Model layer is responsible for all data operations and business logic, isolated from UI concerns:

- **ScreenshotManager**: Handles screenshot capture using PIL/Pillow, file management, and database integration
- **SettingsManager**: Manages application configuration with validation and event propagation for changes
- **DatabaseManager**: Provides async SQLite operations for screenshots, chat history, presets, and settings
- **OllamaClient**: Integrates with local Ollama server for AI analysis with health monitoring and fallback support
- **AutoStartManager**: Manages Windows startup registration via Registry or Startup Folder

**Key Principle**: Models contain no UI logic and communicate through well-defined interfaces.

#### View Layer (User Interface)

The View layer displays data and captures user interactions:

- **TrayManager**: System tray icon lifecycle, context menu creation, and icon state management (pystray)
- **UIManager**: Centralized UI management for PyQt6 windows
- **OverlayWindow**: Displays screenshot overlays for annotation and interaction
- **SettingsWindow**: Provides settings configuration interface (PyQt6)
- **GalleryWindow**: Displays screenshot gallery with chat history and analysis (PyQt6)
- **IconManager**: Dynamic icon state management with theme support and fallback icon generation

**Key Principle**: Views read data from Models and emit events through EventBus for user actions.

#### Controller Layer (Orchestration & Logic Flow)

The Controller layer coordinates between Views and Models, handling business logic and user interactions:

- **MainController**: Central orchestrator managing component initialization, event subscription, and business logic coordination
- **EventBus**: Asynchronous pub-sub system enabling loose coupling between all components
- **HotkeyHandler**: Global hotkey registration and monitoring with thread-safe event queuing for asyncio integration

**Key Principle**: Controllers coordinate flow without maintaining state; they delegate to Models and Views.

### 2.3 Event-Driven Communication

The **EventBus** is the backbone of the MVC implementation, enabling components to communicate without direct dependencies:

```
User Action → View → EventBus → Controller → Model → Database
                          ↑                      ↓
                    Update Propagated      Event Emitted
                          ↑                      ↓
                      View Refreshed ← ← ← ← ← ←
```

#### Event Subscription Pattern

```
Component A.subscribe("event.type", async handler_func)
    ↓
EventBus stores handler with priority and metadata
    ↓
Component B.emit("event.type", data)
    ↓
EventBus routes to all subscribers in priority order
    ↓
Handlers execute asynchronously, failures isolated
```

#### Key Event Categories

- **Application Lifecycle**: `APP_READY`, `APP_SHUTDOWN_REQUESTED`, `APP_SHUTDOWN_STARTING`
- **Screenshot Operations**: `SCREENSHOT_CAPTURE_REQUESTED`, `SCREENSHOT_CAPTURED`, `SCREENSHOT_COMPLETED`
- **UI Interactions**: `UI_OVERLAY_SHOW`, `UI_OVERLAY_HIDE`, `UI_SETTINGS_SHOW`, `UI_GALLERY_SHOW`
- **Settings Management**: `SETTINGS_UPDATED`, `SETTINGS_CHANGED`, `SETTINGS_SAVED`
- **Hotkey Events**: `HOTKEY_SCREENSHOT_CAPTURE`, `HOTKEY_OVERLAY_TOGGLE`, `HOTKEY_SETTINGS_OPEN`
- **AI Operations**: `OLLAMA_RESPONSE_RECEIVED`
- **Error Handling**: `ERROR_OCCURRED`

### 2.4 Threading Model

The application uses a multi-threaded architecture with clear separation of concerns:

1. **Main Thread (asyncio Event Loop)**:
   - Runs the primary asyncio event loop
   - Handles all business logic and database operations
   - Processes events from the EventBus
   - Coordinates with PyQt6 event processing

2. **Pynput Hotkey Thread**:
   - Monitors global hotkeys using the pynput library
   - Bridges to main thread via `ThreadSafeEventQueue`
   - Isolated from main logic to prevent blocking

3. **System Tray Thread**:
   - Manages pystray icon and menu (runs in separate thread)
   - Communicates with main thread via EventBus
   - Handles OS-level tray interactions

4. **PyQt6 Thread (UI)**:
   - Runs in main thread alongside asyncio
   - Shares event loop with asyncio for coordination
   - Processes UI events and updates

### 2.5 Data Flow Architecture

#### Screenshot Capture Flow

```
User Hotkey
    ↓
HotkeyHandler (pynput thread) → ThreadSafeEventQueue → EventBus
    ↓
MainController receives HOTKEY_SCREENSHOT_CAPTURE event
    ↓
MainController calls ScreenshotManager.capture_screenshot()
    ↓
ScreenshotManager captures with PIL/Pillow → saves to disk → creates thumbnail
    ↓
ScreenshotManager registers metadata in DatabaseManager
    ↓
EventBus emits SCREENSHOT_CAPTURED and SCREENSHOT_COMPLETED
    ↓
GalleryWindow updates with new screenshot
    ↓
TrayManager updates icon state
```

#### Settings Change Propagation

```
User modifies setting in SettingsWindow
    ↓
SettingsWindow emits SETTINGS_UPDATED event
    ↓
SettingsManager receives event → validates → saves to database
    ↓
SettingsManager emits SETTINGS_CHANGED event with new value
    ↓
All subscribed components receive update
    ↓
GalleryWindow, OverlayWindow, TrayManager refresh UI
    ↓
HotkeyHandler re-registers hotkeys if changed
```

#### AI Analysis Flow

```
User selects screenshot in Gallery → sends prompt with preset
    ↓
MainController receives GALLERY_CHAT_MESSAGE_SENT event
    ↓
MainController calls OllamaClient.send_prompt(image, prompt)
    ↓
OllamaClient: Validates connection → loads image → sends to Ollama
    ↓
OllamaClient receives response → stores in DatabaseManager
    ↓
OllamaClient emits OLLAMA_RESPONSE_RECEIVED event
    ↓
GalleryWindow displays response in chat interface
    ↓
Response saved with screenshot metadata for future reference
```

---

## 3. Design Patterns

ExplainShot implements multiple design patterns to ensure maintainability, extensibility, and robustness:

### 3.1 Singleton Pattern

**Implementation**: Global EventBus instance

**Location**: `src/controllers/event_bus.py` - `get_event_bus()` function

**Purpose**: Ensures a single EventBus instance accessible throughout the application, coordinating all event communication.

**Why Used**: Multiple event buses would create inconsistencies; a single instance ensures unified communication.

```
get_event_bus() → Global instance cached in module variable
    ↓
Multiple components access same instance
    ↓
All subscriptions and emissions route through single bus
```

### 3.2 Observer/Pub-Sub Pattern

**Implementation**: EventBus with subscribe/emit mechanics

**Locations**:
- `src/controllers/event_bus.py` - Core EventBus implementation
- All model, view, and controller components - Subscribers

**Purpose**: Decouples components so they don't need to know about each other's existence.

**Why Used**: Enables loose coupling; components communicate through events rather than direct references.

**Example Use Cases**:
- SettingsManager publishes changes; multiple UI components subscribe
- HotkeyHandler publishes hotkey events; MainController subscribes
- ScreenshotManager publishes capture completion; GalleryWindow subscribes to refresh

### 3.3 MVC (Model-View-Controller) Pattern

**Implementation**:
- **Model**: `src/models/*` - ScreenshotManager, SettingsManager, DatabaseManager, OllamaClient
- **View**: `src/views/*` - TrayManager, UIManager, Windows
- **Controller**: `src/controllers/*` - MainController, EventBus, HotkeyHandler

**Purpose**: Separates concerns into distinct layers for maintainability.

**Why Used**: Enables independent evolution of UI, business logic, and data access; facilitates testing.

### 3.4 Facade Pattern

**Implementation**: MainController and UIManager

**Location**:
- `src/controllers/main_controller.py` - Orchestrates complex interactions
- `src/views/ui_manager.py` - Simplifies UI component management

**Purpose**: Provides simplified interface to complex subsystems.

**Why Used**:
- MainController hides the complexity of coordinating ScreenshotManager, SettingsManager, DatabaseManager, OllamaClient
- UIManager abstracts PyQt6 window management for the application

**Example**: MainController.handle_screenshot_request() coordinates multiple components internally.

### 3.5 Factory Pattern

**Implementation**: Icon and component creation

**Locations**:
- `src/utils/icon_manager.py` - Creates icons based on state and theme
- `src/utils/auto_start.py` - Creates AutoStartManager instance appropriate for OS

**Purpose**: Decouples object creation from usage, enabling flexible instantiation.

**Why Used**: Icons need different generation logic based on state and theme; platform-specific implementations vary.

### 3.6 Strategy Pattern

**Implementation**: Screenshot capture strategies, export formats, AI model selection

**Locations**:
- `src/models/screenshot_manager.py` - Different capture regions (full screen, region, specific monitor)
- `src/models/ollama_client.py` - Model selection and streaming vs. non-streaming responses
- Auto-start configuration - Registry vs. Startup Folder methods

**Purpose**: Encapsulates interchangeable algorithms allowing runtime selection.

**Why Used**: Different capture regions, AI models, and auto-start methods serve different scenarios.

### 3.7 Adapter Pattern

**Implementation**: ThreadSafeEventQueue bridges pynput thread to asyncio loop

**Location**: `src/controllers/hotkey_handler.py` - ThreadSafeEventQueue class

**Purpose**: Converts thread-based pynput callbacks into asyncio-compatible events.

**Why Used**: pynput operates in a separate thread with blocking callbacks; asyncio requires cooperative scheduling. The adapter translates between paradigms.

```
pynput thread → put_event() → ThreadSafeEventQueue → call_soon_threadsafe()
    ↓
Main asyncio thread → get_event() → EventBus → Subscribers
```

### 3.8 Lazy Initialization Pattern

**Implementation**: Components initialized on-demand

**Locations**:
- Main.py - Initializes components sequentially
- ScreenshotManager - Lazy directory creation
- DatabaseManager - On-demand connection pooling

**Purpose**: Reduces startup time and resource usage.

**Why Used**: Not all features needed at startup; improves perceived responsiveness.

### 3.9 Error Isolation Pattern

**Implementation**: EventBus handler failures don't affect other handlers

**Location**: `src/controllers/event_bus.py` - `_process_event_immediate()` method

**Purpose**: Prevents cascading failures.

**Why Used**: One failed screenshot handler shouldn't prevent UI updates; all handlers execute independently.

### 3.10 Weak Reference Pattern

**Implementation**: EventBus uses weak references for handlers to prevent memory leaks

**Location**: `src/controllers/event_bus.py` - Subscribe with `weak_ref=True`

**Purpose**: Automatically cleans up dead references when objects are garbage collected.

**Why Used**: Prevents memory leaks from forgotten unsubscribes; handlers cleaned automatically.

---

## 4. Technologies and Tools

### 4.1 Programming Language

- **Python 3.12 (LTS)**
  - Modern async/await syntax
  - Type hints support (PEP 585, 604)
  - Performance improvements over 3.11
  - Long-term support until October 2028

### 4.2 Core Libraries

#### System Integration

- **pystray** (0.19.5): System tray icon management
  - Cross-platform tray integration
  - Context menu handling
  - Icon state management
  - Runs in isolated thread to prevent blocking

- **pynput** (1.8.1): Global hotkey and input monitoring
  - Low-level input detection
  - Global hotkey registration
  - Cross-platform compatibility
  - Thread-based event delivery

- **psutil** (7.1.0): System resource monitoring
  - Process information
  - System resource usage tracking
  - Single instance detection
  - Platform-specific system access

#### Image & Media Processing

- **Pillow (PIL)** (11.3.0): Image capture and manipulation
  - Screenshot capture via ImageGrab
  - Image format conversion
  - Thumbnail generation
  - Metadata extraction

#### UI Framework

- **PyQt6** (6.9.1): Modern desktop UI framework
  - Cross-platform GUI development
  - Widget-based interface
  - Signal/slot mechanism
  - Dark theme support
  - Integrates with asyncio event loop

#### AI Integration

- **ollama** (0.6.0): Local AI model interaction
  - RESTful client for Ollama server
  - Model management and selection
  - Streaming response support
  - Health monitoring and connection handling

#### Database

- **SQLite3** (built-in): Local database backend
  - Serverless embedded database
  - ACID transactions
  - Schema versioning and migrations
  - File-based persistence in user's AppData directory

#### Async I/O

- **asyncio** (built-in): Asynchronous programming framework
  - Event loop and task management
  - Coroutines and async/await
  - Thread-safe operations (call_soon_threadsafe)
  - Synchronization primitives (Event, Lock, Queue)

- **aiofiles** (25.1.0): Async file operations
  - Non-blocking file I/O
  - Compatible with asyncio
  - Prevents blocking the event loop

### 4.3 Development & Build Tools

#### Development Dependencies (requirements-dev.txt)

- **pytest**: Testing framework with async support
- **black**: Code formatter (PEP 8 compliance)
- **mypy**: Static type checking (PEP 484)
- **pylint**: Code linting and analysis
- **coverage**: Code coverage measurement

#### Deployment

- **PyInstaller**: Single executable packaging
  - Creates standalone .exe on Windows
  - Bundles Python runtime and dependencies
  - Supports windowed and console applications
  - Icon embedding for branding

### 4.4 System Dependencies

#### Windows-Specific

- **winreg**: Windows Registry access (built-in)
  - Auto-start registry key modification
  - Application Registry settings storage
  - No external dependency required

- **msvcrt**: Windows C Runtime library (built-in)
  - File locking for single-instance detection
  - Platform-specific optimizations

#### Cross-Platform Considerations

- **XDG Base Directory Specification** (Linux): Respects standard directory structure
- **macOS App Bundle**: Compatibility layer for macOS
- **Windows Registry**: Primary Windows integration point

---

## 5. Code Quality and Modularity

### 5.1 Separation of Concerns

The project strictly adheres to separation of concerns through layered architecture:

#### Model Layer Isolation
- Models contain only data and business logic
- No UI rendering or framework-specific code
- Testable in isolation with mock dependencies
- Clear, well-defined public interfaces

#### View Layer Isolation
- Views contain only presentation logic
- No business logic or data processing
- Communicate through EventBus, not direct calls
- Can be tested with mock data and events

#### Controller Layer Isolation
- Controllers coordinate without maintaining state
- Delegate all operations to Models and Views
- Route all communication through EventBus
- Minimal business logic implementation

### 5.2 Modularity and Reusability

#### Module Organization

```
src/
├── models/              # Data access and business logic
│   ├── screenshot_manager.py      # Screenshot operations (770+ lines)
│   ├── database_manager.py        # SQLite persistence (1070+ lines)
│   ├── settings_manager.py        # Configuration management (620+ lines)
│   ├── ollama_client.py           # AI integration (800+ lines)
│   ├── database_schema_migration.py  # Schema versioning
│   ├── screenshot_models.py       # Data structures
│   └── preset_models.py           # Prompt preset definitions

├── views/              # UI presentation layer
│   ├── tray_manager.py            # System tray integration (590+ lines)
│   ├── ui_manager.py              # PyQt6 management
│   ├── gallery_window.py          # Screenshot gallery interface
│   ├── overlay_window.py          # Screenshot overlay
│   ├── settings_window.py         # Configuration UI
│   └── overlay_manager.py         # Overlay state management

├── controllers/        # Business logic coordination
│   ├── event_bus.py               # Pub-sub system (550+ lines)
│   ├── main_controller.py         # Application orchestration (640+ lines)
│   └── hotkey_handler.py          # Hotkey management (1210+ lines)

└── utils/             # Reusable utilities
    ├── logging_config.py          # Structured logging setup
    ├── icon_manager.py            # Icon generation and management
    ├── auto_start.py              # Windows startup integration
    └── style_loader.py            # UI theme management
```

#### Component Independence

Each component can be:
- **Independently initialized**: Components don't require others at creation
- **Independently tested**: Mock dependencies provide isolation
- **Independently replaced**: Interfaces allow alternative implementations
- **Independently configured**: Settings don't couple components

### 5.3 Coding Standards

#### Type Hints

All public methods include type hints for clarity and type checking:

```python
async def capture_screenshot(region: Optional[tuple] = None) -> ScreenshotResult:
async def emit(event_type: str, data: Any = None) -> None:
def subscribe(event_type: str, handler: Callable, priority: int = 0) -> str:
```

#### Documentation

- **Module docstrings**: Describe purpose and responsibilities
- **Class docstrings**: Explain design and public interface
- **Method docstrings**: Document parameters, returns, and exceptions
- **Inline comments**: Clarify complex logic and decisions

#### Naming Conventions

- **Classes**: PascalCase with descriptive names (`ScreenshotManager`, `EventBus`)
- **Functions/Methods**: snake_case with action verbs (`capture_screenshot`, `emit_event`)
- **Constants**: UPPER_SNAKE_CASE for module-level constants
- **Private members**: Leading underscore for internal implementation (`_subscribers`, `_shutdown_requested`)

#### Code Formatting

- **Black**: Automatic code formatting with 88-character line limit
- **PEP 8**: Standard Python style guide adherence
- **Import organization**: Standard library → third-party → local imports
- **Spacing**: 2 blank lines between top-level definitions

### 5.4 Testing Infrastructure

#### Test Structure

```
tests/
├── test_event_bus.py           # EventBus pub-sub functionality
├── test_hotkey_handler.py      # Hotkey registration and threading
├── test_database_and_settings.py  # Database and config operations
```

#### Testing Approach

- **Unit Tests**: Test components in isolation with mocks
- **Async Testing**: pytest-asyncio for coroutine testing
- **Mock Objects**: Replace external dependencies
- **Fixtures**: Reusable test data and component instances

### 5.5 Error Handling and Logging

#### Structured Logging

- **Multiple output formats**: Console (readable) and JSON (machine-parseable)
- **Log rotation**: Automatic file rotation by size and count
- **Privacy filtering**: Automatic sanitization of sensitive paths and usernames
- **Performance tracking**: Log event processing times and system resource usage

#### Exception Hierarchy

Custom exceptions provide granular error handling:

```python
# EventBus exceptions
EventBusError (base)
├── EventHandlerError
└── EventQueueError

# Database exceptions
DatabaseError (base)
├── SchemaError
└── ConnectionError

# Ollama exceptions
OllamaError (base)
├── ConnectionError
├── ModelError
└── ImageProcessingError

# Screenshot exceptions
ScreenshotError (base)
├── CaptureError
├── SaveError
└── DirectoryError
```

#### Error Recovery

- **Transient errors**: Automatic retry with exponential backoff
- **Connection failures**: Offline mode fallback for Ollama
- **File system issues**: Graceful fallback to alternative directories
- **Configuration corruption**: Reset to defaults with user notification

---

## 6. OOP Principles

### 6.1 Encapsulation

#### Data Hiding

All internal state is private, accessible only through controlled interfaces:

```python
class EventBus:
    def __init__(self):
        self._subscribers: Dict[str, List[EventSubscription]] = {}  # Private
        self._event_queue: deque = deque()                          # Private
        self._shutdown_requested: bool = False                      # Private

    # Public interface provides controlled access
    async def subscribe(self, event_type: str, handler: Callable):
        """Public method with validation and type checking"""

    async def emit(self, event_type: str, data: Any = None):
        """Public method with queue management and metrics"""
```

#### Immutable Data Structures

Dataclasses define immutable configuration and event data:

```python
@dataclass
class EventData:
    event_type: str
    data: Any = None
    timestamp: float = field(default_factory=time.time)
    source: Optional[str] = None
    correlation_id: Optional[str] = None
```

### 6.2 Inheritance

#### Base Classes and Abstraction

Inheritance provides code reuse and polymorphism:

```python
# Abstract base for all managers
class BaseManager:
    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger(__name__)
        self._initialized = False

    async def initialize(self) -> bool:
        """Template method for initialization"""
        raise NotImplementedError

# Concrete implementations
class ScreenshotManager(BaseManager):
    async def initialize(self) -> bool:
        """Screenshot-specific initialization"""

class DatabaseManager(BaseManager):
    async def initialize(self) -> bool:
        """Database-specific initialization"""
```

#### Mixin Classes

Optional mixins provide functionality combinations:

```python
class CacheableMixin:
    """Provides caching functionality to any manager"""
    def __init__(self, cache_size=100):
        self._cache = LRUCache(maxsize=cache_size)

class LoggableMixin:
    """Provides enhanced logging to any component"""
    def log_operation(self, operation, duration):
        self.logger.info(f"{operation} completed in {duration}ms")
```

### 6.3 Polymorphism

#### Method Overriding

Subclasses override base implementations:

```python
class EventSubscription:
    def __init__(self, handler, priority=0):
        self.handler = handler
        self.priority = priority

# Different handler types implement same interface
async def handle_screenshot_event(event_data: EventData):
    """Async handler"""

def handle_settings_event(event_data: EventData):
    """Sync handler - EventBus checks asyncio.iscoroutinefunction()"""

# Both work with EventBus.emit() through polymorphism
```

#### Interface-Based Design

Components depend on interfaces, not concrete types:

```python
class MainController:
    def __init__(
        self,
        event_bus: EventBus,  # Interface type, not implementation
        settings_manager: SettingsManager,  # Abstract interface
        database_manager: Optional[DatabaseManager] = None,
    ):
        """Components accept interfaces for flexibility"""
```

### 6.4 Abstraction

#### Hiding Implementation Details

Only essential behavior is exposed; implementation details are hidden:

```python
class ScreenshotManager:
    # Internal implementation details hidden
    async def _capture_with_pil(self, region: Optional[tuple]) -> PILImage:
        """Private method - not part of public interface"""

    async def _apply_compression(self, image: PILImage) -> bytes:
        """Private method - compression strategy hidden"""

    # Public interface abstracts complexity
    async def capture_screenshot(self, region: Optional[tuple] = None) -> ScreenshotResult:
        """Simple public interface hiding PIL, compression, metadata registration"""
        image = await self._capture_with_pil(region)
        compressed = await self._apply_compression(image)
        result = await self._save_and_register(compressed)
        return result
```

#### Design by Contract

Methods define clear contracts with preconditions and postconditions:

```python
class DatabaseManager:
    async def create_screenshot(self, screenshot: ScreenshotMetadata) -> int:
        """
        Create screenshot record in database.

        Preconditions:
            - Database initialized (call initialize_database first)
            - screenshot.path must point to valid file
            - screenshot.filename must be unique

        Postconditions:
            - Returns valid screenshot ID (>0)
            - Record persisted to database
            - Thumbnail registered if available

        Raises:
            - ValueError: If screenshot data invalid
            - DatabaseError: If database operation fails
        """
```

---

## 7. Key Features and Functionalities

### 7.1 Core Features

#### 1. System Tray Integration
- Clean, responsive tray icon with state indicators
- Context menu with quick actions:
  - Take Screenshot
  - Show Gallery
  - Toggle Overlay
  - Open Settings
  - Exit Application
- Dynamic icon updates reflecting application state
- Tooltip showing application status

#### 2. Global Hotkey Support
- Configurable keyboard shortcuts for instant access
- Default hotkeys:
  - `Ctrl+Shift+S`: Capture screenshot
  - `Ctrl+Shift+O`: Toggle overlay
  - `Ctrl+Shift+P`: Open settings
- Conflict detection and resolution
- Dynamic hotkey reconfiguration
- Thread-safe event handling

#### 3. Screenshot Capture
- **Full-screen capture**: Entire monitor or multiple monitors
- **Region selection**: User-defined rectangular regions
- **Atomic operations**: Ensures complete save or rollback
- **Metadata tracking**: Timestamp, dimensions, file size
- **Thumbnail generation**: Fast preview loading
- **Multi-monitor support**: Seamless capture across displays

#### 4. AI-Powered Analysis
- **Local model integration**: Ollama server connection
- **Model selection**: Multiple AI model support (llama, gemma, mistral, etc.)
- **Streaming responses**: Real-time response generation
- **Offline fallback**: Graceful degradation when server unavailable
- **Health monitoring**: Automatic server availability checks
- **Custom prompts**: User-defined analysis prompts

#### 5. Screenshot Gallery
- **Thumbnail browser**: Fast scrolling through many screenshots
- **Chat interface**: Interactive AI conversation per screenshot
- **Preset management**: Quick analysis templates
- **Search and filter**: Find screenshots by date, content, tags
- **Export capabilities**: Save analysis results
- **Auto-cleanup**: Configurable retention policies

#### 6. Configuration Management
- **Settings window**: UI-based configuration interface
- **Database persistence**: Settings survive application restarts
- **Validation framework**: Type-safe configuration values
- **Change notifications**: Components subscribe to setting updates
- **Default values**: Sensible defaults for all settings

#### 7. Auto-Start Support
- **Windows Registry integration**: Registry-based startup configuration
- **Startup Folder support**: Alternative startup method
- **Automatic method selection**: Chooses best available method
- **Delayed startup**: Optional startup delay for system stability
- **Minimized mode**: Starts hidden in system tray
- **Permission handling**: Graceful fallback if admin privileges unavailable

### 7.2 Unique and Critical Aspects

#### Event-Driven Architecture
Unlike monolithic screenshot tools, ExplainShot uses event-driven communication enabling:
- **Loose coupling**: Components don't depend on each other
- **Runtime extensibility**: New features added via event subscribers
- **Testing simplicity**: Mock EventBus enables component testing
- **Debug visibility**: Event history provides audit trail

#### Thread-Safe Hotkey Integration
Bridges pynput's thread-based callbacks to asyncio's cooperative scheduling:
- **No UI blocking**: Hotkey detection runs in dedicated thread
- **Asyncio integration**: Events route to main event loop
- **Graceful fallback**: Hotkey failure doesn't crash application
- **Dynamic reconfiguration**: Hotkeys updated without restart

#### Async-First Design
All I/O operations are non-blocking:
- **Database operations**: Async SQLite wrapper
- **File I/O**: Async file operations for screenshots
- **Network requests**: Async Ollama client
- **UI updates**: Non-blocking window rendering
- **Result**: Responsive UI with fast hotkey response (<50ms)

#### Privacy-Centric Architecture
- **Local processing only**: Screenshots never leave user's machine by default
- **Ollama integration**: AI runs locally without cloud services
- **Log filtering**: Automatic privacy filtering of sensitive paths
- **Configurable retention**: User controls screenshot deletion

---

## 8. Dependencies and Integrations

### 8.1 External Dependencies

#### Direct Dependencies

| Package | Version | Purpose | Integration Point |
|---------|---------|---------|------------------|
| pystray | 0.19.5 | System tray management | TrayManager creates pystray.Icon |
| pynput | 1.8.1 | Global hotkey detection | HotkeyHandler registers keyboard listeners |
| Pillow | 11.3.0 | Screenshot capture | ScreenshotManager.capture_screenshot() |
| PyQt6 | 6.9.1 | UI framework | UIManager, all window classes |
| ollama | 0.6.0 | AI model interaction | OllamaClient sends requests |
| psutil | 7.1.0 | System monitoring | Single instance detection, resource tracking |
| aiofiles | 25.1.0 | Async file I/O | ScreenshotManager file operations |

#### Built-In Dependencies

- **asyncio**: Asynchronous event loop and coordination
- **sqlite3**: Database engine
- **logging**: Structured logging system
- **pathlib**: Cross-platform file path handling
- **json**: Settings serialization
- **dataclasses**: Type-safe data structures

### 8.2 Ollama Integration

#### Server Architecture

```
ExplainShot Application
    ↓
OllamaClient (async client)
    ↓
Ollama Server (localhost:11434)
    ↓
Local AI Models (llama, gemma, mistral, etc.)
    ↓
GPU/CPU Resources
```

#### Integration Details

- **Protocol**: HTTP RESTful API
- **Default URL**: `http://localhost:11434`
- **Health Check**: Periodic connection validation
- **Model Management**: Automatic model list retrieval
- **Image Encoding**: Base64 for image transmission
- **Response Handling**: Streaming and buffered responses
- **Fallback**: Offline mode with retry logic

#### Configuration

```python
OllamaConfig:
    server_url: str = "http://localhost:11434"
    default_model: str = "gemma2:9b"
    timeout_seconds: int = 30
    max_retries: int = 3
    enable_streaming: bool = False
```

### 8.3 Database Integration

#### SQLite Architecture

```
Application
    ↓
DatabaseManager (async wrapper)
    ↓
aiosqlite (async SQLite)
    ↓
SQLite3 Database File
    ↓
User's AppData Directory
```

#### Database Schema

```
screenshots
├── id (INTEGER PRIMARY KEY)
├── filename (TEXT)
├── path (TEXT UNIQUE)
├── timestamp (DATETIME)
├── file_size (INTEGER)
├── thumbnail_path (TEXT)
└── metadata (TEXT JSON)

chat_history
├── id (INTEGER PRIMARY KEY)
├── screenshot_id (FOREIGN KEY)
├── prompt (TEXT)
├── response (TEXT)
├── timestamp (DATETIME)
├── model_name (TEXT)
└── processing_time (REAL)

presets
├── id (INTEGER PRIMARY KEY)
├── name (TEXT UNIQUE)
├── prompt (TEXT)
├── description (TEXT)
├── category (TEXT)
├── tags (TEXT JSON)
├── usage_count (INTEGER)
└── is_favorite (BOOLEAN)

settings
├── id (INTEGER PRIMARY KEY)
├── key (TEXT UNIQUE)
├── value (TEXT JSON)
└── updated_at (DATETIME)

migrations
├── version (INTEGER PRIMARY KEY)
├── name (TEXT)
└── applied_at (DATETIME)
```

### 8.4 Windows Registry Integration

#### Auto-Start Configuration

```
Registry Path:
HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run

Entry:
Name: ExplainShot
Value: C:\Users\[User]\AppData\Local\[Path]\explain-shot.exe --minimized
```

#### Auto-Start Modes

1. **Registry Method** (Primary):
   - Direct registry modification
   - Requires no elevated privileges
   - Works on all Windows versions

2. **Startup Folder Method** (Fallback):
   - Shortcut in Startup folder
   - Alternative if registry unavailable
   - Path: `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`

---

## 9. Scalability and Performance Considerations

### 9.1 Performance Optimization Strategies

#### Memory Management

**Target**: <50MB resident memory when idle

- **Lazy Loading**: Components initialized only when needed
- **Image Cleanup**: PIL Image objects released immediately after processing
- **Cache Management**: LRU caches prevent unbounded growth
- **Weak References**: EventBus subscriptions don't prevent garbage collection
- **Connection Pooling**: Database connections reused, not recreated

#### CPU Optimization

**Target**: <0.1% CPU usage when idle

- **Event-Driven**: No polling loops, event-driven instead
- **Async I/O**: Non-blocking operations prevent spinning
- **Thread Isolation**: Hotkey monitoring in dedicated thread
- **Efficient Queuing**: Priority queues process events in optimal order
- **Background Tasks**: Long operations don't block main thread

#### Startup Performance

**Target**: <2 seconds to tray visibility

- **Sequential Initialization**: Components initialized in dependency order
- **Parallel Where Possible**: Non-dependent components init together
- **Deferred Loading**: UI windows created on-demand
- **Cached Icons**: Icon manager caches generated icons
- **Minimal Imports**: Core modules import only needed dependencies

#### Screenshot Capture

**Optimization**: Minimize capture latency for responsive experience

```python
# Efficient capture chain
PIL.ImageGrab.grab()        # Fast native screenshot
└─ PIL compress + encode    # Hardware acceleration where available
   └─ Atomic file save      # Single write operation
      └─ Database register  # Fast INSERT with indexed lookup
```

### 9.2 Scalability Considerations

#### Large Screenshot Collections

Designed to handle thousands of screenshots efficiently:

- **Indexed Database**: Fast queries on timestamp, filename, tags
- **Pagination**: Gallery loads 50-100 screenshots at a time
- **Thumbnail Caching**: Generated once, cached on disk
- **Efficient Search**: Full-text search on indexed fields
- **Auto-Cleanup**: Automatic deletion of old screenshots

#### Multiple AI Models

Supports multiple Ollama models simultaneously:

- **Model Selection**: Dynamic model selection at request time
- **Concurrent Requests**: Multiple analysis requests queued
- **Response Caching**: Analysis results stored in database
- **Fallback Handling**: Model unavailability doesn't crash app

#### Extended Running

Application designed for continuous background operation:

- **Memory Leak Prevention**: Weak references, event cleanup
- **Connection Stability**: Reconnection logic for Ollama and database
- **Log Rotation**: Logs don't grow unbounded
- **Resource Cleanup**: Periodic cache clearing, old file deletion
- **Graceful Shutdown**: Proper cleanup sequence on exit

### 9.3 Performance Monitoring

#### Built-In Metrics

EventBus tracks comprehensive metrics:

```python
metrics = {
    'events_emitted': int,          # Total events sent
    'events_processed': int,        # Total events handled
    'handlers_called': int,         # Total handler invocations
    'handler_errors': int,          # Failed handlers
    'queue_overflows': int,         # Dropped events due to full queue
    'queue_size': int,              # Current queued events
    'subscription_counts': dict,    # Per-event-type subscriptions
    'total_event_types': int        # Unique event types
}
```

#### Logging with Timestamps

All operations logged with duration tracking:

```python
logger.info("Screenshot captured in %.2fms", capture_time_ms)
logger.info("AI response received in %.2fs", processing_time_s)
logger.debug("Database operation completed: %s", operation_duration_ms)
```

---

## 10. Development Guidelines

### 10.1 Contributing Principles

#### Code Organization

1. **Respect MVC Separation**:
   - Business logic belongs in Models
   - UI rendering belongs in Views
   - Coordination belongs in Controllers
   - Never mix layers

2. **Use the EventBus**:
   - Emit events for state changes
   - Subscribe to relevant events
   - Never call components directly
   - Maintain loose coupling

3. **Maintain Type Safety**:
   - Add type hints to all functions
   - Use type checking with mypy
   - Document parameter and return types
   - Use dataclasses for structured data

4. **Follow Async Patterns**:
   - Use `async def` for I/O operations
   - Await all coroutines
   - Never block the event loop
   - Use `await asyncio.sleep(0)` to yield control

#### Code Style

1. **Format with Black**:
   ```bash
   black src/
   ```

2. **Type Check with Mypy**:
   ```bash
   mypy src/
   ```

3. **Lint with Pylint**:
   ```bash
   pylint src/
   ```

4. **Docstring Format**:
   ```python
   async def example_function(param1: str, param2: Optional[int] = None) -> bool:
       """
       Brief description of function purpose.

       Detailed explanation if needed, including algorithm notes or
       implementation details relevant to maintainability.

       Args:
           param1: Description of param1
           param2: Description of param2, defaults to None

       Returns:
           True if successful, False otherwise

       Raises:
           ValueError: If param1 is empty
           DatabaseError: If database operation fails

       Example:
           >>> result = await example_function("test", 42)
           >>> print(result)
           True
       """
   ```

### 10.2 Adding New Features

#### Step 1: Plan Architecture

Ask these questions before coding:

1. What data is needed? → Design Model additions
2. How does user interact? → Design View additions
3. What events are emitted/received? → Design EventBus events
4. How is it tested? → Write tests first

#### Step 2: Implement Model Layer

```python
# src/models/new_feature_manager.py
class NewFeatureManager:
    """Manages new feature operations."""

    async def initialize(self) -> bool:
        """Initialize the manager."""

    async def perform_operation(self, param: str) -> Result:
        """Perform the operation."""

    async def shutdown(self) -> None:
        """Clean up resources."""
```

#### Step 3: Add EventBus Events

```python
# src/__init__.py - EventTypes class
class EventTypes:
    NEW_FEATURE_OPERATION = "new_feature.operation"
    NEW_FEATURE_COMPLETED = "new_feature.completed"
```

#### Step 4: Implement View Layer

```python
# src/views/new_feature_window.py
class NewFeatureWindow:
    """View for new feature UI."""

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self._setup_ui()
        self._subscribe_to_events()

    async def _on_button_clicked(self):
        """Handle user interaction."""
        await self.event_bus.emit(EventTypes.NEW_FEATURE_OPERATION)
```

#### Step 5: Integrate in MainController

```python
# src/controllers/main_controller.py
class MainController:
    async def initialize(self) -> bool:
        # ... existing code ...
        self.new_feature_manager = NewFeatureManager(...)
        await self.event_bus.subscribe(
            EventTypes.NEW_FEATURE_OPERATION,
            self._handle_new_feature
        )

    async def _handle_new_feature(self, event_data):
        """Handle new feature event."""
        result = await self.new_feature_manager.perform_operation(...)
        await self.event_bus.emit(
            EventTypes.NEW_FEATURE_COMPLETED,
            {"result": result}
        )
```

#### Step 6: Write Tests

```python
# tests/test_new_feature.py
@pytest.mark.asyncio
async def test_new_feature_operation():
    """Test new feature operation."""
    event_bus = EventBus()
    manager = NewFeatureManager(event_bus=event_bus)

    result = await manager.perform_operation("test")
    assert result.success
```

### 10.3 Debugging Practices

#### Enable Debug Logging

```bash
python main.py --debug
python main.py --log-level DEBUG
```

#### Access Event History

```python
# In code or interactive shell
event_bus = get_event_bus()
history = await event_bus.get_event_history(limit=100)
for event in history:
    print(f"{event.event_type}: {event.data}")
```

#### Monitor Metrics

```python
metrics = await event_bus.get_metrics()
print(f"Events emitted: {metrics['events_emitted']}")
print(f"Handlers called: {metrics['handlers_called']}")
print(f"Handler errors: {metrics['handler_errors']}")
```

#### Check Thread State

```python
import threading
print(f"Active threads: {threading.enumerate()}")
print(f"Current thread: {threading.current_thread().name}")
```

### 10.4 Performance Profiling

#### Memory Profiling

```bash
pip install memory-profiler
python -m memory_profiler main.py
```

#### CPU Profiling

```bash
python -m cProfile -s cumtime main.py
```

#### Event Bus Analysis

```python
# Log EventBus metrics periodically
async def monitor_event_bus():
    while True:
        metrics = await event_bus.get_metrics()
        logger.info("EventBus: %s", metrics)
        await asyncio.sleep(60)

asyncio.create_task(monitor_event_bus())
```

### 10.5 Deployment and Build

#### Development Execution

```bash
# Standard execution
python main.py

# With debug logging
python main.py --debug --log-level DEBUG

# With custom log directory
python main.py --log-dir ./logs
```

#### PyInstaller Build

```bash
# Create single executable
pyinstaller --windowed --onefile --icon=resources/icons/app.ico main.py

# Output: dist/explain-shot.exe
```

#### Distribution

The built executable can be:
- Placed on user's machine manually
- Distributed via installer
- Copied to removable media
- Shared with minimum installation friction

### 10.6 Best Practices Summary

| Practice | Why | Example |
|----------|-----|---------|
| Always use async/await | Non-blocking operations | `await database_manager.get_screenshots()` |
| Emit events for changes | Loose coupling | `await event_bus.emit(SETTINGS_CHANGED, {...})` |
| Handle exceptions properly | Graceful degradation | Try-except with proper error events |
| Clean up resources | Prevent memory leaks | Unsubscribe, close files, shutdown components |
| Log important operations | Debugging and auditing | `logger.info("Operation completed")` |
| Type hint everything | Clarity and type checking | `async def func(x: str) -> bool:` |
| Write tests first | Ensure correctness | Create test before implementation |
| Document interfaces | Developer onboarding | Complete docstrings for public methods |
| Validate inputs | Security and stability | Check types and ranges before processing |
| Isolate errors | System resilience | Catch errors per handler, emit error events |

---

## Conclusion

ExplainShot demonstrates professional-grade desktop application architecture by:

1. **Strict MVC adherence**: Clear separation of models, views, and controllers
2. **Event-driven design**: Loose coupling through centralized EventBus
3. **Async-first approach**: Non-blocking operations throughout
4. **Comprehensive error handling**: Graceful degradation and recovery
5. **Extensive logging**: Structured logging with privacy protection
6. **Type safety**: Full type hints and mypy validation
7. **Testability**: Modular design enables unit and integration testing
8. **Performance optimization**: Memory-efficient, responsive architecture
9. **Extensibility**: Well-defined patterns for adding new features
10. **Production readiness**: Built for continuous background operation

This foundation enables rapid feature development while maintaining code quality, stability, and maintainability across the entire codebase.

---

**Document Version**: 1.0
**Last Updated**: October 18, 2025
**Target Audience**: AI Agents, Developers, Technical Leads
**Scope**: Complete Project Context and Architecture Reference
