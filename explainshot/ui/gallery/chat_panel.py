"""Middle column of the gallery: chat with the AI about the current screenshot.

ChatGPT-style: each message is its own bubble widget with per-message
actions (copy, edit for user turns, regenerate for assistant turns,
delete). Forked turns show a `‹ 2/3 ›` branch switcher.

Rendering strategy: a QScrollArea of `MessageRow` widgets, each of which
renders its own bubble with `QTextBrowser` for markdown. We own the
widgets so hit testing works — QTextBrowser inside one big transcript
couldn't tell us which message was hovered.
"""

from __future__ import annotations

import html
import logging
from datetime import datetime
from typing import Callable

import markdown2
from PyQt6.QtCore import QSize, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QClipboard, QGuiApplication, QIcon, QKeyEvent
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextBrowser,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...ai.history import MessageNode
from ..animation import FadeInController, HoverAnimator, HoverStates, HoverStyle
from ..theme import Theme

log = logging.getLogger(__name__)


# --- Message widget ---------------------------------------------------------


_ROLE_STYLES_DARK = {
    "user":      {"bg": "#0067c0", "fg": "#ffffff", "border": "#0067c0", "code_bg": "rgba(0,0,0,0.30)"},
    "assistant": {"bg": "#2f2f2f", "fg": "#f2f2f2", "border": "#3d3d3d", "code_bg": "rgba(255,255,255,0.08)"},
    "system":    {"bg": "transparent", "fg": "#b3b3b3", "border": "#5a5a5a", "code_bg": "rgba(127,127,127,0.15)"},
    "error":     {"bg": "rgba(201,64,64,0.10)", "fg": "#c94040", "border": "#c94040", "code_bg": "rgba(201,64,64,0.20)"},
}
_ROLE_STYLES_LIGHT = {
    "user":      {"bg": "#0067c0", "fg": "#ffffff", "border": "#0067c0", "code_bg": "rgba(0,0,0,0.35)"},
    "assistant": {"bg": "#ffffff", "fg": "#1b1b1b", "border": "#e6e6e6", "code_bg": "rgba(0,0,0,0.06)"},
    "system":    {"bg": "transparent", "fg": "#5c5c5c", "border": "#cfcfcf", "code_bg": "rgba(0,0,0,0.05)"},
    "error":     {"bg": "rgba(201,64,64,0.08)", "fg": "#a3241a", "border": "#c94040", "code_bg": "rgba(201,64,64,0.10)"},
}

_CURRENT_ROLE_STYLES: dict[str, dict[str, str]] = _ROLE_STYLES_DARK


def set_chat_theme(theme: str) -> None:
    """Called by GalleryWindow when the theme changes so new bubbles get the
    right palette. Existing bubbles keep their instance stylesheet — we redraw
    the transcript on theme change so this is fine."""
    global _CURRENT_ROLE_STYLES
    _CURRENT_ROLE_STYLES = _ROLE_STYLES_LIGHT if theme == "light" else _ROLE_STYLES_DARK


