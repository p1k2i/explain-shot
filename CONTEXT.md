# ExplainShot - Project Context & Architecture Documentation

**Version:** 0.1.1
**Language:** Python 3.12
**Architecture Pattern:** MVC (Model-View-Controller) with Event-Driven Architecture
**Last Updated:** October 2025

---

## 1. Project Overview

### Purpose and Goals

**ExplainShot** is a lightweight, cross-platform desktop application designed to capture screenshots and explain them using artificial intelligence. The application integrates with local AI models (via Ollama) to provide intelligent analysis and explanations of captured screen content.

**Primary Goals:**
- Provide seamless screenshot capture with minimal user friction
- Enable AI-powered analysis of screen content through local inference
- Maintain a small resource footprint suitable for continuous background operation
- Deliver a responsive, modern user interface with dark theme support
- Support Windows startup integration for automatic launch

### Key Characteristics

- **Background Process**: Runs as a daemon-like service with minimal system impact
- **Privacy-First**: All processing occurs locally; no cloud integration
- **Event-Driven**: Loose coupling between modules through asynchronous event distribution
- **Cross-Platform Design**: Architecture supports Linux and macOS with Windows as primary target
- **Modular Architecture**: Clear separation of concerns following MVC pattern

---

## 2. Architecture

### 2.1 Overall Structure

The application follows a **three-layer MVC architecture** enhanced with an **event-driven** pattern for inter-component communication:

```
┌─────────────────────────────────────────────────────────────┐
│                    Application Entry Point                  │
│                        (main.py)                            │
└────────────────────────┬────────────────────────────────────┘
                         │
        ┌────────────────┼────────────────┐
        │                │                │
    ┌───▼────┐   ┌──────▼──────┐   ┌───▼────┐
    │ Models │   │ Controllers │   │  Views │
    │ (Data) │   │(Logic/Coord)│   │  (UI)  │
    └───┬────┘   └──────┬──────┘   └───┬────┘
        │                │              │
        └────────────────┼──────────────┘
                         │
                 ┌───────▼────────┐
                 │   EventBus     │
                 │ (Communication)│
                 └────────────────┘
```

### 2.2 Component Layers

#### **Model Layer** (Data & Business Logic)
Manages data persistence, configuration, and business rules:

- **`DatabaseManager`**: SQLite database operations for screenshots, chat history, presets, and metadata
- **`SettingsManager`**: Application configuration management with validation and persistence
- **`ScreenshotManager`**: Screenshot capture, file storage, and metadata management
- **`OllamaClient`**: Integration with local Ollama AI server for model inference
- **`ThumbnailManager`**: Image thumbnail generation and optimization
- **`StorageManager`**: Disk space management and file lifecycle

**Responsibilities:**
- Data validation and transformation
- Database schema management and migrations
- Configuration persistence and retrieval
- Business rule enforcement
- Integration with external services (Ollama)

#### **Controller Layer** (Application Logic & Orchestration)
Coordinates between models and views:

- **`MainController`**: Central application orchestrator managing initialization and shutdown
- **`EventBus`**: Asynchronous event distribution system enabling loose coupling
- **`HotkeyHandler`**: Global keyboard hotkey registration and monitoring

**Responsibilities:**
- Event subscription and emission
- Component lifecycle management
- Business process orchestration
- Cross-layer communication coordination
- Error recovery and fallback handling

#### **View Layer** (User Interface)
Manages all UI presentation and user interaction:

- **`TrayManager`**: System tray icon integration using pystray
- **`UIManager`**: Central PyQt6 window lifecycle coordinator
- **`OverlayManager`**: Transparent overlay window management
- **`SettingsWindow`**: Settings/preferences UI interface
- **`GalleryWindow`**: Screenshot gallery and chat interface
- **`CustomTitleBar`**: Custom window title bar implementation

**Responsibilities:**
- UI rendering and state display
- User input handling
- Window lifecycle management
- Event emission based on user actions
- Theme and style management

### 2.3 Communication Pattern: Event-Driven Architecture

All inter-component communication flows through the **EventBus**, a central publish-subscribe system:

**Key Benefits:**
- **Loose Coupling**: Components don't need direct references to each other
- **Async-First**: Non-blocking event processing using asyncio
- **Scalability**: New event handlers can be added without modifying source components
- **Testability**: Components can be tested in isolation by mocking events

**Event Flow Example:**
```
User clicks "Take Screenshot" in Tray Menu
    ↓
TrayManager emits: SCREENSHOT_CAPTURE_REQUESTED
    ↓
EventBus routes event to MainController
    ↓
MainController calls ScreenshotManager.capture()
    ↓
ScreenshotManager emits: SCREENSHOT_CAPTURED
    ↓
UIManager receives event and shows Gallery
    ↓
OllamaClient receives event and starts analysis
    ↓
OllamaClient emits: OLLAMA_RESPONSE_RECEIVED
    ↓
UIManager displays result in Gallery
```

### 2.4 Initialization Sequence

1. **Application instantiation** - Create Application instance with all components
2. **EventBus initialization** - Setup central event distribution system
3. **Database initialization** - Create schema if needed, open connection pool
4. **SettingsManager initialization** - Load or create default settings
5. **Model components initialization** - ScreenshotManager, OllamaClient, etc.
6. **UIManager initialization** - Create PyQt6 application and managers
7. **MainController initialization** - Setup hotkeys and event subscriptions
8. **Signal handler setup** - Register OS signal handlers for graceful shutdown
9. **Emit APP_READY event** - Signal that application is ready for operation

