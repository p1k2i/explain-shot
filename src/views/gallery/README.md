# Gallery Window - Component-Based Implementation

## Overview

The new gallery window implementation (`src/views/gallery/`) provides a modern, component-based architecture that separates concerns and improves maintainability. This implementation replaces the monolithic gallery window with coordinated components.

## Architecture

### Main Components

1. **GalleryWindow** (`gallery_window.py`) - Main coordinator class
2. **CustomTitleBar** (`components/custom_title_bar.py`) - Window title bar with drag support
3. **ChatInterface** (`components/chat_interface.py`) - AI chat functionality
4. **ScreenshotGallery** (`components/screenshots_gallery.py`) - Screenshot display and selection
5. **PresetsPanel** (`components/presets_panel.py`) - Preset management
6. **Gallery Widgets** (`components/gallery_widgets.py`) - Shared data structures and constants

### Key Features

- **Component Separation**: Each major UI section is a separate, reusable component
- **Event Coordination**: GalleryWindow coordinates communication between components
- **Style Management**: Integrated with the existing style system
- **Async Operations**: Full async support for database and file operations
- **State Management**: Centralized state tracking through GalleryState

## Usage

### Basic Usage

```python
from src.views.gallery import GalleryWindow

# Create gallery window
gallery = GalleryWindow(
    event_bus=event_bus,
    screenshot_manager=screenshot_manager,
    database_manager=database_manager,
    settings_manager=settings_manager
)

# Initialize and show
await gallery.initialize()
await gallery.show_gallery(pre_selected_screenshot_id=123)
```

### Component Access

```python
# Access individual components
chat = gallery.chat_interface
screenshots = gallery.screenshots_gallery
presets = gallery.presets_panel

# Component-specific operations
chat.add_user_message("Hello AI")
await screenshots.select_screenshot(screenshot_id)
await presets.load_presets()
```

## Benefits

1. **Maintainability**: Each component can be developed and tested independently
2. **Reusability**: Components can be used in other windows or contexts
3. **Testability**: Smaller, focused components are easier to test
4. **Extensibility**: New features can be added to specific components
5. **Performance**: Better resource management through component lifecycle

## Migration

The new implementation provides the same public interface as the original gallery window, making it a drop-in replacement. All existing event handling and integration points remain compatible.

## File Structure

```
src/views/gallery/
├── __init__.py                 # Package exports
├── gallery_window.py          # Main coordinator
└── components/
    ├── __init__.py             # Component exports
    ├── custom_title_bar.py     # Title bar component
    ├── chat_interface.py       # Chat functionality
    ├── screenshots_gallery.py  # Screenshot display
    ├── presets_panel.py        # Preset management
    └── gallery_widgets.py      # Shared utilities
```