class MessageBubble(QFrame):
    """One rendered message with editable / actionable UI.

    A bubble carries:
      * the markdown-rendered content
      * inline styling per role — we set an explicit stylesheet on each
        instance because Qt's [property="…"] QSS selectors aren't picked
        up until the next polish cycle when the property is set during
        widget construction. Owning the per-role look here avoids that.
      * a hover-revealed action row (in the parent MessageRow).
    """

    def __init__(self, node: MessageNode, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.node = node
        self.setObjectName("MessageBubble")
        role = node.role if node.role in {"user", "assistant", "system", "error"} else "system"
        self._role = role
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._apply_bubble_style()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._body = QTextBrowser(self)
        self._body.setOpenExternalLinks(True)
        self._body.setStyleSheet(
            f"background: transparent; border: none; padding: 10px 14px; color: {_CURRENT_ROLE_STYLES[role]['fg']};"
        )
        self._body.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._body.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._body.setFrameShape(QFrame.Shape.NoFrame)
        self._body.document().documentLayout().documentSizeChanged.connect(self._adjust_height)
        outer.addWidget(self._body)

        # Editor is created lazily on Edit.
        self._editor: QTextEdit | None = None
        self._editor_actions: QWidget | None = None

        self._render()

    def _apply_bubble_style(self) -> None:
        s = _CURRENT_ROLE_STYLES[self._role]
        self.setStyleSheet(
            f"QFrame#MessageBubble {{"
            f"background: {s['bg']};"
            f"border: 1px solid {s['border']};"
            f"border-radius: 12px;"
            f"}}"
        )

    def _render(self) -> None:
        if self._role in {"user", "assistant"}:
            html_body = markdown2.markdown(
                self.node.content,
                extras=["fenced-code-blocks", "tables", "break-on-newline", "code-friendly"],
            )
        else:
            html_body = f"<div>{html.escape(self.node.content)}</div>"
        code_bg = _CURRENT_ROLE_STYLES[self._role]["code_bg"]
        css = _BUBBLE_CSS.replace("__CODE_BG__", code_bg)
        self._body.setHtml(f"<style>{css}</style>{html_body}")

    def set_content(self, content: str) -> None:
        self.node.content = content
        self._render()

    def append_content(self, delta: str) -> None:
        self.node.content += delta
        self._render()

    def _adjust_height(self) -> None:
        # QTextBrowser doesn't size to content on its own. We give the document
        # an explicit text width so wrapping matches the bubble width, then set
        # our own height to whatever the layout comes out to.
        available = max(60, self._body.width() - 32)
        self._body.document().setTextWidth(available)
        doc_height = int(self._body.document().size().height())
        self._body.setFixedHeight(doc_height + 24)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._adjust_height()

    # -- inline editor ---------------------------------------------------------

    def enter_edit_mode(self, done_callback: Callable[[str | None], None]) -> None:
        if self._editor is not None:
            return
        layout = self.layout()
        if layout is None:
            return
        self._body.hide()
        self._editor = QTextEdit(self)
        self._editor.setPlainText(self.node.content)
        self._editor.setStyleSheet(
            "background: transparent; border: none; padding: 8px 14px; color: inherit;"
        )
        self._editor.setFocus(Qt.FocusReason.OtherFocusReason)
        layout.addWidget(self._editor)

        actions = QWidget(self)
        row = QHBoxLayout(actions)
        row.setContentsMargins(10, 4, 10, 10)
        row.setSpacing(8)
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setProperty("flat", True)
        cancel.clicked.connect(lambda: self._exit_edit_mode(None, done_callback))
        row.addWidget(cancel)
        confirm = QPushButton("Save & regenerate")
        confirm.setProperty("accent", True)
        confirm.clicked.connect(
            lambda: self._exit_edit_mode(self._editor.toPlainText().strip() if self._editor else None, done_callback)
        )
        row.addWidget(confirm)
        layout.addWidget(actions)
        self._editor_actions = actions

    def _exit_edit_mode(self, new_text: str | None, cb: Callable[[str | None], None]) -> None:
        if self._editor is not None:
            self._editor.deleteLater()
            self._editor = None
        if self._editor_actions is not None:
            self._editor_actions.deleteLater()
            self._editor_actions = None
        self._body.show()
        cb(new_text)


_BUBBLE_CSS = """
html, body { margin: 0; padding: 0; }
p { margin: 0 0 6px 0; }
p:last-child { margin-bottom: 0; }
pre { background: __CODE_BG__; border-radius: 4px; padding: 8px 10px; }
code { background: __CODE_BG__; border-radius: 3px; padding: 1px 4px; }
ul, ol { margin: 4px 0 6px 20px; padding: 0; }
"""


class _MessageRow(QWidget):
    """Container for a bubble plus its hover-reveal action bar and (optional)
    branch switcher. Aligns user turns to the right, assistant to the left."""

    edit_requested = pyqtSignal(int)
    delete_requested = pyqtSignal(int)
    regenerate_requested = pyqtSignal(int)
    copy_requested = pyqtSignal(int)
    branch_switch_requested = pyqtSignal(int, int)

    def __init__(self, node: MessageNode, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.node = node
        self.setObjectName("MessageRow")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

        column = QVBoxLayout(self)
        column.setContentsMargins(4, 6, 4, 6)
        column.setSpacing(4)

        # Header: role label + branch switcher (if any) + timestamp
        header = QHBoxLayout()
        header.setContentsMargins(2, 0, 2, 0)
        header.setSpacing(6)

        role_label = QLabel(node.role.capitalize())
        role_label.setObjectName("MessageMeta")
        role_label.setProperty("muted", True)
        role_label.setStyleSheet("font-weight: 600;")
        header.addWidget(role_label)

        header.addStretch(1)

        # Branch switcher, e.g. "‹ 2 / 3 ›"
        self._branch_widget: QWidget | None = None
        if node.has_siblings():
            self._branch_widget = self._build_branch_switcher(node)
            header.addWidget(self._branch_widget)

        ts = QLabel(node.created_at.strftime("%H:%M"))
        ts.setObjectName("MessageMeta")
        ts.setProperty("muted", True)
        header.addWidget(ts)

        column.addLayout(header)

        # Bubble row: alignment depends on role.
        bubble_row = QHBoxLayout()
        bubble_row.setContentsMargins(0, 0, 0, 0)
        self.bubble = MessageBubble(node)
        self.bubble.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        self.bubble.setMaximumWidth(720)
        if node.role == "user":
            bubble_row.addStretch(1)
            bubble_row.addWidget(self.bubble)
        else:
            bubble_row.addWidget(self.bubble)
            bubble_row.addStretch(1)
        column.addLayout(bubble_row)

        # Hover action bar.
        self._actions = self._build_actions(node)
        self._actions_fade = FadeInController(self._actions)
        column.addWidget(self._actions)

    # -- construction helpers --------------------------------------------------

    def _build_branch_switcher(self, node: MessageNode) -> QWidget:
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)

        prev_btn = QPushButton("‹")
        prev_btn.setProperty("chip", True)
        prev_btn.setFixedSize(22, 20)
        prev_btn.clicked.connect(lambda: self.branch_switch_requested.emit(node.id, -1))
        prev_btn.setEnabled(node.index_in_siblings > 0)

        label = QLabel(f"{node.index_in_siblings + 1} / {len(node.siblings)}")
        label.setObjectName("MessageMeta")

        next_btn = QPushButton("›")
        next_btn.setProperty("chip", True)
        next_btn.setFixedSize(22, 20)
        next_btn.clicked.connect(lambda: self.branch_switch_requested.emit(node.id, +1))
        next_btn.setEnabled(node.index_in_siblings < len(node.siblings) - 1)

        row.addWidget(prev_btn)
        row.addWidget(label)
        row.addWidget(next_btn)
        return host

    def _build_actions(self, node: MessageNode) -> QWidget:
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(2, 0, 2, 0)
        row.setSpacing(4)
        if node.role == "user":
            row.addStretch(1)
        for label, tooltip, handler in self._action_specs(node):
            btn = QPushButton(label)
            btn.setProperty("chip", True)
            btn.setToolTip(tooltip)
            btn.clicked.connect(handler)
            row.addWidget(btn)
        if node.role != "user":
            row.addStretch(1)
        return host

    def _action_specs(self, node: MessageNode) -> list[tuple[str, str, Callable[[], None]]]:
        specs: list[tuple[str, str, Callable[[], None]]] = [
            ("Copy", "Copy the message text", lambda: self.copy_requested.emit(node.id)),
        ]
        if node.role == "user":
            specs.append(("Edit", "Edit & regenerate", lambda: self.edit_requested.emit(node.id)))
        if node.role == "assistant":
            specs.append(("Regenerate", "Regenerate this response as a new branch", lambda: self.regenerate_requested.emit(node.id)))
        specs.append(("Delete", "Delete this message and every message below", lambda: self.delete_requested.emit(node.id)))
        return specs

    # -- events ----------------------------------------------------------------

    def enterEvent(self, event) -> None:  # type: ignore[override]
        self._actions_fade.show()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        self._actions_fade.hide()
        super().leaveEvent(event)


# --- Prompt editor ----------------------------------------------------------


class _PromptEditor(QTextEdit):
    submitted = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptRichText(False)
        self.setPlaceholderText("Ask about this screenshot… (Enter to send, Shift+Enter for newline)")
        self.setFixedHeight(84)

    def keyPressEvent(self, event: QKeyEvent | None) -> None:  # type: ignore[override]
        if event and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
                return
            self.submitted.emit()
            return
        super().keyPressEvent(event)


# --- Panel ------------------------------------------------------------------


class ChatPanel(QWidget):
    """Signals emitted upwards to the GalleryWindow."""

    message_submitted = pyqtSignal(str)                       # brand-new user prompt
    edit_submitted = pyqtSignal(int, str)                     # (source_message_id, new_content)
    regenerate_requested = pyqtSignal(int)                    # assistant message_id
    delete_requested = pyqtSignal(int)                        # message_id
    branch_switch_requested = pyqtSignal(int, int)            # message_id, direction
    clear_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[_MessageRow] = []
        self._streaming_row: _MessageRow | None = None
        self._auto_pin = True   # stay at the bottom while streaming unless user scrolls up

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

        clear = QPushButton("Clear")
        clear.setProperty("chip", True)
        clear.setToolTip("Delete the entire conversation")
        clear.clicked.connect(self.clear_requested.emit)
        header.addWidget(clear)
        layout.addLayout(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("background: transparent; border: none;")
        scrollbar = self.scroll.verticalScrollBar()
        if scrollbar is not None:
            scrollbar.valueChanged.connect(self._on_scroll)
        layout.addWidget(self.scroll, 1)

        self._transcript_host = QWidget()
        self._transcript = QVBoxLayout(self._transcript_host)
        self._transcript.setContentsMargins(6, 6, 6, 6)
        self._transcript.setSpacing(2)
        self._transcript.addStretch(1)
        self.scroll.setWidget(self._transcript_host)

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

        self.set_enabled(False)

    # -- public interface ------------------------------------------------------

    def set_enabled(self, enabled: bool) -> None:
        self.editor.setEnabled(enabled)
        self.send.setEnabled(enabled)
        self.hint.setVisible(not enabled)

    def clear(self) -> None:
        for row in self._rows:
            row.deleteLater()
        self._rows.clear()
        self._streaming_row = None
        self._auto_pin = True

    def render(self, path: list[MessageNode]) -> None:
        """Rebuild the visible column from a fresh active-path snapshot."""
        self.clear()
        for node in path:
            self._append_row(node)
        self._pin_bottom()

    def set_status(self, text: str) -> None:
        self.status.setText(text)

    def replace_prompt(self, text: str) -> None:
        self.editor.setPlainText(text)
        self.editor.setFocus(Qt.FocusReason.OtherFocusReason)

    def begin_streaming(self, placeholder_node: MessageNode) -> None:
        self._streaming_row = self._append_row(placeholder_node)
        self._pin_bottom()

    def append_stream(self, delta: str) -> None:
        if self._streaming_row is None:
            return
        self._streaming_row.bubble.append_content(delta)
        if self._auto_pin:
            self._pin_bottom(defer=True)

    def end_streaming(self, final_text: str) -> None:
        if self._streaming_row is not None:
            self._streaming_row.bubble.set_content(final_text)
        self._streaming_row = None

    def show_error(self, message: str) -> None:
        node = MessageNode(
            id=-1, parent_id=None, role="error",
            content=message, model=None, created_at=datetime.now(),
            siblings=None, index_in_siblings=0,
        )
        self._append_row(node)
        self._pin_bottom()

    # -- signals plumbing ------------------------------------------------------

    def _append_row(self, node: MessageNode) -> _MessageRow:
        row = _MessageRow(node)
        row.copy_requested.connect(self._on_copy)
        row.edit_requested.connect(self._on_edit)
        row.delete_requested.connect(self.delete_requested.emit)
        row.regenerate_requested.connect(self.regenerate_requested.emit)
        row.branch_switch_requested.connect(self.branch_switch_requested.emit)
        self._transcript.insertWidget(self._transcript.count() - 1, row)
        self._rows.append(row)
        return row

    def _on_submit(self) -> None:
        text = self.editor.toPlainText().strip()
        if not text:
            return
        self.editor.clear()
        self.message_submitted.emit(text)

    def _on_copy(self, message_id: int) -> None:
        row = self._row_for(message_id)
        if row is None:
            return
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(row.node.content)
            self.set_status("Copied")

    def _on_edit(self, message_id: int) -> None:
        row = self._row_for(message_id)
        if row is None or row.node.role != "user":
            return
        def done(new_text: str | None) -> None:
            if new_text and new_text != row.node.content:
                self.edit_submitted.emit(message_id, new_text)
        row.bubble.enter_edit_mode(done)

    def _row_for(self, message_id: int) -> _MessageRow | None:
        return next((r for r in self._rows if r.node.id == message_id), None)

    # -- scroll behaviour ------------------------------------------------------

    def _on_scroll(self, value: int) -> None:
        scrollbar = self.scroll.verticalScrollBar()
        if scrollbar is None:
            return
        # If the user is within ~20px of the bottom, keep auto-pinning; else pause.
        self._auto_pin = value >= scrollbar.maximum() - 20

    def _pin_bottom(self, *, defer: bool = False) -> None:
        def go() -> None:
            scrollbar = self.scroll.verticalScrollBar()
            if scrollbar is not None:
                scrollbar.setValue(scrollbar.maximum())
        if defer:
            QTimer.singleShot(0, go)
        else:
            go()