### 2.5 Shutdown Sequence

1. **Shutdown signal received** - OS signal or user-initiated shutdown
2. **APP_SHUTDOWN_STARTING event** - Notify all components
3. **MainController shutdown** - Disable hotkeys, cleanup tasks
4. **ScreenshotManager shutdown** - Cancel ongoing operations
5. **OllamaClient shutdown** - Cancel requests, close connections
6. **TrayManager shutdown** - Cleanup system tray icon
7. **SettingsManager shutdown** - Save configuration to database
8. **EventBus shutdown** - Complete pending events, cleanup resources
9. **Cleanup lock file** - Release exclusive lock for single-instance checking
10. **Force exit** - sys.exit(0) to ensure termination

---

## 3. Design Patterns

### 3.1 Singleton Pattern

**Application:** `EventBus`, `SettingsManager`, `DatabaseManager`

**Implementation:**
- Single instance created at application startup
- Shared reference passed to dependent components
- Thread-safe instance retrieval via getter functions

```python
# Example: get_event_bus() ensures single EventBus instance
event_bus = get_event_bus()  # Returns same instance every call
```

**Rationale:**
- Ensures single source of truth for configuration and events
- Prevents duplicate database connections
- Simplifies inter-component communication

### 3.2 Observer/Pub-Sub Pattern

**Application:** `EventBus` with multiple subscribers

**Implementation:**
- Components subscribe to specific event types
- When events occur, all subscribers are notified asynchronously
- Weak references prevent memory leaks from circular dependencies

```python
# Subscribe to event
sub_id = await event_bus.subscribe(
    EventTypes.SCREENSHOT_CAPTURED,
    handler_function
)

# Handler is called when event is emitted
await event_bus.emit(EventTypes.SCREENSHOT_CAPTURED, data={...})
```

**Rationale:**
- Enables loose coupling between modules
- Allows multiple handlers for single events
- Simplifies addition of new features without modifying existing code

### 3.3 Strategy Pattern

**Application:** `AutoStartManager` with multiple implementation strategies

**Implementation:**
- Different auto-start methods (Registry, Startup Folder, Auto-select)
- `AutoStartMethod` enum defines available strategies
- Runtime selection based on permissions and configuration

```python
# AutoStartManager automatically selects best method
success, method = await auto_start_manager.enable_auto_start()
# method might be REGISTRY or STARTUP_FOLDER depending on permissions
```

**Rationale:**
- Handles OS-specific startup requirements
- Gracefully degrades if one method fails
- Easy to add new startup methods

### 3.4 Factory Pattern

**Application:** Icon creation, window instantiation

**Implementation:**
- `IconManager` creates appropriate icons for different states
- `UIManager` creates window instances on demand
- Type-based creation based on configuration

**Rationale:**
- Centralizes object creation logic
- Encapsulates platform-specific implementations
- Simplifies complex object initialization

### 3.5 Adapter Pattern

**Application:** `OllamaClient` adapting Ollama library to application needs

**Implementation:**
- Wraps external Ollama library API
- Translates library methods to application interface
- Handles library-specific error handling and conversions

```python
# Application calls standardized interface
response = await ollama_client.analyze_image(image_path, prompt)

# OllamaClient adapts to Ollama library specifics internally
```

**Rationale:**
- Decouples application from external library implementation
- Centralized error handling and fallback logic
- Simplifies testing through mock adaptation

### 3.6 Repository Pattern

**Application:** `DatabaseManager`, `SettingsManager`

**Implementation:**
- Data access abstraction layer
- SQL queries encapsulated in manager classes
- Business logic doesn't directly access database

```python
# Business logic uses high-level interface
settings = await settings_manager.load_settings()

# Manager handles SQL operations internally
```

**Rationale:**
- Separates data access from business logic
- Enables easier database migrations
- Simplifies testing through mock repositories

### 3.7 Command Pattern

**Application:** Hotkey handling and user actions

**Implementation:**
- User actions encapsulated as commands (Take Screenshot, Open Settings, etc.)
- Commands can be queued, logged, or undone
- Decouples UI from business logic

**Rationale:**
- Enables action queuing and replay
- Simplifies undo/redo implementation
- Allows parameterized action execution

### 3.8 Template Method Pattern

**Application:** Async initialization and shutdown in multiple components

**Implementation:**
- Base initialization sequence defined in `MainController`
- Components implement specific initialization steps
- Framework handles ordering and error handling

**Rationale:**
- Ensures consistent initialization across components
- Reduces code duplication
- Makes it easier to add new components

---

## 4. Technologies and Tools

### 4.1 Core Technologies

| Technology | Version | Purpose | Role |
|-----------|---------|---------|------|
| **Python** | 3.12+ | Primary language | All components |
| **asyncio** | Built-in | Async event loop | Event processing, async operations |
| **SQLite** | Built-in | Database engine | Configuration, screenshots, chat history |

### 4.2 UI Framework

| Library | Version | Purpose |
|---------|---------|---------|
| **PyQt6** | 6.9.1 | GUI framework | Windows, dialogs, custom widgets |
| **pystray** | 0.19.5 | System tray | Background tray icon integration |
| **Pillow (PIL)** | 11.3.0 | Image processing | Screenshot capture, thumbnails, rendering |

