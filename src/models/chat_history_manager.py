"""
Chat History Manager for file-based JSON storage.

This module manages chat history storage using JSON files organized by
screenshot hash, replacing database storage with filesystem operations.
"""

import asyncio
import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .screenshot_models import ScreenshotMetadata


class ChatHistoryError(Exception):
    """Base exception for chat history operations."""
    pass


class ChatMessage:
    """Represents a single chat message."""

    def __init__(
        self,
        message_id: int,
        role: str,
        content: str,
        timestamp: datetime,
        model: str = "unknown",
        processing_time: float = 0.0,
        tokens: Optional[Dict[str, int]] = None
    ):
        """
        Initialize a chat message.

        Args:
            message_id: Sequential ID within conversation
            role: Message role ("user", "assistant", "system")
            content: Message text content
            timestamp: When message was created
            model: AI model used (for assistant messages)
            processing_time: Inference time in seconds
            tokens: Token usage information
        """
        self.message_id = message_id
        self.role = role
        self.content = content
        self.timestamp = timestamp
        self.model = model
        self.processing_time = processing_time
        self.tokens = tokens or {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert message to dictionary for JSON serialization."""
        return {
            "message_id": self.message_id,
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "model": self.model,
            "processing_time": self.processing_time,
            "tokens": self.tokens
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ChatMessage':
        """Create message from dictionary."""
        return cls(
            message_id=data["message_id"],
            role=data["role"],
            content=data["content"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            model=data.get("model", "unknown"),
            processing_time=data.get("processing_time", 0.0),
            tokens=data.get("tokens", {})
        )


class ConversationMetadata:
    """Metadata for a chat conversation."""

    def __init__(
        self,
        screenshot_id: str,
        screenshot_filename: str,
        screenshot_path: str,
        created_at: datetime,
        updated_at: datetime,
        message_count: int = 0,
        model_used: str = "unknown",
        total_tokens: int = 0
    ):
        """
        Initialize conversation metadata.

        Args:
            screenshot_id: Hash of the screenshot file
            screenshot_filename: Original filename of screenshot
            screenshot_path: Full path to screenshot file
            created_at: When conversation started
            updated_at: When conversation was last modified
            message_count: Number of messages in conversation
            model_used: Primary AI model used
            total_tokens: Total token count
        """
        self.screenshot_id = screenshot_id
        self.screenshot_filename = screenshot_filename
        self.screenshot_path = screenshot_path
        self.created_at = created_at
        self.updated_at = updated_at
        self.message_count = message_count
        self.model_used = model_used
        self.total_tokens = total_tokens

    def to_dict(self) -> Dict[str, Any]:
        """Convert metadata to dictionary for JSON serialization."""
        return {
            "screenshot_id": self.screenshot_id,
            "screenshot_filename": self.screenshot_filename,
            "screenshot_path": self.screenshot_path,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "message_count": self.message_count,
            "model_used": self.model_used,
            "total_tokens": self.total_tokens
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ConversationMetadata':
        """Create metadata from dictionary."""
        return cls(
            screenshot_id=data["screenshot_id"],
            screenshot_filename=data["screenshot_filename"],
            screenshot_path=data["screenshot_path"],
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            message_count=data.get("message_count", 0),
            model_used=data.get("model_used", "unknown"),
            total_tokens=data.get("total_tokens", 0)
        )


class ChatHistoryManager:
    """
    Manages chat history using file-based JSON storage.

    Organizes chat conversations by screenshot hash with atomic file operations
    and proper error handling for concurrent access.
    """

    def __init__(self, chat_history_directory: str, logger=None):
        """
        Initialize the chat history manager.

        Args:
            chat_history_directory: Base directory for chat storage
            logger: Optional logger instance
        """
        self.chat_directory = Path(chat_history_directory)
        self.logger = logger or logging.getLogger(__name__)
        self._lock = asyncio.Lock()
        self._initialized = False

        # Ensure directory exists
        self.chat_directory.mkdir(parents=True, exist_ok=True)

    async def initialize(self) -> None:
        """Initialize the chat history manager."""
        if self._initialized:
            return

        try:
            # Validate directory permissions
            await self._validate_directory()
            self._initialized = True
            self.logger.debug("ChatHistoryManager ready for directory "
                             f"{self.chat_directory}")

        except Exception as e:
            self.logger.error(f"Failed to initialize ChatHistoryManager: {e}")
            raise ChatHistoryError(f"Initialization failed: {e}") from e

    async def load_conversation(self, screenshot_hash: str) -> List[ChatMessage]:
        """
        Load all messages for a conversation.

        Args:
            screenshot_hash: SHA-256 hash of screenshot file

        Returns:
            List of ChatMessage objects ordered by message_id
        """
        if not self._initialized:
            await self.initialize()

        try:
            conversation_dir = self._get_conversation_directory(screenshot_hash)

            if not conversation_dir.exists():
                return []

            messages = []
            message_files = list(conversation_dir.glob("message_*.json"))

            # Sort by message number extracted from filename
            message_files.sort(key=lambda f: int(f.stem.split('_')[1]))

            for message_file in message_files:
                try:
                    message_data = await self._read_json_file(message_file)
                    message = ChatMessage.from_dict(message_data)
                    messages.append(message)

                except Exception as e:
                    self.logger.warning(f"Failed to load message {message_file}: {e}")
                    continue

            self.logger.debug(f"Loaded {len(messages)} messages for conversation {screenshot_hash}")
            return messages

        except Exception as e:
            self.logger.error(f"Failed to load conversation {screenshot_hash}: {e}")
            return []

    async def save_message(
        self,
        screenshot_hash: str,
        message: ChatMessage,
        screenshot_metadata: Optional['ScreenshotMetadata'] = None
    ) -> bool:
        """
        Save a message to the conversation.

        Args:
            screenshot_hash: SHA-256 hash of screenshot file
            message: ChatMessage to save
            screenshot_metadata: Optional screenshot metadata for conversation

        Returns:
            True if saved successfully
        """
        if not self._initialized:
            await self.initialize()

        async with self._lock:
            try:
                conversation_dir = self._get_conversation_directory(screenshot_hash)
                conversation_dir.mkdir(parents=True, exist_ok=True)

                # Generate filename with zero-padded message ID
                filename = f"message_{message.message_id:04d}.json"
                message_file = conversation_dir / filename

                # Save message atomically
                await self._write_json_file(message_file, message.to_dict())

                # Update conversation metadata
                await self._update_conversation_metadata(
                    screenshot_hash,
                    message,
                    screenshot_metadata
                )

                self.logger.debug(f"Saved message {message.message_id} to conversation {screenshot_hash}")
                return True

            except Exception as e:
                self.logger.error(f"Failed to save message to conversation {screenshot_hash}: {e}")
                return False

    async def get_conversation_metadata(self, screenshot_hash: str) -> Optional[ConversationMetadata]:
        """
        Get metadata for a conversation.

        Args:
            screenshot_hash: SHA-256 hash of screenshot file

        Returns:
            ConversationMetadata object or None if not found
        """
        if not self._initialized:
            await self.initialize()

        try:
            conversation_dir = self._get_conversation_directory(screenshot_hash)
            metadata_file = conversation_dir / "metadata.json"

            if not metadata_file.exists():
                return None

            metadata_data = await self._read_json_file(metadata_file)
            return ConversationMetadata.from_dict(metadata_data)

        except Exception as e:
            self.logger.error(f"Failed to get conversation metadata {screenshot_hash}: {e}")
            return None

    async def delete_conversation(self, screenshot_hash: str) -> bool:
        """
        Delete an entire conversation.

        Args:
            screenshot_hash: SHA-256 hash of screenshot file

        Returns:
            True if deleted successfully
        """
        if not self._initialized:
            await self.initialize()

        async with self._lock:
            try:
                conversation_dir = self._get_conversation_directory(screenshot_hash)

                if conversation_dir.exists():
                    # Remove all files in the conversation directory
                    for file_path in conversation_dir.iterdir():
                        if file_path.is_file():
                            file_path.unlink()

                    # Remove the directory
                    conversation_dir.rmdir()

                    self.logger.info(f"Deleted conversation {screenshot_hash}")

                return True

            except Exception as e:
                self.logger.error(f"Failed to delete conversation {screenshot_hash}: {e}")
                return False

    async def get_all_conversation_hashes(self) -> List[str]:
        """
        Get all conversation hashes (screenshot IDs).

        Returns:
            List of screenshot hash strings
        """
        if not self._initialized:
            await self.initialize()

        try:
            conversation_hashes = []

            for item in self.chat_directory.iterdir():
                if item.is_dir() and len(item.name) == 64:  # SHA-256 length
                    conversation_hashes.append(item.name)

            return conversation_hashes

        except Exception as e:
            self.logger.error(f"Failed to get conversation hashes: {e}")
            return []

    async def cleanup_old_conversations(self, cutoff_date: datetime) -> int:
        """
        Clean up conversations older than cutoff date.

        Args:
            cutoff_date: Delete conversations older than this date

        Returns:
            Number of conversations deleted
        """
        if not self._initialized:
            await self.initialize()

        try:
            deleted_count = 0
            conversation_hashes = await self.get_all_conversation_hashes()

            for screenshot_hash in conversation_hashes:
                try:
                    metadata = await self.get_conversation_metadata(screenshot_hash)

                    if metadata and metadata.updated_at < cutoff_date:
                        if await self.delete_conversation(screenshot_hash):
                            deleted_count += 1

                except Exception as e:
                    self.logger.warning(f"Failed to check conversation {screenshot_hash} for cleanup: {e}")

            if deleted_count > 0:
                self.logger.info(f"Cleaned up {deleted_count} old conversations")

            return deleted_count

        except Exception as e:
            self.logger.error(f"Failed to cleanup old conversations: {e}")
            return 0

    async def export_conversation(self, screenshot_hash: str) -> Optional[str]:
        """
        Export conversation as JSON string.

        Args:
            screenshot_hash: SHA-256 hash of screenshot file

        Returns:
            JSON string of conversation or None if not found
        """
        try:
            messages = await self.load_conversation(screenshot_hash)
            metadata = await self.get_conversation_metadata(screenshot_hash)

            if not messages and not metadata:
                return None

            export_data = {
                "metadata": metadata.to_dict() if metadata else None,
                "messages": [msg.to_dict() for msg in messages]
            }

            return json.dumps(export_data, indent=2)

        except Exception as e:
            self.logger.error(f"Failed to export conversation {screenshot_hash}: {e}")
            return None

    def compute_screenshot_hash(self, file_path: str) -> str:
        """
        Compute SHA-256 hash of a screenshot file.

        Args:
            file_path: Path to screenshot file

        Returns:
            SHA-256 hash as hexadecimal string
        """
        try:
            hash_sha256 = hashlib.sha256()

            with open(file_path, "rb") as f:
                # Read in chunks to handle large files
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_sha256.update(chunk)

            return hash_sha256.hexdigest()

        except Exception as e:
            self.logger.error(f"Failed to compute hash for {file_path}: {e}")
            raise ChatHistoryError(f"Hash computation failed: {e}") from e

    # Private methods

    def _get_conversation_directory(self, screenshot_hash: str) -> Path:
        """Get the directory path for a conversation."""
        return self.chat_directory / screenshot_hash

    async def _validate_directory(self) -> None:
        """Validate that the directory is writable."""
        try:
            test_file = self.chat_directory / ".test_write"
            test_file.touch()
            test_file.unlink()

        except Exception as e:
            raise ChatHistoryError(f"Directory not writable: {e}") from e

    async def _read_json_file(self, file_path: Path) -> Dict[str, Any]:
        """Read JSON file asynchronously."""
        try:
            loop = asyncio.get_event_loop()
            content = await loop.run_in_executor(
                None,
                lambda: file_path.read_text(encoding='utf-8')
            )
            return json.loads(content)

        except Exception as e:
            raise ChatHistoryError(f"Failed to read JSON file {file_path}: {e}") from e

    async def _write_json_file(self, file_path: Path, data: Dict[str, Any]) -> None:
        """Write JSON file atomically."""
        temp_path = file_path.with_suffix(file_path.suffix + '.tmp')

        try:
            # Write to temporary file first
            loop = asyncio.get_event_loop()
            json_content = json.dumps(data, indent=2, ensure_ascii=False)

            await loop.run_in_executor(
                None,
                lambda: temp_path.write_text(json_content, encoding='utf-8')
            )

            # Atomic rename (replace handles existing files on Windows)
            await loop.run_in_executor(None, lambda: temp_path.replace(file_path))

        except Exception as e:
            # Clean up temp file if it exists
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass

            raise ChatHistoryError(f"Failed to write JSON file {file_path}: {e}") from e

    async def _update_conversation_metadata(
        self,
        screenshot_hash: str,
        message: ChatMessage,
        screenshot_metadata: Optional['ScreenshotMetadata'] = None
    ) -> None:
        """Update conversation metadata file."""
        try:
            conversation_dir = self._get_conversation_directory(screenshot_hash)
            metadata_file = conversation_dir / "metadata.json"

            # Load existing metadata or create new
            if metadata_file.exists():
                existing_data = await self._read_json_file(metadata_file)
                metadata = ConversationMetadata.from_dict(existing_data)
                metadata.updated_at = datetime.now()
                metadata.message_count += 1

                # Update model and token info if it's an assistant message
                if message.role == "assistant":
                    metadata.model_used = message.model
                    if message.tokens:
                        metadata.total_tokens += sum(message.tokens.values())
            else:
                # Create new metadata
                metadata = ConversationMetadata(
                    screenshot_id=screenshot_hash,
                    screenshot_filename=screenshot_metadata.filename if screenshot_metadata else "unknown",
                    screenshot_path=screenshot_metadata.full_path if screenshot_metadata else "",
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                    message_count=1,
                    model_used=message.model if message.role == "assistant" else "unknown",
                    total_tokens=sum(message.tokens.values()) if message.tokens else 0
                )

            # Save updated metadata
            await self._write_json_file(metadata_file, metadata.to_dict())

        except Exception as e:
            self.logger.error(f"Failed to update conversation metadata: {e}")
            # Don't raise - metadata update failure shouldn't prevent message save
