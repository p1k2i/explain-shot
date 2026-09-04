# ExplainShot

Capture any region of your screen, send it to a vision-capable AI, and
have a conversation about what's on it. Works with any OpenAI-compatible
API — Ollama, LM Studio, vLLM, the OpenAI API itself, and anything else
that speaks `/v1/chat/completions`.

Runs in your system tray, opens a modern Fluent-styled gallery when you
need it, and remembers every conversation per screenshot.

## Install

Requires Python 3.12 on Windows 10/11.

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

For development:

```bash
pip install -r requirements-dev.txt
```

## Building

The included `explain-shot.spec` targets PyInstaller. Run:

```bash
.\build.ps1 -Full
```

The executable ends up at `dist\ExplainShot\ExplainShot.exe`.

## Usage

- **Tray icon.** Right-click for capture / gallery / settings / quit. Double-click opens the gallery.
- **Default hotkeys** (rebindable in Settings → Hotkeys):
  - `Ctrl+Shift+S` — capture a region
  - `Ctrl+Shift+G` — toggle the gallery
  - `Ctrl+Shift+P` — open settings
- **Gallery.** Three columns: screenshots (left), AI conversation (middle), reusable prompt presets (right).
- **F5** in the gallery clears thumbnail cache and reloads the list. **Esc** closes it.

## AI provider setup

Open Settings → AI provider and point it at any OpenAI-compatible endpoint.
Common values:

| Provider  | Base URL                          | API key   |
| :-------- | :-------------------------------- | :-------- |
| Ollama    | `http://localhost:11434/v1`       | *(none)*  |
| LM Studio | `http://localhost:1234/v1`        | *(none)*  |
| OpenAI    | `https://api.openai.com/v1`       | required  |

Use "Fetch models" to populate the model list from the endpoint, and
"Test connection" to sanity-check the URL. Vision-capable models
(`llama3.2-vision`, `gpt-4o`, `qwen2.5-vl`, etc.) are required for
screenshot analysis.

## Data locations

Everything lives under `%APPDATA%\ExplainShot\` on Windows:

```
explainshot.db     — SQLite: settings, screenshot metadata, chat history, presets
screenshots\       — captured PNG/JPEG files
logs\              — rotating log files
.instance.lock     — single-instance lock file
```

## Project layout

```
explainshot/
├── main.py            entry point (qasync + Qt event loop)
├── app.py             Application: owns singletons and window lifecycle
├── config/            paths + settings dataclasses + SQLite persistence
├── core/              AppSignals, Database, logging setup
├── ai/                OpenAI-compatible provider + chat history
├── capture/           screenshot capture, metadata, thumbnails
├── presets/           prompt preset CRUD + built-ins
├── hotkeys/           global hotkey binding (pynput -> Qt signals)
├── ui/
│   ├── theme.py       Fluent design tokens + QSS renderer
│   ├── icons.py       icon loading
│   ├── tray.py        system tray icon and menu
│   ├── overlay/       full-screen region selector
│   ├── settings/      settings window
│   └── gallery/       gallery window and its three panels
└── util/              autostart (Windows registry), singleton lock
```

## License

[GNU General Public License v3.0](LICENSE).
