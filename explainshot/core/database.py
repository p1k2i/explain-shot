"""SQLite storage for screenshots, chat messages, and presets.

Wraps sqlite3 in a Database class the rest of the app talks to. Everything
runs synchronously — SQLite is fast enough locally, and the async wrappers
in the old code were just wrapping blocking `sqlite3` calls in threadpool
executors while pretending to be async.
"""

from __future__ import annotations

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
    # chat_messages stores an *entire conversation tree*. parent_id NULL means
    # this is the first turn of the conversation for its screenshot; every other
    # message is a child of the message it was written in reply to. Sibling
    # messages sharing a parent are alternate branches (the user edited,
    # regenerated, or resent). The user's currently-visible branch is picked
    # by chat_active_branch below.
    """
    CREATE TABLE IF NOT EXISTS chat_messages (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        screenshot_id  TEXT NOT NULL,
        parent_id      INTEGER,
        role           TEXT NOT NULL,               -- user | assistant | system
        content        TEXT NOT NULL,
        model          TEXT,
        created_at     TEXT NOT NULL,
        FOREIGN KEY (screenshot_id) REFERENCES screenshots(id) ON DELETE CASCADE,
        FOREIGN KEY (parent_id) REFERENCES chat_messages(id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_chat_screenshot ON chat_messages (screenshot_id, id)",
    "CREATE INDEX IF NOT EXISTS idx_chat_parent ON chat_messages (parent_id)",
    # For each fork point (parent_id, or NULL meaning root), remembers which
    # child is currently visible. When the user forks a message, we update
    # the entry for that message's parent to point at the new child.
    """
    CREATE TABLE IF NOT EXISTS chat_active_branch (
        screenshot_id  TEXT NOT NULL,
        parent_id      INTEGER,
        child_id       INTEGER NOT NULL,
        PRIMARY KEY (screenshot_id, parent_id)
    )
    """,
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
    # Persistent window geometry, keyed by window name (gallery, settings).
    """
    CREATE TABLE IF NOT EXISTS window_state (
        name       TEXT PRIMARY KEY,
        geometry   BLOB,
        maximized  INTEGER DEFAULT 0
    )
    """,
    # System notices are visible in the chat transcript but never sent to
    # the model. Scoped per screenshot so switching screenshots or restarting
    # the app shows the right notices for the right conversation.
    """
    CREATE TABLE IF NOT EXISTS system_notices (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        screenshot_id  TEXT NOT NULL,
        kind           TEXT NOT NULL,             -- error | info
        message        TEXT NOT NULL,
        created_at     TEXT NOT NULL,
        FOREIGN KEY (screenshot_id) REFERENCES screenshots(id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_notices_screenshot ON system_notices (screenshot_id, id)",
]


class Database:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or database_path()
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        # Migrations run before the schema, in case an older on-disk file is
        # missing a column that the schema below now indexes. `IF NOT EXISTS`
        # on the CREATE TABLE keeps this idempotent for fresh installs.
        self._migrate()
        for stmt in SCHEMA:
            self._conn.execute(stmt)
        self._conn.commit()

    def _migrate(self) -> None:
        """Bring older on-disk schemas up to what the current SCHEMA expects.
        Each ALTER is wrapped so a fresh install (column already present) is a
        no-op."""
        migrations = [
            "ALTER TABLE chat_messages ADD COLUMN parent_id INTEGER",
        ]
        for stmt in migrations:
            try:
                self._conn.execute(stmt)
            except sqlite3.OperationalError:
                continue

    # -- generic helpers -------------------------------------------------------

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            cursor = self._conn.execute(sql, params)
            self._conn.commit()
            return cursor

    def executemany(self, sql: str, seq: Iterable[Iterable[Any]]) -> sqlite3.Cursor:
        with self._lock:
            cursor = self._conn.executemany(sql, seq)
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

    def rename_screenshot(self, screenshot_id: str, new_filename: str, new_path: str) -> None:
        self.execute(
            "UPDATE screenshots SET filename = ?, path = ? WHERE id = ?",
            (new_filename, new_path, screenshot_id),
        )

    def delete_screenshot(self, screenshot_id: str) -> None:
        self.execute("DELETE FROM screenshots WHERE id = ?", (screenshot_id,))

    # -- chat messages (branching tree) ---------------------------------------

    def add_message(
        self,
        screenshot_id: str,
        role: str,
        content: str,
        *,
        parent_id: int | None = None,
        model: str | None = None,
        created_at: datetime | None = None,
    ) -> int:
        cursor = self.execute(
            """
            INSERT INTO chat_messages (screenshot_id, parent_id, role, content, model, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                screenshot_id,
                parent_id,
                role,
                content,
                model,
                (created_at or datetime.now()).isoformat(),
            ),
        )
        new_id = int(cursor.lastrowid or 0)
        # New messages become the active child of their parent.
        self.set_active_child(screenshot_id, parent_id, new_id)
        return new_id

    def get_message(self, message_id: int) -> sqlite3.Row | None:
        return self.query_one("SELECT * FROM chat_messages WHERE id = ?", (message_id,))

    def list_all_messages(self, screenshot_id: str) -> list[sqlite3.Row]:
        return self.query(
            "SELECT * FROM chat_messages WHERE screenshot_id = ? ORDER BY id",
            (screenshot_id,),
        )

    def list_children(self, screenshot_id: str, parent_id: int | None) -> list[sqlite3.Row]:
        if parent_id is None:
            return self.query(
                "SELECT * FROM chat_messages WHERE screenshot_id = ? AND parent_id IS NULL ORDER BY id",
                (screenshot_id,),
            )
        return self.query(
            "SELECT * FROM chat_messages WHERE parent_id = ? ORDER BY id",
            (parent_id,),
        )

    def delete_message_subtree(self, message_id: int) -> None:
        """Delete a message and every descendant. Foreign-key CASCADE handles
        the recursion. Also clears the active-branch pointers that referenced
        the removed nodes."""
        # Collect the subtree ids before deletion for active_branch cleanup.
        ids = self._collect_subtree(message_id)
        placeholders = ",".join("?" * len(ids))
        self.execute(f"DELETE FROM chat_messages WHERE id IN ({placeholders})", ids)
        self.execute(
            f"DELETE FROM chat_active_branch WHERE child_id IN ({placeholders}) OR parent_id IN ({placeholders})",
            ids + ids,
        )

    def _collect_subtree(self, root_id: int) -> list[int]:
        collected: list[int] = []
        frontier = [root_id]
        while frontier:
            current = frontier.pop()
            collected.append(current)
            for row in self.query("SELECT id FROM chat_messages WHERE parent_id = ?", (current,)):
                frontier.append(row["id"])
        return collected

    def clear_messages(self, screenshot_id: str) -> None:
        self.execute("DELETE FROM chat_messages WHERE screenshot_id = ?", (screenshot_id,))
        self.execute("DELETE FROM chat_active_branch WHERE screenshot_id = ?", (screenshot_id,))

    def set_active_child(self, screenshot_id: str, parent_id: int | None, child_id: int) -> None:
        # SQLite treats NULL as distinct in UNIQUE, so we can't use INSERT OR
        # REPLACE with a NULL primary-key component. Delete + insert instead.
        with self._lock:
            if parent_id is None:
                self._conn.execute(
                    "DELETE FROM chat_active_branch WHERE screenshot_id = ? AND parent_id IS NULL",
                    (screenshot_id,),
                )
            else:
                self._conn.execute(
                    "DELETE FROM chat_active_branch WHERE screenshot_id = ? AND parent_id = ?",
                    (screenshot_id, parent_id),
                )
            self._conn.execute(
                "INSERT INTO chat_active_branch (screenshot_id, parent_id, child_id) VALUES (?, ?, ?)",
                (screenshot_id, parent_id, child_id),
            )
            self._conn.commit()

    def get_active_child(self, screenshot_id: str, parent_id: int | None) -> int | None:
        if parent_id is None:
            row = self.query_one(
                "SELECT child_id FROM chat_active_branch WHERE screenshot_id = ? AND parent_id IS NULL",
                (screenshot_id,),
            )
        else:
            row = self.query_one(
                "SELECT child_id FROM chat_active_branch WHERE screenshot_id = ? AND parent_id = ?",
                (screenshot_id, parent_id),
            )
        return row["child_id"] if row else None

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

    # -- system notices --------------------------------------------------------

    def add_notice(self, screenshot_id: str, kind: str, message: str, *, created_at: datetime | None = None) -> int:
        cursor = self.execute(
            """
            INSERT INTO system_notices (screenshot_id, kind, message, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (screenshot_id, kind, message, (created_at or datetime.now()).isoformat()),
        )
        return int(cursor.lastrowid or 0)

    def list_notices(self, screenshot_id: str) -> list[sqlite3.Row]:
        return self.query(
            "SELECT * FROM system_notices WHERE screenshot_id = ? ORDER BY id",
            (screenshot_id,),
        )

    def delete_notice(self, notice_id: int) -> None:
        self.execute("DELETE FROM system_notices WHERE id = ?", (notice_id,))

    def clear_notices(self, screenshot_id: str) -> None:
        self.execute("DELETE FROM system_notices WHERE screenshot_id = ?", (screenshot_id,))

    # -- window state ----------------------------------------------------------

    def save_window_state(self, name: str, geometry: bytes, maximized: bool) -> None:
        self.execute(
            "INSERT OR REPLACE INTO window_state (name, geometry, maximized) VALUES (?, ?, ?)",
            (name, geometry, 1 if maximized else 0),
        )

    def load_window_state(self, name: str) -> tuple[bytes, bool] | None:
        row = self.query_one("SELECT geometry, maximized FROM window_state WHERE name = ?", (name,))
        return (bytes(row["geometry"]), bool(row["maximized"])) if row else None
