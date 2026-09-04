"""OpenAI-compatible AI provider.

Any endpoint that speaks the OpenAI /chat/completions dialect works — that
covers Ollama's /v1, LM Studio, vLLM, oobabooga, Together, Groq, and the
real OpenAI. The old code used the `ollama` Python package which locked us
into one provider and gave us no meaningful features in return.

Vision requests use the "image_url" content-part with a base64 data URL —
supported by every OpenAI-compatible vision endpoint the app cares about.
"""

from __future__ import annotations

import base64
import json
import logging
import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator

import httpx

log = logging.getLogger(__name__)


class AIError(Exception):
    pass


@dataclass
class ChatMessage:
    role: str                                        # user | assistant | system
    content: str
    image_paths: list[str] = field(default_factory=list)


class AIProvider:
    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        model: str = "",
        timeout: float = 120.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    # -- public API ------------------------------------------------------------

    async def list_models(self) -> list[str]:
        """GET /models. Ollama and OpenAI both expose this."""
        async with self._client() as client:
            resp = await client.get(f"{self.base_url}/models")
            resp.raise_for_status()
            payload = resp.json()
        entries = payload.get("data") or payload.get("models") or []
        names: list[str] = []
        for entry in entries:
            name = entry.get("id") or entry.get("name")
            if name:
                names.append(name)
        return sorted(names)

    async def ping(self) -> bool:
        try:
            await self.list_models()
            return True
        except Exception as exc:
            log.debug("ping failed: %s", exc)
            return False

    async def chat(self, messages: list[ChatMessage]) -> str:
        """Non-streaming completion. Returns the assistant reply as a string."""
        body = self._build_body(messages, stream=False)
        async with self._client() as client:
            resp = await client.post(f"{self.base_url}/chat/completions", json=body)
            resp.raise_for_status()
            data = resp.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise AIError(f"unexpected response shape: {data}") from exc

    async def stream(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        """Streaming completion. Yields text deltas as they arrive.

        Cleanup note: after `[DONE]` we keep iterating `aiter_lines()` until
        it naturally exhausts instead of returning early. That's what lets
        the underlying `httpcore.HTTP11ConnectionByteStream` async generator
        run to `StopAsyncIteration`. If we bail with `return` here, the
        outer `async with` calls `.aclose()` on that generator while it's
        still suspended at its `yield part`, and it can't release the
        connection synchronously — producing httpcore's
        "async generator ignored GeneratorExit" warning at the end of every
        reply. Draining the tail costs a millisecond and silences it.
        """
        body = self._build_body(messages, stream=True)
        async with self._client() as client:
            async with client.stream(
                "POST", f"{self.base_url}/chat/completions", json=body
            ) as resp:
                resp.raise_for_status()
                done_seen = False
                async for line in resp.aiter_lines():
                    if done_seen or not line or not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        done_seen = True
                        continue
                    try:
                        chunk = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    try:
                        delta = chunk["choices"][0]["delta"].get("content") or ""
                    except (KeyError, IndexError):
                        continue
                    if delta:
                        yield delta

    # -- internals -------------------------------------------------------------

    def _client(self) -> httpx.AsyncClient:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return httpx.AsyncClient(headers=headers, timeout=self.timeout)

    def _build_body(self, messages: list[ChatMessage], *, stream: bool) -> dict[str, Any]:
        if not self.model:
            raise AIError("no model configured")
        return {
            "model": self.model,
            "messages": [self._render(m) for m in messages],
            "stream": stream,
        }

    def _render(self, message: ChatMessage) -> dict[str, Any]:
        if not message.image_paths:
            return {"role": message.role, "content": message.content}
        parts: list[dict[str, Any]] = [{"type": "text", "text": message.content}]
        for image_path in message.image_paths:
            parts.append({
                "type": "image_url",
                "image_url": {"url": encode_image_data_url(image_path)},
            })
        return {"role": message.role, "content": parts}


def encode_image_data_url(image_path: str) -> str:
    p = Path(image_path)
    mime, _ = mimetypes.guess_type(p.name)
    mime = mime or "image/png"
    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"
