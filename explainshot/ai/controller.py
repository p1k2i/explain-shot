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
from contextlib import aclosing
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from PyQt6.QtCore import QObject, pyqtSignal

from .history import ChatHistory
from .provider import AIError, AIProvider, ChatMessage

log = logging.getLogger(__name__)


SYSTEM_PROMPT = (
    "You are ExplainShot, a helpful assistant that describes and answers "
    "questions about the screenshot the user just captured. Be direct and specific."
)

COMPACT_PROMPT = (
    "You are compacting an ongoing conversation into a short reference so it "
    "can continue past the model's context window. Produce a concise summary "
    "in plain prose covering, in this order:\n"
    "1. What the user is trying to do with the screenshot.\n"
    "2. Key facts, values, names, or code the assistant has already established.\n"
    "3. Decisions or preferences the user has stated.\n"
    "4. The current state of the conversation (what was just discussed).\n\n"
    "Do NOT restate every turn. Do NOT add greetings or filler. "
    "Preserve any specific identifiers, numbers, or code exactly. "
    "The output replaces the earlier turns in future prompts, so anything "
    "you omit is lost."
)


@dataclass
class InProgress:
    """Snapshot of a running reply. `parent_id` is the id of the user turn
    the reply forks from; `text` is what has streamed so far."""
    screenshot_id: str
    parent_id: int | None
    text: str = ""
    started_at: datetime = field(default_factory=datetime.now)


