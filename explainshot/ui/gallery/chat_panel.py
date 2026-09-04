"""Middle column of the gallery: chat with the AI about the current screenshot."""

from __future__ import annotations

import html
from datetime import datetime

import markdown2
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class _PromptEditor(QTextEdit):
    submitted = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptRichText(False)
        self.setPlaceholderText("Ask about this screenshot… (Enter to send, Shift+Enter for newline)")
        self.setFixedHeight(80)

    def keyPressEvent(self, event: QKeyEvent | None) -> None:  # type: ignore[override]
        if event and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
                return
            self.submitted.emit()
            return
        super().keyPressEvent(event)


class ChatPanel(QWidget):
    message_submitted = pyqtSignal(str)   # prompt

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("AI conversation")
        title.setProperty("section", True)
        header.addWidget(title, 1)
        self.status = QLabel("Idle")
        self.status.setObjectName("StatusChip")
        header.addWidget(self.status)
        layout.addLayout(header)

        self.transcript = QTextBrowser()
        self.transcript.setObjectName("ChatTranscript")
        self.transcript.setOpenExternalLinks(True)
        layout.addWidget(self.transcript, 1)

        input_row = QVBoxLayout()
        self.editor = _PromptEditor()
        self.editor.submitted.connect(self._on_submit)
        input_row.addWidget(self.editor)

        button_row = QHBoxLayout()
        self.hint = QLabel("Select a screenshot to start chatting.")
        self.hint.setProperty("muted", True)
        button_row.addWidget(self.hint, 1)
        self.send = QPushButton("Send")
        self.send.setProperty("accent", True)
        self.send.clicked.connect(self._on_submit)
        button_row.addWidget(self.send)
        input_row.addLayout(button_row)
        layout.addLayout(input_row)

        self._messages: list[tuple[str, str, datetime]] = []
        self._streaming_buffer = ""
        self._streaming = False
        self.set_enabled(False)

    # -- public API ------------------------------------------------------------

    def set_enabled(self, enabled: bool) -> None:
        self.editor.setEnabled(enabled)
        self.send.setEnabled(enabled)
        self.hint.setText("" if enabled else "Select a screenshot to start chatting.")

    def clear(self) -> None:
        self._messages.clear()
        self._streaming_buffer = ""
        self._streaming = False
        self.transcript.setHtml("")

    def set_status(self, text: str) -> None:
        self.status.setText(text)

    def add_message(self, role: str, content: str) -> None:
        self._messages.append((role, content, datetime.now()))
        self._render()

    def replace_prompt(self, text: str) -> None:
        self.editor.setPlainText(text)
        self.editor.setFocus(Qt.FocusReason.OtherFocusReason)

    def begin_streaming(self) -> None:
        self._streaming = True
        self._streaming_buffer = ""
        self._messages.append(("assistant", "", datetime.now()))
        self._render()

    def append_stream(self, delta: str) -> None:
        if not self._streaming:
            return
        self._streaming_buffer += delta
        if self._messages and self._messages[-1][0] == "assistant":
            role, _, ts = self._messages[-1]
            self._messages[-1] = (role, self._streaming_buffer, ts)
        self._render()

    def end_streaming(self, final_text: str | None = None) -> None:
        if self._streaming and self._messages and self._messages[-1][0] == "assistant":
            role, existing, ts = self._messages[-1]
            self._messages[-1] = (role, final_text or existing, ts)
        self._streaming = False
        self._streaming_buffer = ""
        self._render()

    def show_error(self, message: str) -> None:
        self._messages.append(("error", message, datetime.now()))
        self._streaming = False
        self._render()

    # -- internals -------------------------------------------------------------

    def _on_submit(self) -> None:
        text = self.editor.toPlainText().strip()
        if not text:
            return
        self.editor.clear()
        self.message_submitted.emit(text)

    def _render(self) -> None:
        blocks = ["<style>", _TRANSCRIPT_CSS, "</style>"]
        for role, content, ts in self._messages:
            time_str = ts.strftime("%H:%M")
            if role in {"user", "assistant"}:
                body = markdown2.markdown(
                    content or "…",
                    extras=["fenced-code-blocks", "tables", "break-on-newline", "code-friendly"],
                )
                blocks.append(
                    f'<div class="msg msg-{role}">'
                    f'<div class="meta"><span class="role">{role}</span>'
                    f'<span class="ts">{time_str}</span></div>'
                    f'<div class="body">{body}</div>'
                    f"</div>"
                )
            elif role == "error":
                blocks.append(
                    f'<div class="msg msg-error"><div class="body">⚠ {html.escape(content)}</div></div>'
                )
            else:
                blocks.append(
                    f'<div class="msg msg-system"><div class="body">{html.escape(content)}</div></div>'
                )
        self.transcript.setHtml("".join(blocks))
        scrollbar = self.transcript.verticalScrollBar()
        if scrollbar:
            scrollbar.setValue(scrollbar.maximum())


_TRANSCRIPT_CSS = """
body { color: inherit; }
.msg { margin: 8px 0; }
.meta { font-size: 11px; opacity: 0.7; margin-bottom: 2px; }
.role { text-transform: uppercase; letter-spacing: 0.4px; font-weight: 600; margin-right: 6px; }
.ts { opacity: 0.6; }
.msg-user .body { }
.msg-assistant .body { }
.msg-error .body { color: #c94040; font-weight: 500; }
.msg-system .body { opacity: 0.7; font-style: italic; }
pre { background: rgba(127,127,127,0.15); padding: 8px 10px; border-radius: 4px; }
code { background: rgba(127,127,127,0.15); padding: 1px 4px; border-radius: 3px; }
"""
