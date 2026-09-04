"""Gallery window.

Three concrete design decisions here answer the user's stated pain:

1.  **No cache system.** The old GalleryWindow had a five-way cache
    (_screenshot_cache / _preset_cache / _thumbnail_cache / _ui_state_cache
    with a five-minute _cache_expiry_seconds, plus _content_loaded flag
    and _is_cache_valid vs _restore_from_cache vs _load_fresh_content
    vs _load_content branches). All of that plus its own signal wiring
    was the reason "sometimes the window stops opening" — the flags could
    end up in a state where the window was hidden, invalidated once, and
    never re-loaded. Here the window simply reloads the list from the
    (fast, indexed) database whenever it becomes visible. That was already
    fast enough — the cache was solving a problem the app didn't have.

2.  **No transparency.** Solid background from the Fluent theme. The old
    window toggled WA_TranslucentBackground based on an opacity slider,
    which forces Qt into a compositing path that repaints the whole
    window on every child update. That was the source of the sluggish
    feel. Windows 11's own File Explorer isn't translucent either.

3.  **Fixed lifecycle.** Windows are cheap; create the gallery when
    show() is called, destroy on close. There is no ambiguity between
    "closed" and "hidden" — closing removes the object; the next call
    to open makes a fresh one.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ...ai.history import ChatHistory
from ...ai.provider import AIError, AIProvider
from ...capture.models import ScreenshotRecord
from ...capture.screenshot import ScreenshotService
from ...capture.thumbnails import ThumbnailCache
from ...config.settings import Settings
from ...core.signals import AppSignals
from ...presets.manager import PresetManager
from ..icons import app_icon
from .chat_panel import ChatPanel
from .presets_panel import PresetsPanel
from .screenshots_panel import ScreenshotsPanel

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)


class GalleryWindow(QWidget):
    def __init__(
        self,
        *,
        settings: Settings,
        signals: AppSignals,
        screenshots: ScreenshotService,
        thumbnails: ThumbnailCache,
        presets: PresetManager,
        history: ChatHistory,
        provider_factory,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.signals = signals
        self.screenshots = screenshots
        self.thumbnails = thumbnails
        self.presets = presets
        self.history = history
        self.provider_factory = provider_factory  # () -> AIProvider

        self.setWindowTitle("ExplainShot")
        self.setWindowIcon(app_icon())
        self.resize(1280, 800)
        self.setMinimumSize(960, 600)

        # Solid background — the ordinary widget path, no translucency attribute.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(6)

        # Left — screenshots
        self.screenshots_panel = ScreenshotsPanel(
            self.screenshots, self.thumbnails, settings.ui.thumbnail_px
        )
        splitter.addWidget(self._wrap(self.screenshots_panel))

        # Middle — chat
        self.chat_panel = ChatPanel()
        splitter.addWidget(self._wrap(self.chat_panel))

        # Right — presets
        self.presets_panel = PresetsPanel(self.presets)
        splitter.addWidget(self._wrap(self.presets_panel))

        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 5)
        splitter.setStretchFactor(2, 3)
        splitter.setSizes([460, 560, 340])
        root.addWidget(splitter)

        self._selected: ScreenshotRecord | None = None
        self._active_task: asyncio.Task | None = None

        # Wire panels
        self.screenshots_panel.selection_changed.connect(self._on_selection)
        self.chat_panel.message_submitted.connect(self._on_prompt_submitted)
        self.presets_panel.preset_run.connect(self._on_preset_run)
        self.presets_panel.preset_paste.connect(self._on_preset_paste)

        # Wire signals
        self.signals.screenshot_captured.connect(self._on_new_screenshot)
        self.signals.screenshot_deleted.connect(self.screenshots_panel.remove)
        self.signals.preset_saved.connect(lambda _: self.presets_panel.reload())
        self.signals.preset_deleted.connect(lambda _: self.presets_panel.reload())

        # Load initial content synchronously — the DB query is fast, and this
        # avoids the "sometimes the window opens empty" race.
        self.screenshots_panel.reload()

    # -- window lifecycle ------------------------------------------------------

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        # Refresh in case the folder gained new files while we were closed.
        added = self.screenshots.scan_directory()
        if added:
            self.screenshots_panel.reload()

    def keyPressEvent(self, event: QKeyEvent | None) -> None:  # type: ignore[override]
        if event and event.key() == Qt.Key.Key_F5:
            self.thumbnails.clear()
            self.screenshots_panel.reload()
            return
        if event and event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        # Cancel in-flight streams so the async task doesn't outlive the widgets.
        if self._active_task and not self._active_task.done():
            self._active_task.cancel()
        super().closeEvent(event)

    # -- selection & chat ------------------------------------------------------

    def _on_selection(self, record: ScreenshotRecord | None) -> None:
        self._selected = record
        self.chat_panel.clear()
        if record is None:
            self.chat_panel.set_enabled(False)
            self.chat_panel.set_status("Idle")
            return
        self.chat_panel.set_enabled(True)
        self.chat_panel.set_status(record.filename)
        for message in self.history.load(record.id):
            self.chat_panel.add_message(message.role, message.content)

    def _on_new_screenshot(self, record: ScreenshotRecord) -> None:
        self.screenshots_panel.add_or_update(record)

    def _on_prompt_submitted(self, prompt: str) -> None:
        if not self._selected:
            return
        self.history.append(self._selected.id, "user", prompt)
        self.chat_panel.add_message("user", prompt)
        self._run_completion(prompt)

    def _on_preset_run(self, preset_id: str) -> None:
        preset = self.presets.get(preset_id)
        if not preset or not self._selected:
            return
        self.presets.record_use(preset_id)
        self._on_prompt_submitted(preset.prompt)

    def _on_preset_paste(self, preset_id: str) -> None:
        preset = self.presets.get(preset_id)
        if preset:
            self.chat_panel.replace_prompt(preset.prompt)

    def _run_completion(self, prompt: str) -> None:
        if not self._selected:
            return
        provider = self.provider_factory()
        image_path = self._selected.path
        screenshot_id = self._selected.id
        history = self.history

        async def worker() -> None:
            messages = history.to_prompt(
                screenshot_id,
                image_path=image_path,
                system=(
                    "You are ExplainShot, a helpful assistant that describes "
                    "and answers questions about the screenshot the user just captured. "
                    "Be direct and specific."
                ),
            )
            self.chat_panel.set_status("Thinking…")
            self.chat_panel.begin_streaming()
            self.signals.ai_reply_started.emit(screenshot_id)
            collected: list[str] = []
            try:
                async for chunk in provider.stream(messages):
                    collected.append(chunk)
                    self.chat_panel.append_stream(chunk)
                    self.signals.ai_reply_chunk.emit(screenshot_id, chunk)
                reply = "".join(collected)
                self.chat_panel.end_streaming(reply)
                history.append(screenshot_id, "assistant", reply, model=provider.model)
                self.signals.ai_reply_completed.emit(screenshot_id, reply)
                self.chat_panel.set_status("Ready")
            except asyncio.CancelledError:
                self.chat_panel.end_streaming("".join(collected))
                self.chat_panel.set_status("Cancelled")
                raise
            except (AIError, Exception) as exc:
                log.exception("chat completion failed")
                self.chat_panel.end_streaming("".join(collected))
                self.chat_panel.show_error(str(exc))
                self.chat_panel.set_status("Error")
                self.signals.ai_reply_failed.emit(screenshot_id, str(exc))

        self._active_task = asyncio.ensure_future(worker())

    # -- helpers ---------------------------------------------------------------

    @staticmethod
    def _wrap(widget: QWidget) -> QFrame:
        frame = QFrame()
        frame.setObjectName("Panel")
        wrapper = QVBoxLayout(frame)
        wrapper.setContentsMargins(10, 10, 10, 10)
        wrapper.setSpacing(0)
        wrapper.addWidget(widget)
        return frame
