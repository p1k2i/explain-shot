"""Gallery window.

Layout: custom title bar over a three-column body — screenshots, chat,
presets. The window is a *view* over the app's `ChatController` and
`ChatHistory`: it visualises state, forwards user input, and rebuilds
the transcript on demand. It never owns an in-flight completion, so
closing the window or switching screenshots never drops a reply.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QEvent, QTimer, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import (
    QApplication,
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
from ...config.settings import Settings, update_setting
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
        # Adequate minimum: below this the three columns start clipping their
        # controls (the chat's input button row is the tightest). Per-column
        # minimum widths are set on the splitter children just below.
        self.setMinimumSize(720, 460)

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

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(6)

        self.screenshots_panel = ScreenshotsPanel(
            self.screenshots, self.thumbnails, settings.ui.thumbnail_px,
            settings.ui.gallery_view,
        )
        self.splitter.addWidget(self._wrap(self.screenshots_panel))

        self.chat_panel = ChatPanel()
        self.splitter.addWidget(self._wrap(self.chat_panel))

        self.presets_panel = PresetsPanel(self.presets)
        self.splitter.addWidget(self._wrap(self.presets_panel))

        self.splitter.setStretchFactor(0, 4)
        self.splitter.setStretchFactor(1, 5)
        self.splitter.setStretchFactor(2, 3)
        # Per-column minimum widths so a drag (or a small window) can't crush a
        # panel below the point its controls stay usable. The chat is widest —
        # its input button row (gauge + Compact + Clear + Send) sets the floor.
        for i, min_w in ((0, 180), (1, 300), (2, 200)):
            w = self.splitter.widget(i)
            if w is not None:
                w.setMinimumWidth(min_w)
        self.splitter.setSizes([460, 560, 340])
        # Restore the user's saved column widths (see _restore_splitter).
        self._restore_splitter()
        body_layout.addWidget(self.splitter)

        root.addWidget(body, 1)

        self._selected: ScreenshotRecord | None = None
        self._preview_windows: list[PreviewWindow] = []
        self._did_initial_focus = False

        # Wire panels
        self.screenshots_panel.selection_changed.connect(self._on_selection)
        self.screenshots_panel.preview_requested.connect(self._on_preview_requested)
        self.screenshots_panel.delete_requested.connect(self._on_screenshot_delete)
        self.screenshots_panel.rename_requested.connect(self._on_screenshot_rename)
        self.screenshots_panel.prefs_changed.connect(self._on_gallery_prefs_changed)
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

        # Tab / Shift+Tab switch between the three sections instead of walking
        # every control (arrows navigate *inside* a section). We intercept at
        # the application level, scoped to focus within this window, so it never
        # touches dialogs (separate top-levels) or the settings/preview windows.
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    # -- lifecycle -------------------------------------------------------------

    def eventFilter(self, obj, event) -> bool:  # type: ignore[override]
        if event is not None and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
                mods = event.modifiers()
                # Plain Tab / Shift+Tab only (leave Ctrl/Alt+Tab to the OS/app).
                if not (mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)):
                    focus = QApplication.focusWidget()
                    if focus is not None and self.isAncestorOf(focus):
                        forward = key == Qt.Key.Key_Tab and not (mods & Qt.KeyboardModifier.ShiftModifier)
                        self._cycle_group(forward=forward)
                        return True
        return super().eventFilter(obj, event)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        added = self.screenshots.scan_directory()
        if added:
            self.screenshots_panel.reload()
        self.title_bar.refresh_max_glyph()
        # Put keyboard focus somewhere deterministic on first show (the
        # screenshots grid), so Tab/arrows behave predictably from the start
        # instead of landing on whatever toolbar control Qt picked first.
        if not self._did_initial_focus:
            self._did_initial_focus = True
            QTimer.singleShot(0, self._focus_initial)

    def _focus_initial(self) -> None:
        self._cycle_group(forward=True)   # lands on the first focusable group

    def changeEvent(self, event) -> None:  # type: ignore[override]
        super().changeEvent(event)
        try:
            self.title_bar.refresh_max_glyph()
        except AttributeError:
            pass

    def closeEvent(self, event) -> None:  # type: ignore[override]
        # NOTE: never cancel a running completion here — the controller
        # owns those tasks and they finish independently of us.
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        try:
            self.db.save_window_state("gallery", bytes(self.saveGeometry()), self.isMaximized())
            # Column widths ride in their own window_state row (no schema change).
            self.db.save_window_state("gallery_splitter", bytes(self.splitter.saveState()), False)
        except Exception:
            log.debug("could not save window state", exc_info=True)
        super().closeEvent(event)

    def _restore_splitter(self) -> None:
        """Reapply the user's saved column widths, if any."""
        try:
            state = self.db.load_window_state("gallery_splitter")
            if state and state[0]:
                self.splitter.restoreState(state[0])
        except Exception:
            log.debug("could not restore splitter state", exc_info=True)

    def keyPressEvent(self, event: QKeyEvent | None) -> None:  # type: ignore[override]
        if event is not None:
            key = event.key()
            mods = event.modifiers()
            ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
            if key == Qt.Key.Key_F5:
                self.thumbnails.clear()
                self.screenshots_panel.reload()
                return
            if key == Qt.Key.Key_Escape:
                self.close()
                return
            if ctrl and key == Qt.Key.Key_K:
                self._on_clear()
                return
            # F6 mirrors Tab (cycle groups); Ctrl+1/2/3 jump to the three lists.
            if key == Qt.Key.Key_F6:
                self._cycle_group(forward=not (mods & Qt.KeyboardModifier.ShiftModifier))
                return
            if ctrl and key in (Qt.Key.Key_1, Qt.Key.Key_2, Qt.Key.Key_3):
                # groups: 0 screenshots list, 2 chat editor, 4 presets list
                self._focus_group({Qt.Key.Key_1: 0, Qt.Key.Key_2: 2, Qt.Key.Key_3: 4}[key])
                return
        super().keyPressEvent(event)

    # -- keyboard group navigation --------------------------------------------
    #
    # Six Tab-groups; Tab/Shift+Tab move between them, arrows navigate inside.
    #   0 screenshots list        1 screenshots nav (view/size/refresh)
    #   2 chat text field         3 chat buttons (Compact/Clear/Send)
    #   4 presets list            5 presets nav (+ New)

    def _groups(self) -> list[tuple]:
        sp, cp, pp = self.screenshots_panel, self.chat_panel, self.presets_panel
        return [
            (sp.focus_grid,    sp.owns_grid_focus),
            (sp.focus_toolbar, sp.owns_toolbar_focus),
            (cp.focus_editor,  cp.owns_editor_focus),
            (cp.focus_buttons, cp.owns_buttons_focus),
            (pp.focus_list,    pp.owns_list_focus),
            (pp.focus_nav,     pp.owns_nav_focus),
        ]

    def _focus_group(self, index: int) -> bool:
        return bool(self._groups()[index][0]())

    def _current_group_index(self) -> int:
        widget = QApplication.focusWidget()
        if widget is None:
            return -1
        for i, (_enter, owns) in enumerate(self._groups()):
            if owns(widget):
                return i
        return -1

    def _cycle_group(self, *, forward: bool) -> None:
        groups = self._groups()
        n = len(groups)
        current = self._current_group_index()
        if current < 0:
            order = list(range(n)) if forward else list(range(n - 1, -1, -1))
        else:
            step = 1 if forward else -1
            order = [(current + step * k) % n for k in range(1, n + 1)]
        # Land on the first group that can take focus (skips a disabled chat or
        # an empty list), so Tab never appears to do nothing.
        for idx in order:
            if groups[idx][0]():
                return

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

    def _on_gallery_prefs_changed(self, view_mode: str, thumb_px: int) -> None:
        """Persist the gallery's view mode / thumbnail size when the user
        changes them from the panel toolbar. We keep the shared in-memory
        Settings in sync too so the settings window and next launch agree."""
        self.settings.ui.gallery_view = view_mode
        self.settings.ui.thumbnail_px = thumb_px
        update_setting("ui.gallery_view", view_mode)
        update_setting("ui.thumbnail_px", thumb_px)

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
        # Release the input unconditionally: reply_completed is emitted
        # *inside* the running task (before its done-callback pops it from
        # ChatController._jobs), so is_busy() still says True right here
        # and would leave the input locked forever. Auto-compaction, if it
        # fires, re-locks via its own compact_started signal a moment later.
        self.chat_panel.set_busy(False)
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