### 4.3 System Integration

| Library | Version | Purpose |
|---------|---------|---------|
| **pynput** | 1.8.1 | Global hotkeys | Keyboard monitoring at OS level |
| **psutil** | 7.1.0 | System info | Process monitoring, system metrics |
| **winreg** | Built-in (Windows) | Registry access | Windows auto-start configuration |

### 4.4 AI Integration

| Library | Version | Purpose |
|---------|---------|---------|
| **ollama** | 0.6.0 | AI client | Local model inference |
| **base64** | Built-in | Encoding | Image encoding for AI transmission |

### 4.5 Development Tools

| Tool | Version | Purpose |
|------|---------|---------|
| **pytest** | Latest | Unit testing | Test execution and automation |
| **pytest-cov** | Latest | Coverage reporting | Code coverage analysis |
| **pytest-asyncio** | Latest | Async testing | Async test execution |
| **black** | Latest | Code formatting | PEP 8 compliance |
| **flake8** | Latest | Linting | Code quality checks |
| **mypy** | Latest | Type checking | Static type verification |
| **PyInstaller** | 6.16.0 | Executable generation | Windows .exe creation |

### 4.6 Async Framework Stack

**Async Processing Pipeline:**
```
asyncio Event Loop
    ↓
EventBus (async emitter/subscriber)
    ↓
Component Handlers (async/sync)
    ↓
Database Operations (async via sqlite3)
    ↓
External APIs (async via ollama client)
```

---

## 5. Code Quality and Modularity

### 5.1 Code Quality Standards

#### **Type Hints**
- Comprehensive type annotations on all function signatures
- Usage of `typing` module for complex types (Optional, Dict, List, Callable, etc.)
- Type aliases for clarity (e.g., `KeyboardListener`)
- Full support for static type checking with mypy

```python
async def emit(
    self,
    event_type: str,
    data: Optional[Dict[str, Any]] = None,
    source: Optional[str] = None
) -> bool:
    """Emit an event to all subscribers."""
    ...
```

#### **Documentation**
- Module-level docstrings explaining purpose and functionality
- Class docstrings describing role and responsibilities
- Method docstrings with Args, Returns, and Raises sections
- Inline comments for complex logic

```python
class EventBus:
    """
    Asynchronous event distribution system.

    Provides loose coupling between application modules through an event-driven
    architecture. Supports priority-based event handling, one-time subscriptions,
    weak references, and event queuing.
    """
```

#### **Error Handling**
- Custom exception hierarchy for different error types
- Contextual error information with appropriate logging
- Graceful fallbacks for non-critical failures
- Exponential backoff for retryable operations

```python
class DatabaseError(Exception):
    """Base exception for database operations."""
    pass

class ConnectionError(OllamaError):
    """Raised when connection to Ollama server fails."""
    pass
```

#### **Logging**
- Structured logging with privacy-aware filtering
- Different log levels for different severity
- JSON format for machine-readable logs
- Separate log files for components
- Log rotation and size limits

```python
logger = logging.getLogger(__name__)
logger.info("EventBus initialized with max_queue_size=%d", max_queue_size)
logger.error("Application initialization failed: %s", e)
```

#### **Validation**
- Input validation at component boundaries
- Configuration validation with defaults
- Database schema validation on startup
- File permission validation before operations

### 5.2 Modularity

#### **Clear Module Separation**

```
src/
├── models/              # Data layer - NO UI, NO UI frameworks
│   ├── database_manager.py
│   ├── settings_manager.py
│   ├── screenshot_manager.py
│   ├── ollama_client.py
│   ├── thumbnail_manager.py
│   └── storage_manager.py
│
├── controllers/         # Logic layer - NO UI frameworks
│   ├── event_bus.py
│   ├── main_controller.py
│   └── hotkey_handler.py
│
├── views/              # Presentation layer - UI only
│   ├── tray_manager.py
│   ├── ui_manager.py
│   ├── overlay_manager.py
│   ├── settings_window.py
│   └── gallery/
│       ├── gallery_window.py
│       └── components/
│
└── utils/              # Shared utilities
    ├── logging_config.py
    ├── auto_start.py
    ├── icon_manager.py
    └── style_loader.py
```

#### **Separation of Concerns**

- **Models** contain no UI framework imports (no PyQt6)
- **Views** are isolated UI components that receive data from models
- **Controllers** orchestrate models and views without implementing business logic
- **Utils** provide cross-cutting concerns

#### **Reusable Components**

- **StorageManager**: Generic file and disk management
- **OverlayManager**: Generic transparent window overlay
- **IconManager**: Centralized icon management and generation

#### **Dependency Injection**

Components receive dependencies through constructor parameters rather than creating them:

```python
class ScreenshotManager:
    def __init__(self, database_manager, settings_manager, event_bus):
        self.database_manager = database_manager
        self.settings_manager = settings_manager
        self.event_bus = event_bus
```

**Benefits:**
- Easy to test with mock dependencies
- Flexible component composition
- Eliminates circular dependencies

### 5.3 Testing Strategy

#### **Test Organization**
- Unit tests in `tests/` directory parallel to source
- Test files named `test_*.py` for pytest discovery
- Test modules follow component structure

