"""Prompt presets: reusable questions the user runs against a screenshot.

The old preset system was ~1200 lines across three files with categories,
tags, favorites, per-category colors, usage-stats aggregation. In practice
users cared about "give it a name, give it a prompt, hit run" — that is
what this exposes.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

from ..core.database import Database
from ..core.signals import AppSignals


@dataclass
class Preset:
    id: str
    name: str
    prompt: str
    description: str = ""
    usage_count: int = 0
    builtin: bool = False
    created_at: datetime | None = None


BUILTIN_PRESETS: list[Preset] = [
    Preset(
        id="builtin.explain",
        name="Explain what's on screen",
        prompt="Look at this screenshot and explain what I'm looking at. Be concise but specific.",
        description="Plain-language explanation of the captured content.",
        builtin=True,
    ),
    Preset(
        id="builtin.transcribe",
        name="Transcribe text",
        prompt="Transcribe all readable text in this screenshot exactly as it appears. Preserve line breaks.",
        description="OCR-style verbatim text extraction.",
        builtin=True,
    ),
    Preset(
        id="builtin.summarize",
        name="Summarize",
        prompt="Summarize the content of this screenshot in a few sentences. Focus on the main point.",
        description="Short summary of the captured content.",
        builtin=True,
    ),
    Preset(
        id="builtin.translate",
        name="Translate to English",
        prompt="Translate any non-English text in this screenshot to English. Keep the original layout where possible.",
        description="Translate visible text into English.",
        builtin=True,
    ),
    Preset(
        id="builtin.error",
        name="Explain this error",
        prompt="This screenshot shows an error. Explain what it means, what likely caused it, and what to try next.",
        description="Diagnose an error message.",
        builtin=True,
    ),
    Preset(
        id="builtin.code_review",
        name="Review the code",
        prompt="Review the code visible in this screenshot. Point out bugs, unclear names, and simplifications.",
        description="Ad-hoc code review of a code screenshot.",
        builtin=True,
    ),
]


class PresetManager:
    def __init__(self, db: Database, signals: AppSignals) -> None:
        self.db = db
        self.signals = signals
        self._ensure_builtins()

    # -- public API ------------------------------------------------------------

    def list(self) -> list[Preset]:
        return [self._row_to_preset(row) for row in self.db.list_presets()]

    def get(self, preset_id: str) -> Preset | None:
        row = self.db.get_preset(preset_id)
        return self._row_to_preset(row) if row else None

    def create(self, name: str, prompt: str, description: str = "") -> Preset:
        preset_id = f"user.{hashlib.sha1(f'{name}{prompt}'.encode()).hexdigest()[:12]}"
        self.db.upsert_preset(
            id=preset_id,
            name=name,
            prompt=prompt,
            description=description,
            builtin=False,
        )
        self.signals.preset_saved.emit(preset_id)
        preset = self.get(preset_id)
        assert preset is not None
        return preset

    def update(self, preset_id: str, *, name: str, prompt: str, description: str = "") -> None:
        preset = self.get(preset_id)
        if not preset:
            return
        self.db.upsert_preset(
            id=preset_id,
            name=name,
            prompt=prompt,
            description=description,
            builtin=preset.builtin,
            created_at=preset.created_at,
        )
        self.signals.preset_saved.emit(preset_id)

    def delete(self, preset_id: str) -> None:
        preset = self.get(preset_id)
        if not preset or preset.builtin:
            return
        self.db.delete_preset(preset_id)
        self.signals.preset_deleted.emit(preset_id)

    def record_use(self, preset_id: str) -> None:
        self.db.bump_preset_usage(preset_id)

    # -- internals -------------------------------------------------------------

    def _ensure_builtins(self) -> None:
        existing = {row["id"] for row in self.db.list_presets()}
        for preset in BUILTIN_PRESETS:
            if preset.id not in existing:
                self.db.upsert_preset(
                    id=preset.id,
                    name=preset.name,
                    prompt=preset.prompt,
                    description=preset.description,
                    builtin=True,
                )

    @staticmethod
    def _row_to_preset(row) -> Preset:
        return Preset(
            id=row["id"],
            name=row["name"],
            prompt=row["prompt"],
            description=row["description"] or "",
            usage_count=row["usage_count"] or 0,
            builtin=bool(row["builtin"]),
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
        )
