"""Gallery window.

Layout: custom title bar over a three-column body — screenshots, chat,
presets. The window is a *view* over the app's `ChatController` and
`ChatHistory`: it visualises state, forwards user input, and rebuilds
the transcript on demand. It never owns an in-flight completion, so
closing the window or switching screenshots never drops a reply.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import (
    QFrame,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ...ai.controller import ChatController
from ...ai.history import ChatHistory, MessageNode
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


def _humanise_size(nbytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if nbytes < 1024 or unit == "GB":
            return f"{nbytes:.0f} {unit}" if unit == "B" else f"{nbytes:.1f} {unit}"
        nbytes /= 1024
    return f"{nbytes} B"


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
        chat: ChatController,
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
        self.chat = chat

        self.setWindowTitle("ExplainShot")
        self.setWindowIcon(app_icon())
        self.resize(1280, 800)
        self.setMinimumSize(960, 600)

        set_chat_theme(settings.ui.theme)

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
        self.chat_panel.notice_dismiss_requested.connect(self._on_notice_dismiss)
        self.chat_panel.clear_requested.connect(self._on_clear)
        self.chat_panel.compact_requested.connect(self._on_compact_requested)
        self.presets_panel.preset_run.connect(self._on_preset_run)
        self.presets_panel.preset_paste.connect(self._on_preset_paste)

        # App signals
        self.signals.screenshot_captured.connect(self._on_new_screenshot)
        self.signals.screenshot_deleted.connect(self.screenshots_panel.remove)
        self.signals.preset_saved.connect(lambda _: self.presets_panel.reload())
        self.signals.preset_deleted.connect(lambda _: self.presets_panel.reload())

        # ChatController signals — the panel just visualises what the
        # controller broadcasts, so closing/reopening this window never
        # loses a reply.
        self.chat.reply_started.connect(self._on_reply_started)
        self.chat.reply_chunk.connect(self._on_reply_chunk)
        self.chat.reply_completed.connect(self._on_reply_completed)
        self.chat.reply_failed.connect(self._on_reply_failed)
        self.chat.reply_cancelled.connect(self._on_reply_cancelled)
        self.chat.history_changed.connect(self._on_history_changed)
        self.chat.notices_changed.connect(self._on_notices_changed)
        self.chat.compact_started.connect(self._on_compact_started)
        self.chat.compact_completed.connect(self._on_compact_completed)
        self.chat.compact_failed.connect(self._on_compact_failed)

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
        super().changeEvent(event)
        try:
            self.title_bar.refresh_max_glyph()
        except AttributeError:
            pass

    def closeEvent(self, event) -> None:  # type: ignore[override]
        # NOTE: never cancel a running completion here — the controller
        # owns those tasks and they finish independently of us.
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
            self.chat_panel.set_context(None)
            self.chat_panel.set_status(self.chat_panel.STATUS_IDLE)
            self.title_bar.set_title("ExplainShot")
            return
        # Header: filename + resolution + file size in the context row
        context = (
            f"{record.filename}  ·  {record.width}×{record.height}  ·  {_humanise_size(record.size_bytes)}"
        )
        self.chat_panel.set_context(context)
        self.title_bar.set_title(f"ExplainShot — {record.filename}")

        # Rehydrate transcript and pick up any in-progress reply already
        # running for this screenshot.
        self._refresh_transcript()
        progress = self.chat.in_progress(record.id)
        if progress is not None:
            placeholder = MessageNode(
                id=-1, parent_id=progress.parent_id, role="assistant",
                content=progress.text, model=None, created_at=progress.started_at,
                siblings=None, index_in_siblings=0,
            )
            self.chat_panel.begin_streaming(placeholder)
            if progress.text:
                # We already have some text buffered — render it.
                self.chat_panel._streaming_row.bubble.set_content(progress.text)  # type: ignore[union-attr]
                self.chat_panel._streaming_row.bubble.set_thinking(False)         # type: ignore[union-attr]
        elif self.chat.is_compacting(record.id):
            self.chat_panel.set_status(self.chat_panel.STATUS_COMPACTING)
        else:
            self.chat_panel.set_status(self.chat_panel.STATUS_IDLE)
        # Busy reflects any in-flight AI job on the newly-selected screenshot
        # (reply OR compaction). Selecting a different screenshot switches
        # the view — the previous screenshot's job continues running.
        self.chat_panel.set_busy(self.chat.is_busy(record.id))
        self._refresh_gauge()

    def _refresh_transcript(self) -> None:
        """Fully rebuild the panel from persisted state for the current
        screenshot — messages *and* system notices. This is called on
        selection change and on every history/notice signal so the panel
        can never drift or leak state from a previous screenshot."""
        if self._selected is None:
            self.chat_panel.clear()
            return
        path = self.history.active_path(self._selected.id)
        notices = self.chat.notices(self._selected.id)
        self.chat_panel.render(path, notices)

    def _on_new_screenshot(self, record: ScreenshotRecord) -> None:
        self.screenshots_panel.add_or_update(record)

    def _on_preview_requested(self, screenshot_id: str) -> None:
        record = self.screenshots.get(screenshot_id)
        if not record:
            return
        window = PreviewWindow(record.path, record.filename)
        window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        window.destroyed.connect(
            lambda _=None, w=window: self._preview_windows.remove(w) if w in self._preview_windows else None
        )
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

    # -- user actions in the chat -> controller ------------------------------

    def _on_prompt_submitted(self, prompt: str) -> None:
        if not self._selected:
            return
        self.chat.submit(self._selected.id, self._selected.path, prompt)

    def _on_edit_submitted(self, source_id: int, new_content: str) -> None:
        if not self._selected:
            return
        self.chat.resubmit_edited(self._selected.id, self._selected.path, source_id, new_content)

    def _on_regenerate_requested(self, assistant_id: int) -> None:
        if not self._selected:
            return
        self.chat.regenerate(self._selected.id, self._selected.path, assistant_id)

    def _on_delete_requested(self, message_id: int) -> None:
        if not self._selected:
            return
        self.chat.delete_message(self._selected.id, message_id)

    def _on_branch_switch(self, message_id: int, direction: int) -> None:
        if not self._selected:
            return
        current = self.db.get_message(message_id)
        if not current:
            return
        siblings = [row["id"] for row in self.db.list_children(self._selected.id, current["parent_id"])]
        try:
            index = siblings.index(message_id)
        except ValueError:
            return
        new_index = index + direction
        if not (0 <= new_index < len(siblings)):
            return
        self.chat.switch_branch(self._selected.id, siblings[new_index])

    def _on_clear(self) -> None:
        if not self._selected:
            return
        self.chat.clear(self._selected.id)

    # -- preset actions --------------------------------------------------------

    def _on_preset_run(self, preset_id: str) -> None:
        preset = self.presets.get(preset_id)
        if not preset or not self._selected:
            return
        self.presets.record_use(preset_id)
        self.chat.submit(self._selected.id, self._selected.path, preset.prompt)

    def _on_preset_paste(self, preset_id: str) -> None:
        preset = self.presets.get(preset_id)
        if preset:
            self.chat_panel.replace_prompt(preset.prompt)

    # -- controller signals -> panel -----------------------------------------

    def _on_reply_started(self, screenshot_id: str, parent_id: int) -> None:
        if not self._selected or self._selected.id != screenshot_id:
            return
        placeholder = MessageNode(
            id=-1, parent_id=parent_id if parent_id != -1 else None,
            role="assistant", content="", model=None,
            created_at=__import__("datetime").datetime.now(),
            siblings=None, index_in_siblings=0,
        )
        self.chat_panel.begin_streaming(placeholder)
        self.chat_panel.set_busy(True)

    def _on_reply_chunk(self, screenshot_id: str, delta: str) -> None:
        if not self._selected or self._selected.id != screenshot_id:
            return
        self.chat_panel.append_stream(delta)

    def _on_reply_completed(self, screenshot_id: str, reply: str, _new_id: int) -> None:
        if not self._selected or self._selected.id != screenshot_id:
            return
        # Persisted; rebuild from history so the new turn has its real id.
        self.chat_panel.end_streaming(reply)
        # If auto-compact is about to fire, the controller will re-set busy.
        # For now assume idle; compact_started will overwrite this.
        self.chat_panel.set_busy(self.chat.is_busy(screenshot_id))
        if not self.chat.is_compacting(screenshot_id):
            self.chat_panel.set_status(self.chat_panel.STATUS_IDLE)
        self._refresh_gauge()
        self._refresh_transcript()

    def _on_reply_failed(self, screenshot_id: str, _error: str) -> None:
        if not self._selected or self._selected.id != screenshot_id:
            return
        # The controller has already persisted a notice for this failure;
        # notices_changed will fire and re-render the transcript. All we
        # do here is drop the empty streaming placeholder + set the chip.
        self.chat_panel.cancel_streaming()
        self.chat_panel.set_busy(False)
        self.chat_panel.set_status(self.chat_panel.STATUS_ERROR)

    def _on_reply_cancelled(self, screenshot_id: str) -> None:
        if not self._selected or self._selected.id != screenshot_id:
            return
        self.chat_panel.cancel_streaming()
        self.chat_panel.set_busy(False)
        self.chat_panel.set_status(self.chat_panel.STATUS_CANCELLED)

    def _on_history_changed(self, screenshot_id: str) -> None:
        if not self._selected or self._selected.id != screenshot_id:
            return
        self._refresh_transcript()
        self._refresh_gauge()

    def _on_notices_changed(self, screenshot_id: str) -> None:
        if not self._selected or self._selected.id != screenshot_id:
            return
        self._refresh_transcript()

    def _on_notice_dismiss(self, notice_id: int) -> None:
        if not self._selected:
            return
        self.chat.dismiss_notice(self._selected.id, notice_id)

    def _on_compact_requested(self) -> None:
        if not self._selected:
            return
        self.chat.compact(self._selected.id, self._selected.path)

    def _on_compact_started(self, screenshot_id: str) -> None:
        if not self._selected or self._selected.id != screenshot_id:
            return
        self.chat_panel.set_busy(True)
        self.chat_panel.set_status(self.chat_panel.STATUS_COMPACTING)

    def _on_compact_completed(self, screenshot_id: str) -> None:
        if not self._selected or self._selected.id != screenshot_id:
            return
        self.chat_panel.set_busy(False)
        self.chat_panel.set_status(self.chat_panel.STATUS_IDLE)
        self._refresh_gauge()

    def _on_compact_failed(self, screenshot_id: str, _error: str) -> None:
        if not self._selected or self._selected.id != screenshot_id:
            return
        self.chat_panel.set_busy(False)
        self.chat_panel.set_status(self.chat_panel.STATUS_ERROR)
        self._refresh_gauge()

    def _refresh_gauge(self) -> None:
        if self._selected is None:
            return
        self.chat_panel.set_context_usage(self.chat.context_usage(self._selected.id))

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