#### **Test Coverage**
- Core logic components: EventBus, SettingsManager, DatabaseManager
- Event handling workflows
- Configuration validation
- Hotkey registration and handling

#### **Testing Approach**
- Async-aware testing with `pytest-asyncio`
- Mocking external dependencies
- Testing public interfaces, not implementation details
- Coverage reporting with pytest-cov

---

## 6. OOP Principles

### 6.1 Encapsulation

**Principle**: Bundle related data and behavior; hide internal implementation details.

**Application in ExplainShot:**

```python
# SettingsManager encapsulates all configuration logic
class SettingsManager:
    # Private attributes indicate internal state
    _database_manager: Optional[DatabaseManager]
    _settings_cache: Optional[ApplicationSettings]
    _dirty_flag: bool

    # Public interface for external access
    async def load_settings(self) -> ApplicationSettings:
        ...

    async def save_settings(self) -> bool:
        ...

    async def update_setting(self, key: str, value: Any) -> bool:
        ...
```

**Benefits:**
- Internal changes don't affect client code
- Validation happens at a single point
- Consistent state management

### 6.2 Inheritance

**Principle**: Derive specialized classes from general classes to promote code reuse.

**Application in ExplainShot:**

```python
# Exception hierarchy for specific error handling
class OllamaError(Exception):
    """Base exception for Ollama-related errors."""
    pass

class ConnectionError(OllamaError):
    """Raised when connection to Ollama server fails."""
    pass

class ModelError(OllamaError):
    """Raised when model-related operations fail."""
    pass

# Allows specific exception handling
try:
    await ollama_client.analyze_image(...)
except ConnectionError:
    # Handle connection specifically
    logger.warning("Ollama server connection failed")
except ModelError:
    # Handle model-specific errors
    logger.error("Model loading failed")
except OllamaError:
    # Catch all Ollama-related errors
    pass
```

**Dataclass Inheritance for Configuration:**
```python
# Base configuration class
@dataclass
class HotkeyConfig:
    screenshot_capture: str = "ctrl+shift+s"

# Specialized configurations inherit and extend
@dataclass
class ApplicationSettings:
    hotkeys: HotkeyConfig
    ui: UIConfig
    screenshot: ScreenshotConfig
```

### 6.3 Polymorphism

**Principle**: Objects of different types respond to the same interface.

**Application in ExplainShot:**

```python
# Different handler types respond to same subscription interface
async def async_handler(event_data):
    await process_event_async(event_data)

def sync_handler(event_data):
    process_event_sync(event_data)

# Both registered with same interface
sub1 = await event_bus.subscribe(EventTypes.SCREENSHOT_CAPTURED, async_handler)
sub2 = await event_bus.subscribe(EventTypes.SCREENSHOT_CAPTURED, sync_handler)

# EventBus handles both transparently
await event_bus.emit(EventTypes.SCREENSHOT_CAPTURED, data={...})
```

**Strategy Pattern Polymorphism:**
```python
# Different AutoStart strategies implement same interface
class AutoStartManager:
    async def enable_auto_start_via_registry(self) -> bool:
        # Registry implementation
        ...

    async def enable_auto_start_via_startup_folder(self) -> bool:
        # Startup folder implementation
        ...

    async def enable_auto_start(self) -> Tuple[bool, AutoStartMethod]:
        # Selects appropriate strategy based on environment
        ...
```

### 6.4 Abstraction

**Principle**: Hide complexity by exposing only relevant interfaces.

**Application in ExplainShot:**

```python
# ScreenshotManager abstracts complex capture process
class ScreenshotManager:
    # Public interface - simple, high-level
    async def capture_full_screen(self) -> ScreenshotResult:
        """Simple public interface hides complex implementation."""
        ...

    # Private implementation details - complex internal logic
    async def _validate_capture(self, image: PILImage) -> bool:
        """Private method - not part of public interface."""
        ...

    async def _apply_optimizations(self, image: PILImage) -> PILImage:
        """Private method - optimization details hidden."""
        ...
```

**Database Abstraction:**
```python
# High-level interface
screenshots = await database_manager.get_screenshots(limit=10)

# SQL complexity hidden
async def get_screenshots(self, limit: int = 10) -> List[ScreenshotMetadata]:
    async with self._get_connection() as conn:
        cursor = await conn.execute(
            "SELECT * FROM screenshots ORDER BY timestamp DESC LIMIT ?",
            (limit,)
        )
        rows = await cursor.fetchall()
        return [ScreenshotMetadata.from_db_row(row) for row in rows]
```

---

## 7. Key Features

### 7.1 Screenshot Capture

**Functionality:**
- Full-screen capture with pixel-perfect accuracy
- Region selection support for partial captures
- Atomic file operations preventing corruption
- Metadata extraction and storage
- Automatic thumbnail generation
- File format options (PNG, JPEG, WebP)

**Key Components:**
- `ScreenshotManager`: Core capture logic
- `ThumbnailManager`: Thumbnail optimization
- `DatabaseManager`: Metadata persistence

**Workflow:**
1. User triggers capture (hotkey or tray menu)
2. ScreenshotManager captures screen to memory
3. File saved atomically to disk
4. Metadata extracted and stored in database
5. Thumbnail generated asynchronously
6. Events emitted for UI updates
7. AI analysis initiated automatically

