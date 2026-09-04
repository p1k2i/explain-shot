"""Gallery window.

Fluent frameless chrome + three panels (screenshots / chat / presets).
The chat panel is now a branching ChatGPT-style tree — the window holds
the coordination logic (submit / edit / regenerate / delete) that turns
those UI events into ChatHistory mutations + AI provider calls.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ...ai.history import ChatHistory, MessageNode
from ...ai.provider import AIError, AIProvider
from ...capture.models import ScreenshotRecord
from ...capture.screenshot import ScreenshotService
from ...capture.thumbnails import ThumbnailCache
from ...config.settings import Settings
from ...core.database import Database
from ...core.signals import AppSignals
from ...presets.manager import PresetManager
from ..chrome import FramelessWindow, TitleBar
from ..icons import app_icon
from .chat_panel import ChatPanel, set_chat_theme
from .presets_panel import PresetsPanel
from .preview import PreviewWindow
from .screenshots_panel import ScreenshotsPanel

log = logging.getLogger(__name__)


class GalleryWindow(FramelessWindow):
    def __init__(
        self,
        *,
        settings: Settings,
        signals: AppSignals,
        db: Database,
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
        self.db = db
        self.screenshots = screenshots
        self.thumbnails = thumbnails
        self.presets = presets
        self.history = history
        self.provider_factory = provider_factory

        self.setWindowTitle("ExplainShot")
        self.setWindowIcon(app_icon())
        self.resize(1280, 800)
        self.setMinimumSize(960, 600)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- chrome ---
        self.title_bar = TitleBar(self, title="ExplainShot")
        self.title_bar.request_close.connect(self.close)
        root.addWidget(self.title_bar)

        # --- body ---
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(12, 12, 12, 12)
        body_layout.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(6)

        self.screenshots_panel = ScreenshotsPanel(
            self.screenshots, self.thumbnails, settings.ui.thumbnail_px,
        )
        splitter.addWidget(self._wrap(self.screenshots_panel))

        set_chat_theme(settings.ui.theme)
        self.chat_panel = ChatPanel()
        splitter.addWidget(self._wrap(self.chat_panel))

        self.presets_panel = PresetsPanel(self.presets)
        splitter.addWidget(self._wrap(self.presets_panel))

        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 5)
        splitter.setStretchFactor(2, 3)
        splitter.setSizes([460, 560, 340])
        body_layout.addWidget(splitter)

        root.addWidget(body, 1)

        self._selected: ScreenshotRecord | None = None
        self._active_task: asyncio.Task | None = None

        self._preview_windows: list[PreviewWindow] = []

        # Wire panels
        self.screenshots_panel.selection_changed.connect(self._on_selection)
        self.screenshots_panel.preview_requested.connect(self._on_preview_requested)
        self.screenshots_panel.delete_requested.connect(self._on_screenshot_delete)
        self.screenshots_panel.rename_requested.connect(self._on_screenshot_rename)
        self.chat_panel.message_submitted.connect(self._on_prompt_submitted)
        self.chat_panel.edit_submitted.connect(self._on_edit_submitted)
        self.chat_panel.regenerate_requested.connect(self._on_regenerate_requested)
        self.chat_panel.delete_requested.connect(self._on_delete_requested)
        self.chat_panel.branch_switch_requested.connect(self._on_branch_switch)
        self.chat_panel.clear_requested.connect(self._on_clear)
        self.presets_panel.preset_run.connect(self._on_preset_run)
        self.presets_panel.preset_paste.connect(self._on_preset_paste)

        # App signals
        self.signals.screenshot_captured.connect(self._on_new_screenshot)
        self.signals.screenshot_deleted.connect(self.screenshots_panel.remove)
        self.signals.preset_saved.connect(lambda _: self.presets_panel.reload())
        self.signals.preset_deleted.connect(lambda _: self.presets_panel.reload())

        # Restore geometry
        state = self.db.load_window_state("gallery")
        if state:
            try:
                self.restoreGeometry(state[0])
                if state[1]:
                    self.showMaximized()
            except Exception:
                pass

        self.screenshots_panel.reload()

    # -- lifecycle -------------------------------------------------------------

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        added = self.screenshots.scan_directory()
        if added:
            self.screenshots_panel.reload()
        self.title_bar.refresh_max_glyph()

    def changeEvent(self, event) -> None:  # type: ignore[override]
        # Keep the max/restore glyph in sync when the OS toggles the state.
        super().changeEvent(event)
        try:
            self.title_bar.refresh_max_glyph()
        except AttributeError:
            pass

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._active_task and not self._active_task.done():
            self._active_task.cancel()
        try:
            self.db.save_window_state("gallery", bytes(self.saveGeometry()), self.isMaximized())
        except Exception:
            log.debug("could not save window state", exc_info=True)
        super().closeEvent(event)

    def keyPressEvent(self, event: QKeyEvent | None) -> None:  # type: ignore[override]
        if event is not None:
            if event.key() == Qt.Key.Key_F5:
                self.thumbnails.clear()
                self.screenshots_panel.reload()
                return
            if event.key() == Qt.Key.Key_Escape:
                self.close()
                return
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_K:
                self._on_clear()
                return
        super().keyPressEvent(event)

    # -- selection -------------------------------------------------------------

    def _on_selection(self, record: ScreenshotRecord | None) -> None:
        self._selected = record
        if record is None:
            self.chat_panel.clear()
            self.chat_panel.set_enabled(False)
            self.chat_panel.set_status("No screenshot")
            self.title_bar.set_title("ExplainShot")
            return
        self.chat_panel.set_enabled(True)
        self.chat_panel.set_status(f"{record.width}×{record.height}")
        self.title_bar.set_title(f"ExplainShot — {record.filename}")
        self._refresh_transcript()

    def _refresh_transcript(self) -> None:
        if not self._selected:
            self.chat_panel.clear()
            return
        path = self.history.active_path(self._selected.id)
        self.chat_panel.render(path)

    def _on_new_screenshot(self, record: ScreenshotRecord) -> None:
        self.screenshots_panel.add_or_update(record)

    def _on_preview_requested(self, screenshot_id: str) -> None:
        record = self.screenshots.get(screenshot_id)
        if not record:
            return
        window = PreviewWindow(record.path, record.filename)
        window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        window.destroyed.connect(lambda _=None, w=window: self._preview_windows.remove(w) if w in self._preview_windows else None)
        self._preview_windows.append(window)
        window.show()
        window.raise_()
        window.activateWindow()

    def _on_screenshot_delete(self, screenshot_id: str) -> None:
        self.screenshots.delete(screenshot_id)

    def _on_screenshot_rename(self, screenshot_id: str, new_stem: str) -> None:
        updated = self.screenshots.rename(screenshot_id, new_stem)
        if updated is not None:
            self.screenshots_panel.reload()
            self.screenshots_panel.select(updated.id)

    # -- chat operations -------------------------------------------------------

    def _on_prompt_submitted(self, prompt: str) -> None:
        if not self._selected:
            return
        message_id = self.history.append_root(self._selected.id, "user", prompt)
        self._refresh_transcript()
        self._run_completion()

    def _on_edit_submitted(self, source_id: int, new_content: str) -> None:
        if not self._selected:
            return
        source = self.db.get_message(source_id)
        if not source:
            return
        # Fork under the same parent as the edited message.
        self.history.fork_from(
            self._selected.id, source["parent_id"], "user", new_content,
        )
        self._refresh_transcript()
        self._run_completion()

    def _on_regenerate_requested(self, assistant_id: int) -> None:
        if not self._selected:
            return
        assistant = self.db.get_message(assistant_id)
        if not assistant or assistant["role"] != "assistant":
            return
        # A new assistant sibling under the same parent (the user's prompt).
        self._refresh_transcript()   # Optimistic: keep old bubble visible for a beat
        self._run_completion(fork_parent_id=assistant["parent_id"])

    def _on_delete_requested(self, message_id: int) -> None:
        if not self._selected:
            return
        self.history.delete_subtree(self._selected.id, message_id)
        self._refresh_transcript()

    def _on_branch_switch(self, message_id: int, direction: int) -> None:
        if not self._selected:
            return
        current = self.db.get_message(message_id)
        if not current:
            return
        siblings = [
            row["id"]
            for row in self.db.list_children(self._selected.id, current["parent_id"])
        ]
        try:
            index = siblings.index(message_id)
        except ValueError:
            return
        new_index = index + direction
        if not (0 <= new_index < len(siblings)):
            return
        self.history.switch_branch(self._selected.id, siblings[new_index])
        self._refresh_transcript()

    def _on_clear(self) -> None:
        if not self._selected:
            return
        self.history.clear(self._selected.id)
        self._refresh_transcript()

    # -- preset actions --------------------------------------------------------

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

    # -- completion runner -----------------------------------------------------

    def _run_completion(self, *, fork_parent_id: int | None = None) -> None:
        if not self._selected:
            return
        if self._active_task and not self._active_task.done():
            self._active_task.cancel()

        provider = self.provider_factory()
        image_path = self._selected.path
        screenshot_id = self._selected.id
        history = self.history
        chat_panel = self.chat_panel
        signals = self.signals

        async def worker() -> None:
            path = history.active_path(screenshot_id)
            # Where do we attach the assistant turn?
            parent_id = fork_parent_id if fork_parent_id is not None else (path[-1].id if path else None)
            placeholder = MessageNode(
                id=-1,
                parent_id=parent_id,
                role="assistant",
                content="",
                model=provider.model,
                created_at=datetime.now(),
                siblings=None,
                index_in_siblings=0,
            )
            chat_panel.set_status("Thinking…")
            chat_panel.begin_streaming(placeholder)
            signals.ai_reply_started.emit(screenshot_id)

            messages = history.to_prompt(
                screenshot_id,
                image_path=image_path,
                system=(
                    "You are ExplainShot, a helpful assistant that describes "
                    "and answers questions about the screenshot the user just captured. "
                    "Be direct and specific."
                ),
            )
            collected: list[str] = []
            try:
                async for chunk in provider.stream(messages):
                    collected.append(chunk)
                    chat_panel.append_stream(chunk)
                    signals.ai_reply_chunk.emit(screenshot_id, chunk)
                reply = "".join(collected)
                chat_panel.end_streaming(reply)
                history.fork_from(
                    screenshot_id, parent_id, "assistant", reply, model=provider.model,
                )
                signals.ai_reply_completed.emit(screenshot_id, reply)
                chat_panel.set_status("Ready")
                self._refresh_transcript()
            except asyncio.CancelledError:
                chat_panel.end_streaming("".join(collected))
                chat_panel.set_status("Cancelled")
                self._refresh_transcript()
                raise
            except Exception as exc:
                log.exception("chat completion failed")
                chat_panel.end_streaming("".join(collected))
                chat_panel.show_error(str(exc))
                chat_panel.set_status("Error")
                signals.ai_reply_failed.emit(screenshot_id, str(exc))
                self._refresh_transcript()

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
