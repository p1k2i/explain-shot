"""
Ollama Client Module

Provides integration with the local Ollama server for AI-powered screenshot analysis.
Handles connection management, model selection, image processing, streaming responses,
and graceful fallbacks to maintain application reliability.
"""

import asyncio
import base64
import logging
from io import BytesIO
from datetime import datetime
from typing import Optional, Dict, Any, List, Callable
from pathlib import Path

try:
    import ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    ollama = None  # type: ignore
    OLLAMA_AVAILABLE = False

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    Image = None  # type: ignore
    PIL_AVAILABLE = False

from ..controllers.event_bus import EventBus
from .. import EventTypes
from .chat_history_manager import ChatHistoryManager, ChatMessage

logger = logging.getLogger(__name__)


class OllamaError(Exception):
    """Base exception for Ollama-related errors."""
    pass


class ConnectionError(OllamaError):
    """Raised when connection to Ollama server fails."""
    pass


class ModelError(OllamaError):
    """Raised when model-related operations fail."""
    pass


class ImageProcessingError(OllamaError):
    """Raised when image processing fails."""
    pass


class OllamaClient:
    """
    Ollama integration client for AI-powered screenshot analysis.

    Provides asynchronous interface to Ollama server with health monitoring,
    model management, streaming responses, and offline fallback support.
    """

    def __init__(
        self,
        event_bus: EventBus,
        chat_history_manager: Optional[ChatHistoryManager] = None,
        database_manager=None,  # Legacy - will be deprecated
        preset_manager=None,    # New preset manager
        settings_manager=None,
        server_url: str = "http://localhost:11434",
        default_model: str = "gemma2:9b"
    ):
        """
        Initialize OllamaClient.

        Args:
            event_bus: EventBus for event-driven communication
            chat_history_manager: ChatHistoryManager for JSON file storage
            database_manager: DatabaseManager for legacy support (deprecated)
            preset_manager: PresetManager for preset operations
            settings_manager: SettingsManager for configuration
            server_url: Ollama server URL
            default_model: Default model name
        """
        self.event_bus = event_bus
        self.chat_history_manager = chat_history_manager
        self.database_manager = database_manager  # Legacy support
        self.preset_manager = preset_manager      # New preset manager
        self.settings_manager = settings_manager

        # Configuration
        self.server_url = server_url
        self.current_model = default_model
        self.timeout_seconds = 30
        self.max_retries = 3
        self.enable_streaming = True

        # State management
        self._initialized = False
        self._is_online = False
        self._available_models: List[str] = []
        self._health_check_task: Optional[asyncio.Task] = None
        self._retry_count = 0
        self._last_health_check = datetime.now()

        # Conversation context per screenshot (loaded from files on demand)
        self._conversation_history: Dict[str, List[Dict]] = {}

        # Connection settings
        self._connection_timeout = 5.0
        self._health_check_interval = 30.0
        self._retry_delays = [1, 2, 4, 8, 16]  # Exponential backoff

        logger.info("OllamaClient initialized with server: %s", server_url)

    async def initialize(self) -> bool:
        """
        Initialize the Ollama client and perform initial health check.

        Returns:
            True if initialization successful
        """
        if self._initialized:
            return True

        try:
            logger.info("Initializing OllamaClient...")

            # Check if ollama library is available
            if not OLLAMA_AVAILABLE:
                logger.error("Ollama library not available - falling back to offline mode")
                await self._switch_to_offline_mode("ollama_library_missing")
                return True  # Still return True to continue initialization

            # Load settings if available
            if self.settings_manager:
                await self._load_settings()

            # Subscribe to events
            await self._subscribe_to_events()

            # Perform initial health check
            await self._perform_health_check()

            # Start periodic health monitoring
            self._health_check_task = asyncio.create_task(self._health_monitor_loop())

            self._initialized = True
            logger.info("OllamaClient initialization complete - Online: %s", self._is_online)
            return True

        except Exception as e:
            logger.error("OllamaClient initialization failed: %s", e)
            await self._switch_to_offline_mode("initialization_failed")
            return False

    async def _load_settings(self) -> None:
        """Load Ollama configuration from settings manager."""
        try:
            if not self.settings_manager:
                return

            settings = await self.settings_manager.load_settings()
            ollama_config = settings.ollama

            self.server_url = ollama_config.server_url
            self.current_model = ollama_config.default_model
            self.timeout_seconds = ollama_config.timeout_seconds
            self.max_retries = ollama_config.max_retries
            self.enable_streaming = ollama_config.enable_streaming

            logger.info("Loaded Ollama settings - Model: %s, Server: %s",
                       self.current_model, self.server_url)

        except Exception as e:
            logger.error("Failed to load Ollama settings: %s", e)

    async def _subscribe_to_events(self) -> None:
        """Subscribe to relevant application events."""
        await self.event_bus.subscribe(
            EventTypes.SETTINGS_UPDATED,
            self._handle_settings_updated,
            priority=80
        )

        await self.event_bus.subscribe(
            EventTypes.GALLERY_CHAT_MESSAGE_SENT,
            self._handle_chat_message,
            priority=90
        )

        await self.event_bus.subscribe(
            EventTypes.GALLERY_PRESET_EXECUTED,
            self._handle_preset_execution,
            priority=90
        )

    async def _perform_health_check(self) -> bool:
        """
        Perform health check against Ollama server.

        Returns:
            True if server is healthy
        """
        if not OLLAMA_AVAILABLE:
            return False

        try:
            logger.debug("Performing Ollama health check...")

            # Configure ollama client
            ollama_client = ollama.AsyncClient(host=self.server_url)  # type: ignore

            # Simple health check with timeout
            response = await asyncio.wait_for(
                ollama_client.list(),
                timeout=self._connection_timeout
            )

            # Extract available models
            if 'models' in response:
                self._available_models = [model.get('name', model.get('model', '')) for model in response['models']]
                # Filter out empty names
                self._available_models = [name for name in self._available_models if name]
                logger.info("Available Ollama models: %s", self._available_models)

            # Verify current model is available
            if self.current_model not in self._available_models and self._available_models:
                logger.warning("Current model '%s' not found, using '%s'",
                             self.current_model, self._available_models[0])
                self.current_model = self._available_models[0]

            self._is_online = True
            self._retry_count = 0
            self._last_health_check = datetime.now()

            # Emit online event
            await self.event_bus.emit(
                EventTypes.OLLAMA_RESPONSE_RECEIVED,
                {
                    'status': 'online',
                    'models': self._available_models,
                    'current_model': self.current_model
                },
                source="OllamaClient"
            )

            logger.info("Ollama health check passed - Server online")
            return True

        except asyncio.TimeoutError:
            logger.warning("Ollama health check timed out")
            await self._handle_connection_failure("timeout")
            return False

        except Exception as e:
            logger.warning("Ollama health check failed: %s", e)
            await self._handle_connection_failure(str(e))
            return False

    async def _handle_connection_failure(self, reason: str) -> None:
        """Handle connection failure with retry logic."""
        self._is_online = False
        self._retry_count += 1

        if self._retry_count <= self.max_retries:
            retry_delay = self._retry_delays[min(self._retry_count - 1, len(self._retry_delays) - 1)]
            logger.info("Ollama connection failed (attempt %d/%d), retrying in %ds: %s",
                       self._retry_count, self.max_retries, retry_delay, reason)

            await asyncio.sleep(retry_delay)
            await self._perform_health_check()
        else:
            logger.error("Ollama connection failed after %d attempts, switching to offline mode",
                        self.max_retries)
            await self._switch_to_offline_mode(reason)

    async def _switch_to_offline_mode(self, reason: str) -> None:
        """Switch to offline mode and emit event."""
        self._is_online = False

        await self.event_bus.emit(
            "ollama.offline",
            {
                'reason': reason,
                'retry_count': self._retry_count,
                'timestamp': datetime.now().isoformat()
            },
            source="OllamaClient"
        )

        logger.warning("Ollama client switched to offline mode: %s", reason)

    async def _health_monitor_loop(self) -> None:
        """Background health monitoring loop."""
        try:
            while True:
                await asyncio.sleep(self._health_check_interval)

                # Only check if we've been offline or it's been a while
                time_since_check = (datetime.now() - self._last_health_check).total_seconds()

                if not self._is_online or time_since_check > self._health_check_interval:
                    await self._perform_health_check()

        except asyncio.CancelledError:
            logger.info("Health monitor loop cancelled")
        except Exception as e:
            logger.error("Error in health monitor loop: %s", e)

    async def send_chat_message(
        self,
        screenshot_hash: str,
        prompt: str,
        image_path: Optional[str] = None,
        stream_callback: Optional[Callable[[str], None]] = None,
        screenshot_metadata=None  # ScreenshotMetadata for context
    ) -> Dict[str, Any]:
        """
        Send chat message with screenshot analysis.

        Args:
            screenshot_hash: Hash of the screenshot being analyzed
            prompt: User prompt text
            image_path: Path to screenshot image file
            stream_callback: Optional callback for streaming updates
            screenshot_metadata: Optional ScreenshotMetadata for context

        Returns:
            Dictionary with response data
        """
        try:
            if not self._is_online:
                return await self._generate_mock_response(screenshot_hash, prompt)

            # Prepare image data
            image_data = None
            if image_path and Path(image_path).exists():
                image_data = await self._process_image(image_path)

            # Build conversation context
            messages = await self._build_conversation_messages(screenshot_hash, prompt, image_data)

            # Send request to Ollama
            if self.enable_streaming and stream_callback:
                response = await self._send_streaming_request(messages, stream_callback)
            else:
                response = await self._send_standard_request(messages)

            # Store in chat history files using ChatHistoryManager
            if self.chat_history_manager:
                await self._store_chat_history_json(screenshot_hash, prompt, response, screenshot_metadata)
            else:
                logger.warning("No ChatHistoryManager available - chat history not saved")

            # Emit success event
            await self.event_bus.emit(
                EventTypes.OLLAMA_RESPONSE_RECEIVED,
                {
                    'screenshot_hash': screenshot_hash,
                    'prompt': prompt,
                    'response': response['content'],
                    'model': self.current_model,
                    'processing_time': response.get('processing_time', 0),
                    'timestamp': datetime.now().isoformat()
                },
                source="OllamaClient"
            )

            return response

        except Exception as e:
            logger.error("Failed to send chat message: %s", e)

            # Emit error event
            await self.event_bus.emit(
                EventTypes.ERROR_OCCURRED,
                {
                    'error': 'ollama_chat_failed',
                    'message': str(e),
                    'screenshot_hash': screenshot_hash,
                    'prompt': prompt
                },
                source="OllamaClient"
            )

            # Return mock response as fallback
            return await self._generate_mock_response(screenshot_hash, prompt, error=str(e))

    async def _process_image(self, image_path: str) -> Optional[str]:
        """
        Process image for Ollama request.

        Args:
            image_path: Path to image file

        Returns:
            Base64 encoded image data or None if processing failed
        """
        try:
            if not PIL_AVAILABLE:
                logger.warning("PIL not available for image processing")
                return None

            # Load and process image
            with Image.open(image_path) as img:  # type: ignore
                # Convert to RGB if necessary
                if img.mode != 'RGB':
                    img = img.convert('RGB')

                # Resize large images to reduce token usage
                max_size = 1920
                if img.width > max_size or img.height > max_size:
                    img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)  # type: ignore
                    logger.debug("Resized image to %dx%d", img.width, img.height)

                # Convert to JPEG with compression
                buffer = BytesIO()
                img.save(buffer, format='JPEG', quality=85, optimize=True)
                buffer.seek(0)

                # Encode to base64
                image_data = base64.b64encode(buffer.getvalue()).decode('utf-8')

                logger.debug("Processed image: %s -> %d bytes",
                           Path(image_path).name, len(image_data))

                return image_data

        except Exception as e:
            logger.error("Image processing failed for %s: %s", image_path, e)
            raise ImageProcessingError(f"Failed to process image: {e}")

    async def _build_conversation_messages(
        self,
        screenshot_hash: str,
        prompt: str,
        image_data: Optional[str]
    ) -> List[Dict]:
        """Build conversation messages for Ollama request."""
        messages = []

        # Load conversation history from files
        try:
            if self.chat_history_manager:
                chat_messages = await self.chat_history_manager.load_conversation(screenshot_hash)

                # Convert ChatMessage objects to Ollama format
                for chat_msg in chat_messages:
                    messages.append({
                        "role": chat_msg.role,
                        "content": chat_msg.content
                    })

            # Fallback to memory cache if available
            elif screenshot_hash in self._conversation_history:
                messages.extend(self._conversation_history[screenshot_hash])

        except Exception as e:
            logger.warning(f"Failed to load conversation history: {e}")

        # Build current message
        message = {
            "role": "user",
            "content": prompt
        }

        # Add image if available
        if image_data:
            message["images"] = [image_data]  # type: ignore

        messages.append(message)
        return messages

    async def _send_streaming_request(
        self,
        messages: List[Dict],
        stream_callback: Callable[[str], None]
    ) -> Dict[str, Any]:
        """Send streaming request to Ollama."""
        try:
            start_time = datetime.now()
            full_response = ""

            ollama_client = ollama.AsyncClient(host=self.server_url)  # type: ignore

            async for chunk in await ollama_client.chat(
                model=self.current_model,
                messages=messages,
                stream=True
            ):
                if chunk.get('message', {}).get('content'):
                    content = chunk['message']['content']
                    full_response += content

                    # Call stream callback
                    if stream_callback:
                        stream_callback(content)

                    # Emit streaming update event
                    await self.event_bus.emit(
                        "ollama.streaming.update",
                        {
                            'content': content,
                            'partial_response': full_response
                        },
                        source="OllamaClient"
                    )

            processing_time = (datetime.now() - start_time).total_seconds()

            return {
                'content': full_response,
                'model': self.current_model,
                'processing_time': processing_time,
                'streaming': True
            }

        except Exception as e:
            logger.error("Streaming request failed: %s", e)
            raise ConnectionError(f"Streaming request failed: {e}")

    async def _send_standard_request(self, messages: List[Dict]) -> Dict[str, Any]:
        """Send standard (non-streaming) request to Ollama."""
        try:
            start_time = datetime.now()

            ollama_client = ollama.AsyncClient(host=self.server_url)  # type: ignore

            response = await asyncio.wait_for(
                ollama_client.chat(
                    model=self.current_model,
                    messages=messages
                ),
                timeout=self.timeout_seconds
            )

            processing_time = (datetime.now() - start_time).total_seconds()

            return {
                'content': response['message']['content'],
                'model': self.current_model,
                'processing_time': processing_time,
                'streaming': False
            }

        except asyncio.TimeoutError:
            raise ConnectionError(f"Request timed out after {self.timeout_seconds}s")
        except Exception as e:
            logger.error("Standard request failed: %s", e)
            raise ConnectionError(f"Request failed: {e}")

    def _update_conversation_history(self, screenshot_hash: str, prompt: str, response: str) -> None:
        """Update in-memory conversation history for context (legacy support)."""
        if screenshot_hash not in self._conversation_history:
            self._conversation_history[screenshot_hash] = []

        # Add user message
        self._conversation_history[screenshot_hash].append({
            "role": "user",
            "content": prompt
        })

        # Add assistant response
        self._conversation_history[screenshot_hash].append({
            "role": "assistant",
            "content": response
        })

        # Limit conversation history to prevent token overflow
        max_messages = 10
        if len(self._conversation_history[screenshot_hash]) > max_messages:
            self._conversation_history[screenshot_hash] = self._conversation_history[screenshot_hash][-max_messages:]

    async def _store_chat_history_json(
        self,
        screenshot_hash: str,
        prompt: str,
        response: Dict[str, Any],
        screenshot_metadata=None
    ) -> None:
        """Store AI response in JSON files using ChatHistoryManager."""
        try:
            if not self.chat_history_manager:
                return

            # Load existing conversation to get next message ID
            existing_messages = await self.chat_history_manager.load_conversation(screenshot_hash)
            next_id = len(existing_messages) + 1

            # Note: User message should already be saved by GalleryWindow
            # Only save the assistant response here

            # Create assistant message
            assistant_message = ChatMessage(
                message_id=next_id,
                role="assistant",
                content=response['content'],
                timestamp=datetime.now(),
                model=response.get('model', self.current_model),
                processing_time=response.get('processing_time', 0.0),
                tokens=response.get('tokens', {})
            )

            # Save assistant message
            await self.chat_history_manager.save_message(
                screenshot_hash,
                assistant_message,
                screenshot_metadata
            )

        except Exception as e:
            logger.error("Failed to store AI response in JSON: %s", e)

    async def _generate_mock_response(
        self,
        screenshot_hash: str,
        prompt: str,
        error: Optional[str] = None
    ) -> Dict[str, Any]:
        """Generate mock response when Ollama is unavailable."""

        if error:
            mock_content = (
                f"I apologize, but I'm currently unable to analyze your screenshot due to a connection issue: {error}. "
                f"This is a placeholder response. Once the AI service is restored, I'll be able to provide detailed "
                f"analysis of your screenshot based on your request: '{prompt}'"
            )
        else:
            mock_content = (
                f"This is a simulated AI response to your request: '{prompt}'. "
                f"I can see you're asking about screenshot with hash {screenshot_hash[:8]}..., but I'm currently operating in offline mode. "
                f"When connected to the AI service, I would provide detailed analysis of the visual content, "
                f"identify UI elements, explain functionality, and answer your specific questions about what's shown in the image."
            )

        return {
            'content': mock_content,
            'model': 'offline_mode',
            'processing_time': 0.1,
            'streaming': False,
            'mock': True
        }

    async def get_available_models(self) -> List[str]:
        """Get list of available models from Ollama server."""
        if not self._is_online:
            return []

        try:
            ollama_client = ollama.AsyncClient(host=self.server_url)  # type: ignore
            response = await ollama_client.list()

            if 'models' in response:
                models = [model.get('name', model.get('model', '')) for model in response['models']]
                # Filter out empty names
                models = [name for name in models if name]
                self._available_models = models
                return models

        except Exception as e:
            logger.error("Failed to get available models: %s", e)

        return []

    async def switch_model(self, model_name: str) -> bool:
        """
        Switch to a different model.

        Args:
            model_name: Name of the model to switch to

        Returns:
            True if switch successful
        """
        try:
            # Verify model is available
            available_models = await self.get_available_models()

            if model_name not in available_models:
                logger.error("Model '%s' not available. Available models: %s",
                           model_name, available_models)
                return False

            old_model = self.current_model
            self.current_model = model_name

            # Emit model switch event
            await self.event_bus.emit(
                "ollama.model.switched",
                {
                    'old_model': old_model,
                    'new_model': model_name,
                    'timestamp': datetime.now().isoformat()
                },
                source="OllamaClient"
            )

            logger.info("Switched from model '%s' to '%s'", old_model, model_name)
            return True

        except Exception as e:
            logger.error("Failed to switch model to '%s': %s", model_name, e)
            return False

    async def _handle_settings_updated(self, event_data) -> None:
        """Handle settings update events."""
        try:
            if not event_data.data or 'key' not in event_data.data:
                return

            key = event_data.data['key']
            value = event_data.data['value']

            # Handle Ollama-specific settings
            if key == 'ollama.default_model':
                await self.switch_model(value)
            elif key == 'ollama.server_url':
                self.server_url = value
                # Trigger health check for new server
                await self._perform_health_check()
            elif key in ['ollama.timeout_seconds', 'ollama.max_retries', 'ollama.enable_streaming']:
                # Reload all settings
                await self._load_settings()

        except Exception as e:
            logger.error("Error handling settings update: %s", e)

    async def _handle_chat_message(self, event_data) -> None:
        """Handle chat message events from gallery."""
        try:
            data = event_data.data
            message = data.get('message', '')
            context = data.get('context', {})

            # Get screenshot hash from context
            screenshot_hash = context.get('selected_screenshot') or context.get('screenshot_hash')
            image_path = context.get('image_path')
            screenshot_metadata = context.get('screenshot_metadata')

            if not screenshot_hash:
                logger.warning("No screenshot selected for chat message")
                return

            # Send chat message
            await self.send_chat_message(
                screenshot_hash=screenshot_hash,
                prompt=message,
                image_path=image_path,
                screenshot_metadata=screenshot_metadata
            )

        except Exception as e:
            logger.error("Error handling chat message: %s", e)

    async def _handle_preset_execution(self, event_data) -> None:
        """Handle preset execution events from gallery."""
        try:
            data = event_data.data
            preset_id = data.get('preset_id')
            screenshot_context = data.get('screenshot_context')

            if not preset_id or not screenshot_context:
                logger.warning("Invalid preset execution data")
                return

            # Handle new dict format
            if isinstance(screenshot_context, dict):
                screenshot_hash = screenshot_context.get('selected_screenshot')
                image_path = screenshot_context.get('image_path')
                screenshot_metadata = screenshot_context.get('screenshot_metadata')
            else:
                # Legacy support: screenshot_context as string (shouldn't happen with new code)
                logger.warning("Received legacy string context for preset execution")
                return

            if not screenshot_hash:
                logger.warning("No valid screenshot context for preset execution")
                return

            # Get preset details from preset_manager (new) or database_manager (legacy fallback)
            preset = None
            if self.preset_manager:
                preset = await self.preset_manager.get_preset_by_id(preset_id)
            elif self.database_manager:
                # Legacy fallback - will be removed
                preset = await self.database_manager.get_preset_by_id(preset_id)
            else:
                logger.error("No preset manager available for preset execution")
                return

            if not preset:
                logger.error("Preset not found: %s", preset_id)
                return

            # Build enhanced prompt with context
            enhanced_prompt = self._build_preset_prompt(preset.prompt, screenshot_hash)

            # Send chat message
            await self.send_chat_message(
                screenshot_hash=screenshot_hash,
                prompt=enhanced_prompt,
                image_path=image_path,
                screenshot_metadata=screenshot_metadata
            )

        except Exception as e:
            logger.error("Error handling preset execution: %s", e)

    def _build_preset_prompt(self, preset_prompt: str, screenshot_hash: str) -> str:
        """Build enhanced prompt for preset execution."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        return f"""System Context: Analyzing screenshot with ID {screenshot_hash[:8]}... captured at {timestamp}

User Request: {preset_prompt}

Please provide a detailed analysis based on the image content and user request above."""

    async def get_conversation_history(self, screenshot_hash: str) -> List[Dict]:
        """Get conversation history for a screenshot."""
        try:
            if self.chat_history_manager:
                # Load from JSON files
                chat_messages = await self.chat_history_manager.load_conversation(screenshot_hash)
                return [{"role": msg.role, "content": msg.content} for msg in chat_messages]
            else:
                # Fallback to memory cache
                return self._conversation_history.get(screenshot_hash, [])
        except Exception as e:
            logger.error(f"Failed to get conversation history: {e}")
            return []

    def is_online(self) -> bool:
        """Check if Ollama server is online."""
        return self._is_online

    def get_current_model(self) -> str:
        """Get current model name."""
        return self.current_model

    async def shutdown(self) -> None:
        """Shutdown the Ollama client."""
        logger.info("Shutting down OllamaClient...")

        # Cancel health check task
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass

        # Clear conversation history
        self._conversation_history.clear()

        self._initialized = False
        logger.info("OllamaClient shutdown complete")