### 7.2 AI-Powered Screenshot Analysis

**Functionality:**
- Integration with local Ollama AI server
- Support for multiple AI models
- Streaming response handling
- Response caching to avoid redundant processing
- Offline fallback when server unavailable
- Model health monitoring

**Key Components:**
- `OllamaClient`: AI server integration
- `SettingsManager`: Model configuration

**Features:**
- **Model Flexibility**: Configure any Ollama-supported model
- **Prompt Templates**: Pre-built prompts with parameters
- **Streaming Responses**: Real-time AI output display
- **Error Recovery**: Automatic retry with exponential backoff

### 7.3 Screenshot Gallery

**Functionality:**
- Visual gallery of captured screenshots
- Chat interface for multi-turn conversations
- Preset prompts for common analysis tasks
- Screenshot metadata display
- Thumbnail-based browsing
- Integration with AI responses

**Key Components:**
- `GalleryWindow`: Main gallery UI
- `ChatInterface`: Chat conversation widget
- `PresetsPanel`: Preset management UI
- `ScreenshotsGallery`: Thumbnail gallery widget

**Features:**
- **Lazy Loading**: Thumbnails loaded on demand
- **Search and Filter**: Find screenshots by date, content
- **Favorite Management**: Mark important screenshots
- **Export Options**: Save conversations and screenshots
- **Responsive Design**: Adapts to window size

### 7.4 Global Hotkey System

**Functionality:**
- System-wide keyboard hotkey registration
- Background operation without window focus
- Conflict detection and resolution
- Dynamic hotkey reconfiguration
- Multiple hotkeys for different actions

**Key Components:**
- `HotkeyHandler`: Hotkey registration and monitoring
- Thread-safe event queue for inter-thread communication
- Pynput library for low-level keyboard access

**Default Hotkeys:**
- `Ctrl+Shift+S`: Capture screenshot
- `Ctrl+Shift+O`: Toggle overlay
- `Ctrl+Shift+P`: Open settings

### 7.5 System Tray Integration

**Functionality:**
- Background operation with tray icon
- Context menu with quick actions
- Icon state visualization (idle, capturing, processing, error)
- Minimize/restore functionality
- Single-instance checking

**Key Components:**
- `TrayManager`: Tray icon and menu management
- `IconManager`: Dynamic icon generation
- Application-level shutdown coordination

**Menu Options:**
- Take Screenshot
- Show Gallery
- Toggle Overlay
- Open Settings
- About
- Exit

### 7.6 Persistent Configuration

**Functionality:**
- SQLite-backed settings storage
- Type-safe configuration objects
- Validation with sensible defaults
- Auto-save on changes
- Migration support for schema evolution

**Key Components:**
- `SettingsManager`: Configuration management
- `DatabaseManager`: SQLite operations
- Dataclass-based configuration objects

**Configuration Sections:**
- **Hotkeys**: Global keyboard shortcuts
- **UI**: Theme, opacity, window behavior
- **Screenshot**: Format, quality, directory
- **Ollama**: Model selection, server URL, timeouts
- **AutoStart**: Startup behavior

### 7.7 Performance Optimization

**Storage Management:**
- Automatic cleanup of old files
- Disk space monitoring
- File count limits
- Configurable retention policies
- Archive support for long-term storage

### 7.8 Auto-Start Capability

**Functionality:**
- Automatic launch on Windows startup
- Multiple implementation methods (Registry, Startup Folder)
- Graceful degradation on permission failures
- Configurable startup delay
- Minimized startup mode

**Implementation Methods:**
1. **Registry Method**: Adds entry to `HKEY_CURRENT_USER\...\Run`
2. **Startup Folder**: Creates shortcut in Startup folder
3. **Automatic Selection**: Tries best method based on permissions

---

## 8. Dependencies and Integrations

### 8.1 External Dependencies

#### **System Libraries**
- `winreg` (Windows): Registry operations for auto-start
- `msvcrt` (Windows): File locking for single-instance checking
- `threading` (Built-in): Thread management for hotkeys
- `asyncio` (Built-in): Async event loop

#### **Third-Party Packages**

| Dependency | Version | Purpose | Usage |
|-----------|---------|---------|-------|
| pystray | 0.19.5 | System tray | Tray icon and menu integration |
| pynput | 1.8.1 | Global hotkeys | Keyboard monitoring |
| PyQt6 | 6.9.1 | GUI framework | All UI components |
| Pillow | 11.3.0 | Image processing | Screenshot capture, thumbnails |
| ollama | 0.6.0 | AI client | Ollama server communication |
| psutil | 7.1.0 | System monitoring | Resource monitoring |
| aiofiles | 25.1.0 | Async file I/O | Non-blocking file operations |

### 8.2 Integration Points

#### **Ollama Server Integration**

**Connection Pattern:**
```
ExplainShot ←→ Ollama Server (HTTP REST API)
    Port: 11434 (default)
    Protocol: HTTP
    Format: JSON request/response
```

**Supported Operations:**
- List available models
- Generate responses (streaming and non-streaming)
- Check server health
- Pull/push models

**Error Handling:**
- Connection timeouts with configurable retry
- Offline mode for unavailable server
- User notification of service status

#### **Database Integration**

**SQLite Features Used:**
- Transactions for data consistency
- Foreign keys for referential integrity
- Indexes for query optimization
- BLOB support for binary data
- Full-text search (extensible)

