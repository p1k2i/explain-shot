"""Headless chat controller.

Owns every in-flight AI reply. The gallery window is a *view* onto this
controller — it does not run the tasks itself. Concretely that means:

  * closing the gallery does not cancel an in-flight completion; the
    reply lands in ChatHistory (and thus the DB) regardless.
  * switching to a different screenshot doesn't drop a reply that was
    being generated for the previous one.
  * a window that opens after a reply finishes still sees the reply
    (it's already been appended to history via ChatHistory.fork_from).

State model
-----------
For each screenshot the controller may have zero or one active job. The
job carries the parent id that the assistant reply will be attached to,
plus the buffer of chunks streamed so far. Consumers (windows) can call
``in_progress(screenshot_id)`` at any time to snapshot the current state.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from PyQt6.QtCore import QObject, pyqtSignal

from .history import ChatHistory
from .provider import AIError, AIProvider

log = logging.getLogger(__name__)


SYSTEM_PROMPT = (
    "You are ExplainShot, a helpful assistant that describes and answers "
    "questions about the screenshot the user just captured. Be direct and specific."
)


@dataclass
class InProgress:
    """Snapshot of a running reply. `parent_id` is the id of the user turn
    the reply forks from; `text` is what has streamed so far."""
    screenshot_id: str
    parent_id: int | None
    text: str = ""
    started_at: datetime = field(default_factory=datetime.now)


class ChatController(QObject):
    """UI-agnostic owner of running chat completions.

    Signals fire on the Qt main thread; multiple windows can connect to
    the same controller and stay in sync."""

    reply_started = pyqtSignal(str, int)        # screenshot_id, parent_id
    reply_chunk = pyqtSignal(str, str)          # screenshot_id, delta
    reply_completed = pyqtSignal(str, str, int) # screenshot_id, full text, new assistant message id
    reply_failed = pyqtSignal(str, str)         # screenshot_id, human-readable error
    reply_cancelled = pyqtSignal(str)           # screenshot_id
    history_changed = pyqtSignal(str)           # screenshot_id — user/assistant turns mutated

    def __init__(self, history: ChatHistory, provider_factory: Callable[[], AIProvider], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.history = history
        self.provider_factory = provider_factory
        self._jobs: dict[str, asyncio.Task] = {}
        self._progress: dict[str, InProgress] = {}

    # -- introspection ---------------------------------------------------------

    def is_busy(self, screenshot_id: str) -> bool:
        return screenshot_id in self._jobs

    def in_progress(self, screenshot_id: str) -> InProgress | None:
        return self._progress.get(screenshot_id)

    # -- user actions ----------------------------------------------------------

    def submit(self, screenshot_id: str, image_path: str, prompt: str) -> None:
        """Record a user turn and kick off an assistant reply."""
        self.history.append_root(screenshot_id, "user", prompt)
        self.history_changed.emit(screenshot_id)
        self._start_reply(screenshot_id, image_path, parent_id=None)

    def resubmit_edited(self, screenshot_id: str, image_path: str, source_message_id: int, new_content: str) -> None:
        """Edit a user turn: fork a new sibling under the same parent."""
        source = self.history.db.get_message(source_message_id)
        if source is None:
            return
        self.history.fork_from(screenshot_id, source["parent_id"], "user", new_content)
        self.history_changed.emit(screenshot_id)
        self._start_reply(screenshot_id, image_path, parent_id=None)

    def regenerate(self, screenshot_id: str, image_path: str, assistant_message_id: int) -> None:
        """Ask for a new assistant sibling under the same user turn."""
        assistant = self.history.db.get_message(assistant_message_id)
        if assistant is None or assistant["role"] != "assistant":
            return
        # After branch switch the "tip" for our new attempt is the user turn
        # (assistant's parent). Activate that user branch first so the prompt
        # rebuild picks the right context.
        parent_row = self.history.db.get_message(assistant["parent_id"]) if assistant["parent_id"] else None
        if parent_row is not None:
            self.history.switch_branch(screenshot_id, parent_row["id"])
        self._start_reply(screenshot_id, image_path, parent_id=assistant["parent_id"])

    def delete_message(self, screenshot_id: str, message_id: int) -> None:
        self.history.delete_subtree(screenshot_id, message_id)
        self.history_changed.emit(screenshot_id)

    def switch_branch(self, screenshot_id: str, message_id: int) -> None:
        self.history.switch_branch(screenshot_id, message_id)
        self.history_changed.emit(screenshot_id)

    def clear(self, screenshot_id: str) -> None:
        self.cancel(screenshot_id)
        self.history.clear(screenshot_id)
        self.history_changed.emit(screenshot_id)

    def cancel(self, screenshot_id: str) -> None:
        task = self._jobs.get(screenshot_id)
        if task is not None and not task.done():
            task.cancel()

    # -- runner ----------------------------------------------------------------

    def _start_reply(self, screenshot_id: str, image_path: str, *, parent_id: int | None) -> None:
        """Cancel any in-flight reply for the same screenshot, then kick off
        a new one. The task keeps running even if the window closes."""
        self.cancel(screenshot_id)

        # Reserve the parent — for a fresh submit this is the tip after the
        # user append; for regeneration it's the user turn we already know.
        if parent_id is None:
            path = self.history.active_path(screenshot_id)
            parent_id = path[-1].id if path else None

        provider = self.provider_factory()
        state = InProgress(screenshot_id=screenshot_id, parent_id=parent_id)
        self._progress[screenshot_id] = state

        task = asyncio.ensure_future(self._run(screenshot_id, image_path, provider, state))
        self._jobs[screenshot_id] = task
        task.add_done_callback(lambda t, sid=screenshot_id: self._jobs.pop(sid, None))
        self.reply_started.emit(screenshot_id, parent_id or -1)

    async def _run(self, screenshot_id: str, image_path: str, provider: AIProvider, state: InProgress) -> None:
        try:
            messages = self.history.to_prompt(
                screenshot_id,
                image_path=image_path,
                system=SYSTEM_PROMPT,
            )
            collected: list[str] = []
            try:
                async for chunk in provider.stream(messages):
                    if not chunk:
                        continue
                    collected.append(chunk)
                    state.text += chunk
                    self.reply_chunk.emit(screenshot_id, chunk)
            except AIError:
                raise
            reply = "".join(collected)
            # Some endpoints ignore stream=True — fall back so the user
            # doesn't see silence.
            if not reply.strip():
                log.info("stream yielded nothing for %s; retrying non-streaming", screenshot_id[:8])
                reply = await provider.chat(messages)
                if reply:
                    self.reply_chunk.emit(screenshot_id, reply)
                    state.text = reply
            if not reply.strip():
                self.reply_failed.emit(screenshot_id, "The model returned an empty response.")
                return
            new_id = self.history.fork_from(
                screenshot_id, state.parent_id, "assistant", reply, model=provider.model,
            )
            self.reply_completed.emit(screenshot_id, reply, new_id)
            self.history_changed.emit(screenshot_id)
        except asyncio.CancelledError:
            self.reply_cancelled.emit(screenshot_id)
            raise
        except Exception as exc:
            log.exception("chat completion failed")
            self.reply_failed.emit(screenshot_id, str(exc))
        finally:
            self._progress.pop(screenshot_id, None)
