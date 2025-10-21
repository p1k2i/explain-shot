"""
Chat Interface Module

Implements the AI chat interface for the gallery's middle column.
"""

import logging
from datetime import datetime
from typing import List

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextBrowser,
    QLineEdit, QPushButton, QLabel
)

from src.utils.style_loader import load_stylesheet

from .gallery_widgets import ChatMessage

logger = logging.getLogger(__name__)


class ChatWidget(QWidget):
    """Chat interface widget for AI interactions."""

    message_sent = pyqtSignal(str)  # message content

    def __init__(self, parent=None):
        super().__init__(parent)
        self.chat_messages: List[ChatMessage] = []

        self.setObjectName("ChatWidget")
        self._setup_ui()

    def _setup_ui(self):
        """Setup the UI."""
        # Main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Chat history
        self.chat_history = QTextBrowser()
        self.chat_history.setMinimumHeight(400)
        layout.addWidget(self.chat_history)

        # Input area
        input_layout = QHBoxLayout()

        self.chat_input = QLineEdit()
        self.chat_input.setPlaceholderText("Type your message...")
        self.chat_input.returnPressed.connect(self._send_message)

        self.send_button = QPushButton("Send")
        self.send_button.setFixedSize(60, 30)
        self.send_button.setObjectName("send_button")
        self.send_button.clicked.connect(self._send_message)

        input_layout.addWidget(self.chat_input)
        input_layout.addWidget(self.send_button)

        layout.addLayout(input_layout)

        # Status bar
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("status_label")
        layout.addWidget(self.status_label)

    def _send_message(self):
        """Handle sending a message."""
        text = self.chat_input.text().strip()
        if text:
            self.chat_input.clear()
            self.message_sent.emit(text)

    def add_user_message(self, content: str):
        """Add a user message to the chat."""
        message = ChatMessage(
            sender="user",
            content=content,
            timestamp=datetime.now()
        )
        self.chat_messages.append(message)
        self._update_chat_display()

    def add_ai_message(self, content: str):
        """Add an AI response to the chat."""
        message = ChatMessage(
            sender="ai",
            content=content,
            timestamp=datetime.now()
        )
        self.chat_messages.append(message)
        self._update_chat_display()

    def add_system_message(self, content: str):
        """Add a system message to the chat."""
        message = ChatMessage(
            sender="system",
            content=content,
            timestamp=datetime.now()
        )
        self.chat_messages.append(message)
        self._update_chat_display()

    def set_prompt_text(self, prompt: str):
        """Set text in the input field."""
        self.chat_input.setText(prompt)
        self.chat_input.setFocus()

    def clear_chat(self):
        """Clear chat history."""
        self.chat_messages.clear()
        self._update_chat_display()

    def set_status(self, status: str):
        """Update the status label."""
        self.status_label.setText(status)

    def _update_chat_display(self):
        """Update the chat history display."""
        html_content = self._generate_chat_html()
        self.chat_history.setHtml(html_content)

        # Scroll to bottom
        scrollbar = self.chat_history.verticalScrollBar()
        if scrollbar:
            scrollbar.setValue(scrollbar.maximum())

    def _generate_chat_html(self) -> str:
        """Generate HTML for chat messages."""
        # Load CSS from file
        css_content = load_stylesheet("gallery", "dark", "chat")
        if css_content is None:
            css_content = ""  # Fallback to empty CSS

        html = f"""
        <style>
            {css_content}
        </style>
        <body>
        """

        for message in self.chat_messages:
            timestamp_str = message.timestamp.strftime("%H:%M:%S")
            sender_class = f"message-{message.sender}"

            html += f"""
            <div class="message {sender_class}">
                <div class="message-header">
                    <span class="sender">{message.sender.upper()}</span>
                    <span class="timestamp">{timestamp_str}</span>
                </div>
                <div class="message-content">{self._escape_html(message.content)}</div>
            </div>
            """

        html += "</body>"
        return html

    def _escape_html(self, text: str) -> str:
        """Escape HTML special characters."""
        return (text.replace('&', '&amp;')
                   .replace('<', '&lt;')
                   .replace('>', '&gt;')
                   .replace('"', '&quot;')
                   .replace("'", '&#x27;'))


class ChatInterface(QWidget):
    """Chat interface column widget."""

    # Signals
    message_sent = pyqtSignal(str)  # message content

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ChatInterface")
        self._setup_ui()

    def _setup_ui(self):
        """Setup the UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # Column header
        header = QLabel("AI Chat")
        header.setObjectName("column_header")
        layout.addWidget(header)

        # Chat widget
        self.chat_widget = ChatWidget()
        self.chat_widget.message_sent.connect(self.message_sent.emit)
        layout.addWidget(self.chat_widget)

    def add_user_message(self, content: str):
        """Add a user message to the chat."""
        self.chat_widget.add_user_message(content)

    def add_ai_message(self, content: str):
        """Add an AI response to the chat."""
        self.chat_widget.add_ai_message(content)

    def add_system_message(self, content: str):
        """Add a system message to the chat."""
        self.chat_widget.add_system_message(content)

    def set_prompt_text(self, prompt: str):
        """Set text in the input field."""
        self.chat_widget.set_prompt_text(prompt)

    def clear_chat(self):
        """Clear chat history."""
        self.chat_widget.clear_chat()

    def set_status(self, status: str):
        """Update the status label."""
        self.chat_widget.set_status(status)

    async def update_request_pooling_setting(self, enabled: bool):
        """Update request pooling enabled setting."""
        try:
            # This could be used to optimize AI request handling
            # For now, just log the change
            logger.debug(f"Request pooling enabled updated to: {enabled}")
        except Exception as e:
            logger.error(f"Error updating request pooling setting: {e}")

    async def update_max_concurrent_setting(self, max_concurrent: int):
        """Update max concurrent requests setting."""
        try:
            # This could be used to limit concurrent AI requests
            # For now, just log the change
            logger.debug(f"Max concurrent requests updated to: {max_concurrent}")
        except Exception as e:
            logger.error(f"Error updating max concurrent setting: {e}")

    async def update_request_timeout_setting(self, timeout: float):
        """Update request timeout setting."""
        try:
            # This could be used to set AI request timeouts
            # For now, just log the change
            logger.debug(f"Request timeout updated to: {timeout} seconds")
        except Exception as e:
            logger.error(f"Error updating request timeout setting: {e}")