**Database Schema:**
- `screenshots`: Captured images metadata
- `chat_history`: Conversation history with AI
- `presets`: Preset prompts
- `settings`: Application configuration

#### **Operating System Integration**

**Windows-Specific Features:**
- Registry access via `winreg` for auto-start
- Startup folder shortcuts
- Global hotkey interception via `pynput`
- File locking for single-instance checking
- System tray icon via `pystray`

**Cross-Platform Support (Architecture):**
- Abstracted Windows-specific code
- Fallback implementations for other platforms
- Platform detection via `sys.platform` and `os.name`

### 8.3 Third-Party Service Dependencies

**Ollama AI Server:**
- **Role**: Local AI inference engine
- **Criticality**: Optional (degraded mode without it)
- **Configuration**: Server URL, model selection, timeouts

**No Cloud Integration:**
- No external AI service calls
- No telemetry or analytics
- No data transmission outside local network
- Privacy-first by design

---

## 9. Scalability and Performance Considerations

### 9.1 Performance Targets

| Metric | Target | Notes |
|--------|--------|-------|
| Startup Time | < 2 seconds | To tray visibility |
| Idle Memory | < 50 MB | Resident memory when inactive |
| Idle CPU | < 0.1% | When not capturing/processing |
| Screenshot Capture | < 500 ms | Full screen capture time |
| Thumbnail Generation | < 2 seconds | Per image async operation |
| AI Response Time | Variable | Depends on model and image complexity |

### 9.2 Memory Optimization

**Lazy Loading:**
- Models not loaded until first use
- Thumbnails generated on-demand
- UI windows created when shown
- Event handlers only for registered events

**Resource Management:**
- Weak references in event subscriptions prevent memory leaks
- Proper async task cleanup on shutdown
- Connection pooling for database operations
- Stream-based processing for large files

### 9.3 Database Optimization

**Indexing:**
- Primary keys on all major tables
- Indexes on frequently queried columns (timestamp, screenshot_id)
- Full-text search indexes for chat history

**Query Optimization:**
- Pagination for large result sets
- Prepared statements to prevent SQL injection
- Async queries to prevent blocking event loop
- Query result caching

**Storage Management:**
- Automatic cleanup of old files
- Configurable retention policies
- Archive support for long-term storage
- Disk space monitoring

### 9.4 Async Architecture Benefits

**Non-Blocking Operations:**
- Screenshot capture doesn't freeze UI
- AI analysis happens in background
- Multiple concurrent operations possible
- Event loop remains responsive

**Concurrency Model:**
```
Main Event Loop
    ├─ Process user input (tray clicks, hotkeys)
    ├─ EventBus emission (non-blocking)
    ├─ Database queries (async)
    ├─ File I/O operations (async)
    ├─ AI inference (async)
    └─ PyQt6 event processing
```

### 9.5 Scalability Considerations

**Extensibility Points:**
- New event types can be added without code changes
- New handlers can subscribe to existing events
- Additional AI models supported through configuration
- Custom presets without code modification

**Module Addition:**
- New models can be added to model layer
- New UI components can be added to views
- New event handlers can subscribe to bus
- Plugins could be supported with event interface

**Data Growth:**
- SQLite handles thousands of screenshots efficiently
- Automatic cleanup prevents unbounded growth
- Configurable storage limits
- Archive system for historical data

---

## 10. Development Guidelines

### 10.1 Code Standards and Best Practices

#### **Python Style Guide**
- Follow **PEP 8** for code formatting
- Use `black` for automatic formatting: `black src/ tests/`
- Use `flake8` for linting: `flake8 src/ tests/`
- Use `mypy` for type checking: `mypy src/`

#### **Type Annotations**
- All function parameters and return types must be annotated
- Use `Optional[T]` for nullable types (not `T | None` for compatibility)
- Use `Dict[K, V]`, `List[T]`, `Tuple[...]` from typing module
- Use `TYPE_CHECKING` imports for forward references to avoid circular imports

```python
from typing import Optional, Dict, List, TYPE_CHECKING

if TYPE_CHECKING:
    from src.views.tray_manager import TrayManager

async def initialize_tray(self, tray: "TrayManager") -> bool:
    ...
```

#### **Documentation Standards**
- Module-level docstring explaining purpose
- Class docstring with role and responsibilities
- Method docstring with Args, Returns, Raises sections
- Type hints and docstrings are required for all public APIs

```python
async def emit_and_wait(
    self,
    event_type: str,
    data: Optional[Dict[str, Any]] = None,
    timeout: float = 5.0
) -> List[Any]:
    """
    Emit an event and wait for all handlers to complete.

    Args:
        event_type: Type of event to emit
        data: Optional event data payload
        timeout: Maximum time to wait for handlers (seconds)

    Returns:
        List of return values from all handlers

    Raises:
        asyncio.TimeoutError: If handlers don't complete within timeout
    """
```

#### **Error Handling**
- Create specific exception classes for error domains
- Inherit from base domain exception
- Include context in error messages
- Log errors at appropriate level (error vs warning)

```python
class OllamaError(Exception):
    """Base exception for Ollama-related errors."""
    pass

class ModelError(OllamaError):
    """Raised when model-related operations fail."""
    pass

try:
    model = await ollama_client.load_model(model_name)
except ModelError as e:
    logger.error("Failed to load model %s: %s", model_name, e)
    # Handle gracefully, maybe use cached response
```

