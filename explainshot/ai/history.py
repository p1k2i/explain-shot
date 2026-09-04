"""Per-screenshot chat history, backed by the SQLite chat_messages table.

The old code kept chat history as a JSON file per screenshot on disk under
appdata/chat_history/. That was fine but duplicated storage responsibility
with the database and made cross-screenshot queries impossible. Now it lives
in one table, keyed by screenshot id.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..core.database import Database
from .provider import ChatMessage


@dataclass
class StoredMessage:
    id: int
    role: str
    content: str
    model: str | None
    created_at: datetime


class ChatHistory:
    def __init__(self, db: Database) -> None:
        self.db = db

    def append(
        self,
        screenshot_id: str,
        role: str,
        content: str,
        *,
        model: str | None = None,
    ) -> int:
        return self.db.add_message(screenshot_id, role, content, model=model)

    def load(self, screenshot_id: str) -> list[StoredMessage]:
        rows = self.db.list_messages(screenshot_id)
        return [
            StoredMessage(
                id=row["id"],
                role=row["role"],
                content=row["content"],
                model=row["model"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    def clear(self, screenshot_id: str) -> None:
        self.db.clear_messages(screenshot_id)

    def to_prompt(
        self,
        screenshot_id: str,
        *,
        image_path: str | None = None,
        system: str | None = None,
    ) -> list[ChatMessage]:
        """Convert the stored history into a message list ready to send to the model.

        `image_path` is attached to the most recent user turn — that's the
        turn the model is being asked about.
        """
        history = self.load(screenshot_id)
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
