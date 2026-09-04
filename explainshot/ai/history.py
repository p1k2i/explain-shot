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

        The FULL conversation is included — every user and assistant turn on
        the active branch from the root to the tip. We never truncate; if
        the model can't handle the size that's the model's problem to report.

        When `cutoff_message_id` is provided we stop AFTER that message. Used
        for regeneration: we're about to create a new sibling under a user
        turn, so the old assistant sibling below it must NOT be sent — else
        the model sees its previous answer and just repeats.
        """
        history = self.active_path(screenshot_id)
        if cutoff_message_id is not None:
            for i, msg in enumerate(history):
                if msg.id == cutoff_message_id:
                    history = history[: i + 1]
                    break
        out: list[ChatMessage] = []
        if system:
            out.append(ChatMessage(role="system", content=system))
        last_user_index = -1
        for i, msg in enumerate(history):
            if msg.role == "user":
                last_user_index = i
        for i, msg in enumerate(history):
            images = [image_path] if (image_path and i == last_user_index) else []
            out.append(ChatMessage(role=msg.role, content=msg.content, image_paths=images))
        return out

    # -- helpers ---------------------------------------------------------------

    def _tail_id(self, screenshot_id: str) -> int | None:
        path = self.active_path(screenshot_id)
        return path[-1].id if path else None