#### **Async/Await Best Practices**
- All I/O operations must be async (database, file, network)
- Use `asyncio.gather()` for concurrent operations
- Use `await asyncio.sleep(0)` for cooperative yielding
- Never block the event loop with sync operations
- Use `asyncio.create_task()` for fire-and-forget operations

```python
# Good - Concurrent operations
results = await asyncio.gather(
    database_manager.save_screenshot(metadata),
    thumbnail_manager.generate_thumbnail(image),
    ollama_client.analyze_image(image)
)

# Bad - Sequential operations
result1 = await database_manager.save_screenshot(metadata)
result2 = await thumbnail_manager.generate_thumbnail(image)
result3 = await ollama_client.analyze_image(image)
```

### 10.2 Architecture Compliance

#### **Layer-Specific Rules**

**Model Layer (src/models/)**
- ✅ Pure data classes and business logic
- ✅ Database operations
- ✅ External service integration (Ollama)
- ❌ NO PyQt6 imports
- ❌ NO UI framework code
- ❌ NO direct file system paths in business logic

**Controller Layer (src/controllers/)**
- ✅ Event orchestration
- ✅ Component lifecycle
- ✅ Business logic coordination
- ✅ Limited synchronous logic for event handling
- ❌ NO PyQt6 imports
- ❌ NO direct database queries (use models)
- ❌ NO UI implementation

**View Layer (src/views/)**
- ✅ PyQt6 UI implementation
- ✅ User interaction handling
- ✅ UI state management
- ✅ Event emission
- ❌ NO business logic
- ❌ NO database queries
- ❌ NO direct Ollama API calls

#### **Naming Conventions**

| Item | Convention | Example |
|------|-----------|---------|
| Classes | PascalCase | `EventBus`, `ScreenshotManager` |
| Methods/Functions | snake_case | `capture_screenshot()`, `emit_event()` |
| Constants | UPPER_CASE | `DEFAULT_TIMEOUT`, `MAX_QUEUE_SIZE` |
| Private attributes | _snake_case | `_subscribers`, `_event_queue` |
| Event types | dot.separated.case | `screenshot.captured`, `app.ready` |
| Module files | snake_case | `event_bus.py`, `settings_manager.py` |

#### **Event Type Definition**

New event types must be added to `EventTypes` class in `src/__init__.py`:

```python
class EventTypes:
    """Central registry of event types for the EventBus system."""

    # Existing events...

    # New domain events
    MY_FEATURE_STARTED = "my_feature.started"
    MY_FEATURE_COMPLETED = "my_feature.completed"
    MY_FEATURE_ERROR = "my_feature.error"
```

**Event Naming Pattern:**
- Format: `domain.action` or `domain.state`
- Example: `screenshot.captured`, `app.shutdown_starting`, `error.occurred`

### 10.3 Contributing Guidelines

#### **Adding a New Feature**

1. **Identify MVC Components**
   - What model layer is needed? (data, business logic)
   - What controller changes? (event handling, coordination)
   - What view layer is needed? (UI components)

2. **Create Model Components** (if needed)
   - Implement business logic in model layer
   - Add database schema migration if needed
   - Write unit tests

3. **Create Controller Components** (if needed)
   - Add event types to `EventTypes` class
   - Implement event handlers
   - Add to `MainController` initialization

4. **Create View Components** (if needed)
   - Implement UI using PyQt6
   - Handle user interactions
   - Emit events for user actions

5. **Integration Testing**
   - Test end-to-end workflow
   - Verify event flow
   - Check error handling

6. **Documentation**
   - Update this CONTEXT.md if architecture changed
   - Add docstrings to new components
   - Document new event types

#### **Code Review Checklist**

- [ ] Type hints on all function signatures
- [ ] Docstrings on public methods
- [ ] No imports crossing layer boundaries incorrectly
- [ ] No UI code in model layer
- [ ] No business logic in view layer
- [ ] Async operations use await properly
- [ ] Error handling includes logging
- [ ] Tests exist for new functionality
- [ ] Code passes black, flake8, mypy
- [ ] Follows naming conventions
- [ ] No hardcoded paths or configuration values

#### **Testing Requirements**

- Unit tests for all new models
- Integration tests for event workflows
- Test coverage target: > 70% for critical paths
- Use `pytest` with async support
- Mock external dependencies (Ollama, database)

```bash
# Run tests with coverage
pytest tests/ --cov=src --cov-report=html

# Run specific test file
pytest tests/test_event_bus.py -v

# Run with output
pytest tests/ -s -v
```

### 10.4 Common Development Tasks

#### **Adding a New Event**

1. Define event type in `src/__init__.py`:
```python
class EventTypes:
    MY_NEW_EVENT = "my_new.event"
```

2. Subscribe to event in controller:
```python
await self.event_bus.subscribe(
    EventTypes.MY_NEW_EVENT,
    self._handle_my_new_event
)
```

3. Emit event when condition occurs:
```python
await self.event_bus.emit(
    EventTypes.MY_NEW_EVENT,
    data={'key': 'value'},
    source="my_component"
)
```

#### **Adding a New Setting**

