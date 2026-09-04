"""Per-screenshot chat history as a branching tree, ChatGPT style.

Each screenshot has a conversation tree stored in `chat_messages`. The
timeline you see in the UI is one path from root to a leaf — the active
branch — chosen by `chat_active_branch`. When the user edits or regenerates
a message we fork: create a new sibling under the same parent and point
the active-branch pointer at it. The old sibling still exists and the user
can flip back.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..core.database import Database
from .provider import ChatMessage


@dataclass
class MessageNode:
    id: int
    parent_id: int | None
    role: str
    content: str
    model: str | None
    created_at: datetime
    # Populated by ChatHistory.active_path so the UI can render branch controls.
    siblings: list[int] = None  # type: ignore[assignment]
    index_in_siblings: int = 0

    def has_siblings(self) -> bool:
        return self.siblings is not None and len(self.siblings) > 1


class ChatHistory:
    def __init__(self, db: Database) -> None:
        self.db = db

    # -- reading ---------------------------------------------------------------

    def active_path(self, screenshot_id: str) -> list[MessageNode]:
        """The message sequence currently shown to the user: from the active
        root child to the tip of the active branch."""
        path: list[MessageNode] = []
        parent_id: int | None = None
        while True:
            children = self.db.list_children(screenshot_id, parent_id)
            if not children:
                break
            # Prefer the last active child; fall back to the newest.
            active = self.db.get_active_child(screenshot_id, parent_id)
            picked_row = next((c for c in children if c["id"] == active), children[-1])
            sibling_ids = [c["id"] for c in children]
            picked = MessageNode(
                id=picked_row["id"],
                parent_id=picked_row["parent_id"],
                role=picked_row["role"],
                content=picked_row["content"],
                model=picked_row["model"],
                created_at=datetime.fromisoformat(picked_row["created_at"]),
                siblings=sibling_ids,
                index_in_siblings=sibling_ids.index(picked_row["id"]),
            )
            path.append(picked)
            parent_id = picked_row["id"]
        return path

    def sibling_ids(self, screenshot_id: str, parent_id: int | None) -> list[int]:
        return [row["id"] for row in self.db.list_children(screenshot_id, parent_id)]

    # -- writing ---------------------------------------------------------------

    def append_root(self, screenshot_id: str, role: str, content: str, *, model: str | None = None) -> int:
        """Append a message at the tip of the current active branch. Callers
        that need to fork a specific parent should use `fork_from` instead."""
        tail = self._tail_id(screenshot_id)
        return self.db.add_message(
            screenshot_id, role, content, parent_id=tail, model=model,
        )

    def fork_from(
        self,
        screenshot_id: str,
        parent_id: int | None,
        role: str,
        content: str,
        *,
        model: str | None = None,
    ) -> int:
        """Create a new child of `parent_id` and activate that branch."""
        return self.db.add_message(
            screenshot_id, role, content, parent_id=parent_id, model=model,
        )

    def switch_branch(self, screenshot_id: str, message_id: int) -> None:
        """Activate `message_id` — makes it the visible child at its parent."""
        msg = self.db.get_message(message_id)
        if not msg:
            return
        self.db.set_active_child(screenshot_id, msg["parent_id"], message_id)

    def delete_subtree(self, screenshot_id: str, message_id: int) -> None:
        """Remove `message_id` and all its descendants. If a sibling exists,
        activate the previous one; otherwise unset the parent's pointer."""
        msg = self.db.get_message(message_id)
        if not msg:
            return
        parent_id = msg["parent_id"]
        # Snapshot sibling order + our position BEFORE the deletion.
        children_before = [row["id"] for row in self.db.list_children(screenshot_id, parent_id)]
        try:
            index = children_before.index(message_id)
        except ValueError:
            index = 0
        self.db.delete_message_subtree(message_id)
        surviving = [i for i in children_before if i != message_id]
        if surviving:
            new_active = surviving[max(index - 1, 0)] if index > 0 else surviving[0]
            self.db.set_active_child(screenshot_id, parent_id, new_active)

    def clear(self, screenshot_id: str) -> None:
        self.db.clear_messages(screenshot_id)

    # -- rendering for the model ---------------------------------------------

    def to_prompt(
        self,
        screenshot_id: str,
        *,
        image_path: str | None = None,
        system: str | None = None,
        cutoff_message_id: int | None = None,
    ) -> list[ChatMessage]:
        """Convert the active branch into a list ready to send to the AI.

        The full un-compacted conversation is sent. If the branch contains
        a `compact` message (a summary of everything before it), we send
        [system, compact-as-system, messages-after-compact...] — the
        pre-compact turns stay visible in the UI as history but never
        cross the wire.

        `cutoff_message_id` truncates the path AFTER that message. Used by
        regeneration so an old assistant sibling doesn't sneak into the
        prompt for its own replacement.
        """
        history = self.active_path(screenshot_id)
        if cutoff_message_id is not None:
            for i, msg in enumerate(history):
                if msg.id == cutoff_message_id:
                    history = history[: i + 1]
                    break

        # Find the newest compact on the path; everything before it is
        # already summarised and shouldn't be re-sent.
        compact_index = -1
        for i, msg in enumerate(history):
            if msg.role == "compact":
                compact_index = i

        out: list[ChatMessage] = []
        if system:
            out.append(ChatMessage(role="system", content=system))
        if compact_index >= 0:
            summary = history[compact_index].content
            out.append(ChatMessage(
                role="system",
                content=(
                    "Summary of the earlier conversation you're continuing:\n\n"
                    + summary
                ),
            ))
            tail = history[compact_index + 1:]
        else:
            tail = history

        last_user_index = -1
        for i, msg in enumerate(tail):
            if msg.role == "user":
                last_user_index = i
        for i, msg in enumerate(tail):
            if msg.role == "compact":
                continue  # Shouldn't happen (only one compact per tail) but be safe.
            images = [image_path] if (image_path and i == last_user_index) else []
            out.append(ChatMessage(role=msg.role, content=msg.content, image_paths=images))
        return out

    # -- context accounting ---------------------------------------------------

    def uncompacted_tail(self, screenshot_id: str) -> list[MessageNode]:
        """Messages on the active path since (and not including) the latest
        compact. This is what would be sent to the LLM on the next request,
        modulo the system prompt."""
        history = self.active_path(screenshot_id)
        for i in range(len(history) - 1, -1, -1):
            if history[i].role == "compact":
                return history[i + 1:]
        return history

    def latest_compact(self, screenshot_id: str) -> MessageNode | None:
        """Newest compact on the active branch, if any. Used when compacting
        again — the fresh compact should build on the previous summary rather
        than re-reading every raw turn."""
        for node in reversed(self.active_path(screenshot_id)):
            if node.role == "compact":
                return node
        return None

    def chars_since_compact(self, screenshot_id: str) -> int:
        """Length of the un-compacted tail only. Used by _run_compact to
        decide whether we have anything new worth summarising."""
        return sum(len(m.content) for m in self.uncompacted_tail(screenshot_id))

    def context_chars(self, screenshot_id: str) -> int:
        """Bytes actually shipped to the model on the next request.
        Includes the current compact summary (if any) because that content
        rides on every request as system context — right after a compact
        the gauge should reflect the summary's weight, not zero."""
        total = self.chars_since_compact(screenshot_id)
        compact = self.latest_compact(screenshot_id)
        if compact is not None:
            total += len(compact.content)
        return total

    def compact_from_tip(self, screenshot_id: str, summary_text: str) -> int:
        """Attach a compact message at the current tip of the active branch."""
        path = self.active_path(screenshot_id)
        tip_id = path[-1].id if path else None
        return self.db.add_message(screenshot_id, "compact", summary_text, parent_id=tip_id)

    # -- helpers ---------------------------------------------------------------

    def _tail_id(self, screenshot_id: str) -> int | None:
        path = self.active_path(screenshot_id)
        return path[-1].id if path else None
