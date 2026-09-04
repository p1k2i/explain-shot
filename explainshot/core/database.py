"""SQLite storage for screenshots, chat messages, and presets.

Wraps sqlite3 in a Database class the rest of the app talks to. Everything
runs synchronously — SQLite is fast enough locally, and the async wrappers
in the old code were just wrapping blocking `sqlite3` calls in threadpool
executors while pretending to be async.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from ..config.paths import database_path

SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS screenshots (
        id           TEXT PRIMARY KEY,             -- sha256 hex of the image
        filename     TEXT NOT NULL,
        path         TEXT NOT NULL,
        width        INTEGER NOT NULL,
        height       INTEGER NOT NULL,
        size_bytes   INTEGER NOT NULL,
        format       TEXT NOT NULL,
        created_at   TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_screenshots_created ON screenshots (created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS chat_messages (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        screenshot_id  TEXT NOT NULL,
        role           TEXT NOT NULL,               -- user | assistant | system
        content        TEXT NOT NULL,
        model          TEXT,
        created_at     TEXT NOT NULL,
        FOREIGN KEY (screenshot_id) REFERENCES screenshots(id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_chat_screenshot ON chat_messages (screenshot_id, id)",
    """
    CREATE TABLE IF NOT EXISTS presets (
        id           TEXT PRIMARY KEY,
        name         TEXT NOT NULL,
        prompt       TEXT NOT NULL,
        description  TEXT DEFAULT '',
        usage_count  INTEGER DEFAULT 0,
        builtin      INTEGER DEFAULT 0,
        created_at   TEXT NOT NULL
    )
    """,
]


class Database:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or database_path()
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        for stmt in SCHEMA:
            self._conn.execute(stmt)
        self._conn.commit()

    # -- generic helpers -------------------------------------------------------

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            cursor = self._conn.execute(sql, params)
            self._conn.commit()
            return cursor

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def query_one(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- screenshots -----------------------------------------------------------

    def upsert_screenshot(
        self,
        *,
        id: str,
        filename: str,
        path: str,
        width: int,
        height: int,
        size_bytes: int,
        format: str,
        created_at: datetime,
    ) -> None:
        self.execute(
            """
            INSERT OR REPLACE INTO screenshots
            (id, filename, path, width, height, size_bytes, format, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (id, filename, path, width, height, size_bytes, format, created_at.isoformat()),
        )

    def list_screenshots(self, limit: int | None = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM screenshots ORDER BY created_at DESC"
        if limit is not None:
            sql += " LIMIT ?"
            return self.query(sql, (limit,))
        return self.query(sql)

    def get_screenshot(self, screenshot_id: str) -> sqlite3.Row | None:
        return self.query_one("SELECT * FROM screenshots WHERE id = ?", (screenshot_id,))

    def delete_screenshot(self, screenshot_id: str) -> None:
        self.execute("DELETE FROM screenshots WHERE id = ?", (screenshot_id,))

    # -- chat messages ---------------------------------------------------------

    def add_message(
        self,
        screenshot_id: str,
        role: str,
        content: str,
        *,
        model: str | None = None,
        created_at: datetime | None = None,
    ) -> int:
        cursor = self.execute(
            """
            INSERT INTO chat_messages (screenshot_id, role, content, model, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                screenshot_id,
                role,
                content,
                model,
                (created_at or datetime.now()).isoformat(),
            ),
        )
        return int(cursor.lastrowid or 0)

    def list_messages(self, screenshot_id: str) -> list[sqlite3.Row]:
        return self.query(
            "SELECT * FROM chat_messages WHERE screenshot_id = ? ORDER BY id",
            (screenshot_id,),
        )

    def clear_messages(self, screenshot_id: str) -> None:
        self.execute("DELETE FROM chat_messages WHERE screenshot_id = ?", (screenshot_id,))

    # -- presets ---------------------------------------------------------------

    def upsert_preset(
        self,
        *,
        id: str,
        name: str,
        prompt: str,
        description: str = "",
        builtin: bool = False,
        created_at: datetime | None = None,
    ) -> None:
        self.execute(
            """
            INSERT INTO presets (id, name, prompt, description, builtin, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                prompt = excluded.prompt,
                description = excluded.description
            """,
            (
                id,
                name,
                prompt,
                description,
                1 if builtin else 0,
                (created_at or datetime.now()).isoformat(),
            ),
        )

    def list_presets(self) -> list[sqlite3.Row]:
        return self.query("SELECT * FROM presets ORDER BY usage_count DESC, name")

    def get_preset(self, preset_id: str) -> sqlite3.Row | None:
        return self.query_one("SELECT * FROM presets WHERE id = ?", (preset_id,))

    def delete_preset(self, preset_id: str) -> None:
        self.execute("DELETE FROM presets WHERE id = ? AND builtin = 0", (preset_id,))

    def bump_preset_usage(self, preset_id: str) -> None:
        self.execute("UPDATE presets SET usage_count = usage_count + 1 WHERE id = ?", (preset_id,))