@dataclass(frozen=True)
class SystemNotice:
    """A visible-in-transcript, invisible-to-LLM message scoped to a
    screenshot. Persists in the DB so reopening the app or switching
    screenshots shows the correct set of notices."""
    id: int
    kind: str            # "error" | "info"
    message: str
    created_at: datetime


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
    notices_changed = pyqtSignal(str)           # screenshot_id — notices added/removed
    compact_started = pyqtSignal(str)           # screenshot_id — compaction begins
    compact_completed = pyqtSignal(str)         # screenshot_id — compaction landed
    compact_failed = pyqtSignal(str, str)       # screenshot_id, error

    def __init__(
        self,
        history: ChatHistory,
        provider_factory: Callable[[], AIProvider],
        *,
        context_chars_limit: int = 24000,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.history = history
        self.provider_factory = provider_factory
        self.context_chars_limit = max(2000, int(context_chars_limit))
        self._jobs: dict[str, asyncio.Task] = {}
        self._progress: dict[str, InProgress] = {}
        self._compact_jobs: dict[str, asyncio.Task] = {}

    def set_context_chars_limit(self, limit: int) -> None:
        self.context_chars_limit = max(2000, int(limit))

    # -- introspection ---------------------------------------------------------

    def is_busy(self, screenshot_id: str) -> bool:
        """Any AI work in flight for this screenshot (reply or compaction).
        The UI uses this to disable the send button."""
        return screenshot_id in self._jobs or screenshot_id in self._compact_jobs

    def is_compacting(self, screenshot_id: str) -> bool:
        return screenshot_id in self._compact_jobs

    def in_progress(self, screenshot_id: str) -> InProgress | None:
        return self._progress.get(screenshot_id)

    def context_usage(self, screenshot_id: str) -> float:
        """0.0–1.0 fraction of the compact threshold currently in play on
        the next LLM request. Includes the compact summary itself — after
        a compact the summary IS the context, so the gauge should reflect
        its weight rather than reading zero."""
        if self.context_chars_limit <= 0:
            return 0.0
        used = self.history.context_chars(screenshot_id)
        return min(1.0, used / self.context_chars_limit)

    def notices(self, screenshot_id: str) -> list[SystemNotice]:
        return [
            SystemNotice(
                id=row["id"],
                kind=row["kind"],
                message=row["message"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in self.history.db.list_notices(screenshot_id)
        ]

    def add_notice(self, screenshot_id: str, kind: str, message: str) -> None:
        self.history.db.add_notice(screenshot_id, kind, message)
        self.notices_changed.emit(screenshot_id)

    def dismiss_notice(self, screenshot_id: str, notice_id: int) -> None:
        self.history.db.delete_notice(notice_id)
        self.notices_changed.emit(screenshot_id)

    def clear_notices(self, screenshot_id: str) -> None:
        self.history.db.clear_notices(screenshot_id)
        self.notices_changed.emit(screenshot_id)

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
        self.history.db.clear_notices(screenshot_id)
        self.history_changed.emit(screenshot_id)
        self.notices_changed.emit(screenshot_id)

    def cancel(self, screenshot_id: str) -> None:
        task = self._jobs.get(screenshot_id)
        if task is not None and not task.done():
            task.cancel()

    # -- compaction ------------------------------------------------------------

    def compact(self, screenshot_id: str, image_path: str) -> None:
        """Kick off a manual compaction. If one is already running for this
        screenshot, this is a no-op — the existing task will finish first."""
        if screenshot_id in self._compact_jobs:
            return
        provider = self.provider_factory()
        task = asyncio.ensure_future(self._run_compact(screenshot_id, image_path, provider))
        self._compact_jobs[screenshot_id] = task
        task.add_done_callback(lambda t, sid=screenshot_id: self._compact_jobs.pop(sid, None))
        self.compact_started.emit(screenshot_id)

    async def _run_compact(self, screenshot_id: str, image_path: str, provider: AIProvider) -> None:
        try:
            tail = self.history.uncompacted_tail(screenshot_id)
            previous = self.history.latest_compact(screenshot_id)
            # We need SOMETHING new to work with — either fresh turns since
            # the last compact, or a previous summary we can distil further.
            if not tail and previous is None:
                return
            if len(tail) < 2 and previous is None:
                return

            # Compaction context:
            #   [COMPACT_PROMPT]  (system rules for the summariser)
            #   [previous summary, if any, as a "previous summary" system msg]
            #   [every un-compacted user/assistant turn since that summary]
            # This lets summaries build on summaries — we never re-send the
            # raw pre-compact turns because they're already folded into the
            # previous summary. That's what makes long-running conversations
            # affordable.
            messages: list[ChatMessage] = [ChatMessage(role="system", content=COMPACT_PROMPT)]
            if previous is not None:
                messages.append(ChatMessage(
                    role="system",
                    content=(
                        "Previous summary of the conversation so far — fold "
                        "this into your new summary alongside the turns below:"
                        "\n\n" + previous.content
                    ),
                ))
            for msg in tail:
                messages.append(ChatMessage(role=msg.role, content=msg.content))

            log.info(
                "compact -> %s: summarising %d turn(s) + %s prior summary (%d chars total)",
                screenshot_id[:8], len(tail),
                "1" if previous is not None else "no",
                sum(len(m.content) for m in messages[1:]),
            )
            summary = await provider.chat(messages)
            if not summary.strip():
                raise RuntimeError("The compaction model returned an empty summary.")
            new_id = self.history.compact_from_tip(screenshot_id, summary.strip())
            log.info("compact -> %s: stored as message %d", screenshot_id[:8], new_id)
            # No system notice: the new "Summary of earlier conversation" row
            # in the transcript already communicates what happened.
            self.compact_completed.emit(screenshot_id)
            self.history_changed.emit(screenshot_id)
        except asyncio.CancelledError:
            self.compact_completed.emit(screenshot_id)
            raise
        except Exception as exc:
            log.exception("compaction failed")
            message = _friendlier_error(str(exc))
            self.history.db.add_notice(screenshot_id, "error", "Compaction failed: " + message)
            self.notices_changed.emit(screenshot_id)
            self.compact_failed.emit(screenshot_id, message)

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
            # Full conversation, minus anything AFTER the message we're
            # forking from. For a fresh submit that's the tip (no truncation);
            # for regeneration that stops before the assistant sibling we're
            # about to replace.
            messages = self.history.to_prompt(
                screenshot_id,
                image_path=image_path,
                system=SYSTEM_PROMPT,
                cutoff_message_id=state.parent_id,
            )
            turns = sum(1 for m in messages if m.role != "system")
            char_count = sum(len(m.content) for m in messages)
            log.info(
                "chat -> %s: sending %d turn(s) (%d chars) to model %s",
                screenshot_id[:8], turns, char_count, provider.model,
            )
            collected: list[str] = []
            # aclosing() guarantees the underlying httpx generator is closed
            # explicitly on early termination (cancellation, break, exception).
            # Without it httpcore prints "async generator ignored GeneratorExit"
            # when the task is cancelled mid-stream — its inner byte-stream
            # generator can't release the connection synchronously.
            try:
                async with aclosing(provider.stream(messages)) as stream:
                    async for chunk in stream:
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
                message = "The model returned an empty response."
                self.history.db.add_notice(screenshot_id, "error", message)
                self.notices_changed.emit(screenshot_id)
                self.reply_failed.emit(screenshot_id, message)
                return
            new_id = self.history.fork_from(
                screenshot_id, state.parent_id, "assistant", reply, model=provider.model,
            )
            self.reply_completed.emit(screenshot_id, reply, new_id)
            self.history_changed.emit(screenshot_id)
            # Auto-compact after a successful turn if we've crossed the
            # configured character threshold. Compaction runs as its own
            # task; the UI observes compact_started to lock input.
            if self.context_usage(screenshot_id) >= 1.0:
                self.compact(screenshot_id, image_path)
        except asyncio.CancelledError:
            self.history.db.add_notice(screenshot_id, "info", "Reply cancelled.")
            self.notices_changed.emit(screenshot_id)
            self.reply_cancelled.emit(screenshot_id)
            raise
        except Exception as exc:
            log.exception("chat completion failed")
            message = _friendlier_error(str(exc))
            self.history.db.add_notice(screenshot_id, "error", message)
            self.notices_changed.emit(screenshot_id)
            self.reply_failed.emit(screenshot_id, message)
        finally:
            self._progress.pop(screenshot_id, None)


_CONTEXT_LENGTH_MARKERS = (
    "context length",
    "context_length_exceeded",
    "maximum context",
    "maximum tokens",
    "too many tokens",
    "prompt is too long",
    "exceeds the model",
)


def _friendlier_error(raw: str) -> str:
    """Detect a few common upstream error phrasings and rewrite them into
    a plainer sentence the user can act on. Falls through unchanged for
    anything we don't recognise."""
    lower = raw.lower()
    if any(marker in lower for marker in _CONTEXT_LENGTH_MARKERS):
        return (
            "The conversation is too long for this model's context window. "
            "Start a new chat (Clear) or switch to a model with a larger "
            "context.\n\nRaw error: " + raw
        )
    return raw