1. Add field to config dataclass in `src/models/settings_manager.py`:
```python
@dataclass
class UIConfig:
    theme: str = "dark"
    my_new_setting: str = "default_value"  # Add here
```

2. SettingsManager automatically handles persistence
3. Access via: `settings.ui.my_new_setting`

#### **Adding a New Database Table**

1. Create table in `DatabaseManager.initialize_database()`:
```python
async with self._get_connection() as conn:
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS my_table (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            ...
        )
    """)
```

2. Implement get/save methods in DatabaseManager
3. Document table purpose and columns

#### **Debugging Async Code**

```python
# Enable asyncio debug mode
asyncio.run(main(), debug=True)

# Or in environment: PYTHONASYNCDEBUG=1

# Log event details
await event_bus.emit(EventTypes.MY_EVENT)
metrics = await event_bus.get_metrics()
logger.info("Event metrics: %s", metrics)
```

### 10.5 Performance Profiling

#### **Memory Profiling**
```bash
# Using memory_profiler
pip install memory-profiler
python -m memory_profiler main.py
```

#### **Async Profiling**
```python
# In main.py for debugging
import asyncio

# Enable debug mode to catch slow callbacks
asyncio.run(main(), debug=True)
```

#### **Database Query Optimization**
```python
# Enable query logging
connection.set_trace_callback(print)

# Analyze query performance
EXPLAIN QUERY PLAN SELECT ...
```

### 10.6 Release Checklist

- [ ] All tests pass: `pytest tests/`
- [ ] Code formatted: `black src/`
- [ ] No lint issues: `flake8 src/`
- [ ] Type check passes: `mypy src/`
- [ ] Version updated in `src/__init__.py`
- [ ] CONTEXT.md updated if needed
- [ ] README.md updated if user-facing changes
- [ ] Build executable: `pyinstaller --windowed --onefile --icon=resources/icons/app.ico main.py`
- [ ] Test executable on Windows
- [ ] Create git tag: `git tag v0.1.1`

---

## 11. Troubleshooting and Common Issues

### 11.1 Hotkey Registration Failures

**Problem**: Global hotkeys not working

**Debugging Steps:**
1. Check hotkey configuration in settings
2. Verify hotkey is not bound by another application
3. Check `HotkeyHandler` logs for registration errors
4. Try different hotkey combination

**Solution:**
```python
# Update hotkey in settings
settings.hotkeys.screenshot_capture = "ctrl+alt+s"
await settings_manager.save_settings()
```

### 11.2 Ollama Server Connection Issues

**Problem**: AI analysis not working

**Debugging Steps:**
1. Verify Ollama server is running: `http://localhost:11434`
2. Check network connectivity
3. Verify model is installed in Ollama
4. Check logs for connection errors

**Solution:**
```python
# Test connection
health = await ollama_client.check_health()
if not health:
    logger.error("Ollama server unavailable")
```

### 11.3 Database Corruption

**Problem**: Database errors on startup

**Solution:**
1. Backup existing database: `cp app_data.db app_data.db.backup`
2. Delete corrupt database: `rm app_data.db`
3. Restart application to recreate clean database

### 11.4 Memory Leaks

**Problem**: Memory usage increasing over time

**Investigation:**
1. Check for circular references in event subscriptions
2. Verify weak references are being used correctly
3. Check for unfinished async tasks
4. Use memory profiler to identify leaks

**Prevention:**
- Always use weak references in event subscriptions
- Properly clean up async tasks on shutdown
- Test memory usage with long-running processes

---

## 12. Future Enhancement Opportunities

### 12.1 Planned Features

- **Multi-GPU Support**: Leverage multiple GPUs for faster processing
- **Batch Processing**: Process multiple screenshots in parallel
- **Custom Model Support**: Allow users to provide custom AI models
- **Cloud Sync**: Optional cloud backup of screenshots
- **Plugin System**: Enable third-party extensions via event system
- **Advanced Analytics**: Detailed usage and performance analytics

### 12.2 Architecture Improvements

- **Microservices Model**: Separate AI inference into standalone service
- **GraphQL API**: Expose application state via GraphQL for external tools
- **WebSocket Support**: Real-time communication for remote clients
- **Database Migration**: Automated schema migrations with versioning
- **Configuration Profiles**: Support multiple configuration sets

### 12.3 Performance Improvements

- **Native Extensions**: C++ modules for performance-critical paths
- **GPU Acceleration**: GPU-accelerated image processing
- **Smart Caching**: ML-based cache invalidation prediction
- **Streaming Optimization**: HTTP/2 for faster AI responses

---

## Conclusion

ExplainShot demonstrates a well-architected desktop application with:

- **Clear MVC Architecture**: Separation of concerns across models, views, and controllers
- **Event-Driven Design**: Loose coupling enabling scalability and maintainability
- **Quality-First Development**: Type hints, comprehensive logging, error handling
- **OOP Principles**: Proper use of encapsulation, inheritance, polymorphism, abstraction
- **Async-First**: Modern async/await for responsive UI and non-blocking I/O
- **Extensibility**: Event system enables feature addition without code modification

This document provides new developers and AI agents with a comprehensive understanding of the application's architecture, enabling them to contribute effectively while maintaining code quality and consistency.

---

**Document Version:** 1.0
**Last Updated:** October 18, 2025
**Maintainers:** ExplainShot Development Team
