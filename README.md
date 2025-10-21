# ExplainShot

A lightweight, cross-platform desktop application for capturing screenshots and explaining them using AI integration. Built with Python 3.12 following the MVC pattern with minimal coupling.

## Features

- **Background Process**: Runs as a daemon-like service with minimal resource footprint
- **System Tray Integration**: Clean, responsive tray icon with context menu
- **Auto-Start Support**: Configurable Windows startup integration
- **Dark Theme UI**: Modern interface with transparency support
- **Event-Driven Architecture**: Loose coupling between modules using asyncio
- **Comprehensive Logging**: Structured logging with privacy protection
- **Settings Management**: SQLite-based configuration with validation

## Project Structure

```
explain-shot/
├── src/
│   ├── models/           # Data layer (Settings, Database)
│   ├── views/            # UI layer (Tray, Windows)
│   ├── controllers/      # Logic layer (EventBus, Main Controller)
│   └── utils/            # Utilities (Logging, Auto-start, Icons)
├── resources/
│   └── icons/            # Application icons for different states
├── logs/                 # Application logs
├── tests/                # Unit tests
├── main.py              # Application entry point
└── requirements.txt     # Python dependencies
```

## Installation

### Setting Up a Virtual Environment

1. **Create a Virtual Environment**:
  ```bash
  python -m venv venv
  ```

2. **Activate the Virtual Environment**:
  - On Windows:
    ```bash
    venv\Scripts\activate
    ```
  - On macOS/Linux:
    ```bash
    source venv/bin/activate
    ```

### For Production
Install only the necessary dependencies:
```bash
pip install -r requirements.txt
```

### For Development
Install all dependencies, including development tools:
```bash
pip install -r requirements-dev.txt
```

## Usage

### Development Mode
```bash
python main.py
```

### Command Line Options
```bash
python main.py --help
python main.py --debug                    # Enable debug logging
python main.py --log-level DEBUG         # Set log level
```

### Building Executable
```bash
pyinstaller --windowed --onefile --icon=resources/icons/app.ico main.py
```

## Architecture

### MVC Pattern Implementation

- **Model Layer**:
  - `SettingsManager`: Configuration and validation
  - `DatabaseManager`: SQLite operations
  - `ScreenshotManager`: Image capture and processing
  - `OllamaClient`: AI integration

- **View Layer**:
  - `TrayManager`: System tray icon and menu
  - `UIManager`: PyQt6 windows

- **Controller Layer**:
  - `EventBus`: Asynchronous event distribution
  - `MainController`: Application orchestration
  - `HotkeyHandler`: Global hotkey management

### Event-Driven Communication

All modules communicate through the `EventBus` using predefined event types:

```python
# Example event emission
await event_bus.emit(EventTypes.SCREENSHOT_CAPTURE_REQUESTED)

# Example event subscription
await event_bus.subscribe(EventTypes.APP_SHUTDOWN_REQUESTED, handler)
```

### System Integration

- **Auto-Start**: Supports both Windows Registry and Startup Folder methods
- **Icon Management**: Dynamic state-based tray icons with fallback generation
- **Logging**: Privacy-aware structured logging with file rotation
- **Settings**: Database-backed configuration with validation

## Configuration

Settings are stored in SQLite database with the following structure:

```python
ApplicationSettings:
  - hotkeys: HotkeyConfig
  - ui: UIConfig
  - screenshot: ScreenshotConfig
  - ollama: OllamaConfig
  - auto_start: AutoStartConfig
```

### Auto-Start Configuration

The application can automatically start with Windows:

- **Registry Method**: `HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run`
- **Startup Folder**: `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`
- **Automatic Selection**: Chooses best available method based on permissions

## Logging

Structured logging with multiple output formats:

- **File Logs**: JSON format with rotation (configurable size/count)
- **Console Output**: Human-readable format for development
- **Privacy Filtering**: Automatic sanitization of sensitive information
- **Module-Specific**: Separate log files for different components

## Error Handling

Comprehensive error management:

- **Classification**: Critical, Recoverable, Transient errors
- **Recovery**: Automatic retry with exponential backoff
- **Fallbacks**: Graceful degradation for service unavailability
- **User Notification**: System tray notifications for important errors

## Performance Considerations

- **Startup Time**: Target < 2 seconds to tray visibility
- **Memory Usage**: Target < 50MB resident memory
- **CPU Usage**: Target < 0.1% when idle
- **Resource Management**: Lazy loading and efficient caching

## Dependencies

### Core Dependencies
- `pystray`: System tray functionality
- `pynput`: Global hotkey handling
- `Pillow`: Image processing
- `PyQt6`: UI framework
- `ollama`: AI integration
- `psutil`: System monitoring

## License

This project is licensed under the [GNU General Public License v3.0](https://www.gnu.org/licenses/gpl-3.0.en.html).

See [LICENSE](LICENSE) in this repository or visit [https://www.gnu.org/licenses/gpl-3.0.en.html](https://www.gnu.org/licenses/gpl-3.0.en.html).

## Contributing

[Contributing guidelines to be added]
