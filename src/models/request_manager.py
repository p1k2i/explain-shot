"""
Enhanced Request Manager for Optimized AI Request Handling

This module provides request queuing with concurrency limits, timeout management,
retry logic, and connection pooling for Ollama requests with backpressure handling.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, Optional, Any, Callable, Set
import uuid

logger = logging.getLogger(__name__)


class RequestPriority(Enum):
    """Priority levels for request processing."""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    URGENT = 3


class RequestStatus(Enum):
    """Status of a request."""
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


@dataclass
class OllamaRequest:
    """Represents an Ollama API request."""
    id: str
    screenshot_id: int
    prompt: str
    image_path: Optional[str]
    model_name: str
    priority: RequestPriority
    stream_callback: Optional[Callable] = None
    timeout: float = 30.0
    max_retries: int = 3
    created_at: Optional[datetime] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()


@dataclass
class RequestHandle:
    """Handle for tracking and controlling requests."""
    request_id: str
    future: asyncio.Future
    request: Optional[OllamaRequest]
    status: RequestStatus = RequestStatus.QUEUED

    def cancel(self) -> bool:
        """Cancel the request if possible."""
        if not self.future.done():
            return self.future.cancel()
        return False

    def is_done(self) -> bool:
        """Check if request is completed."""
        return self.future.done()


@dataclass
class QueueStatus:
    """Status of the request queue."""
    total_queued: int
    processing_count: int
    completed_count: int
    failed_count: int
    average_processing_time: float
    queue_depth_by_priority: Dict[RequestPriority, int]


@dataclass
class RequestConfig:
    """Configuration for request management."""
    max_concurrent: int = 1
    queue_max_size: int = 10
    default_timeout: float = 30.0
    max_retries: int = 3
    retry_delay: float = 1.0
    retry_backoff_multiplier: float = 2.0
    enable_request_deduplication: bool = True
    request_rate_limit: float = 0.0  # seconds between requests


class RequestManager:
    """
    Enhanced request manager for Ollama API calls.

    Provides:
    - Request queuing with priority handling
    - Concurrency limits and rate limiting
    - Timeout management with retries
    - Request deduplication
    - Backpressure handling
    - Performance monitoring
    - Cancellation support
    """

    def __init__(self, ollama_client, event_bus, cache_manager=None, settings_manager=None):
        """
        Initialize the request manager.

        Args:
            ollama_client: OllamaClient instance for actual requests
            event_bus: EventBus for communication
            cache_manager: Optional CacheManager for response caching
            settings_manager: Optional settings manager
        """
        self.ollama_client = ollama_client
        self.event_bus = event_bus
        self.cache_manager = cache_manager
        self.settings_manager = settings_manager

        # Configuration
        self._config = RequestConfig()
        self._initialized = False

        # Request queuing
        self._request_queues: Dict[RequestPriority, asyncio.Queue] = {
            priority: asyncio.Queue() for priority in RequestPriority
        }
        self._processing_semaphore = asyncio.Semaphore(self._config.max_concurrent)

        # Request tracking
        self._active_requests: Dict[str, RequestHandle] = {}
        self._completed_requests: Dict[str, RequestHandle] = {}
        self._request_lock = asyncio.Lock()

        # Request deduplication
        self._pending_requests: Dict[str, RequestHandle] = {}
        self._dedup_lock = asyncio.Lock()

        # Rate limiting
        self._last_request_time = 0.0
        self._rate_limit_lock = asyncio.Lock()

        # Processing tasks
        self._processing_tasks: Set[asyncio.Task] = set()
        self._queue_processor_task: Optional[asyncio.Task] = None

        # Statistics
        self._stats = {
            'total_requests': 0,
            'completed_requests': 0,
            'failed_requests': 0,
            'cancelled_requests': 0,
            'timeout_requests': 0,
            'total_processing_time': 0.0,
            'last_reset': datetime.now()
        }

        logger.info("RequestManager initialized")

    async def initialize(self) -> None:
        """Initialize the request manager."""
        try:
            # Load configuration
            await self._load_settings()

            # Subscribe to events
            if self.event_bus:
                self.event_bus.subscribe("settings.changed", self._handle_settings_changed)
                self.event_bus.subscribe("request.cancel_all", self._handle_cancel_all_requests)

            # Start queue processor
            self._queue_processor_task = asyncio.create_task(self._process_request_queue())

            self._initialized = True
            logger.info("RequestManager initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize RequestManager: {e}")
            raise

    async def _load_settings(self) -> None:
        """Load request configuration from settings."""
        try:
            if not self.settings_manager:
                return

            settings = await self.settings_manager.load_settings()

            # Load request configuration if available
            if hasattr(settings, 'request_management'):
                req_config = settings.request_management
                self._config.max_concurrent = getattr(req_config, 'max_concurrent', 1)
                self._config.queue_max_size = getattr(req_config, 'queue_max_size', 10)
                self._config.default_timeout = getattr(req_config, 'default_timeout', 30.0)
                self._config.max_retries = getattr(req_config, 'max_retries', 3)
                self._config.retry_delay = getattr(req_config, 'retry_delay', 1.0)
                self._config.enable_request_deduplication = getattr(req_config, 'enable_request_deduplication', True)

                # Update semaphore if concurrency changed
                self._processing_semaphore = asyncio.Semaphore(self._config.max_concurrent)

            logger.debug(f"Loaded request settings - Max concurrent: {self._config.max_concurrent}, "
                        f"Queue size: {self._config.queue_max_size}")

        except Exception as e:
            logger.warning(f"Failed to load request settings: {e}")

    def _generate_request_key(self, screenshot_id: int, prompt: str, model_name: str) -> str:
        """Generate key for request deduplication."""
        return f"{screenshot_id}:{model_name}:{hash(prompt)}"

    async def enqueue_request(self,
                            screenshot_id: int,
                            prompt: str,
                            image_path: Optional[str] = None,
                            model_name: Optional[str] = None,
                            priority: RequestPriority = RequestPriority.NORMAL,
                            stream_callback: Optional[Callable] = None,
                            timeout: Optional[float] = None) -> RequestHandle:
        """
        Enqueue an Ollama request for processing.

        Args:
            screenshot_id: Screenshot ID
            prompt: User prompt
            image_path: Optional path to image
            model_name: AI model name
            priority: Request priority
            stream_callback: Optional streaming callback
            timeout: Request timeout in seconds

        Returns:
            RequestHandle for tracking the request
        """
        try:
            # Use default model if not specified
            if model_name is None:
                model_name = self.ollama_client.current_model

            # Validate that we have a model name
            if not model_name:
                raise ValueError("No model name specified and no default model available")

            # Use default timeout if not specified
            if timeout is None:
                timeout = self._config.default_timeout

            # Check for request deduplication
            if self._config.enable_request_deduplication:
                request_key = self._generate_request_key(screenshot_id, prompt, model_name)

                async with self._dedup_lock:
                    if request_key in self._pending_requests:
                        # Return existing request handle
                        existing_handle = self._pending_requests[request_key]
                        logger.debug(f"Deduplicating request for screenshot {screenshot_id}")
                        return existing_handle

            # Create new request
            request_id = str(uuid.uuid4())
            request = OllamaRequest(
                id=request_id,
                screenshot_id=screenshot_id,
                prompt=prompt,
                image_path=image_path,
                model_name=model_name,
                priority=priority,
                stream_callback=stream_callback,
                timeout=timeout,
                max_retries=self._config.max_retries
            )

            # Create future and handle
            future = asyncio.Future()
            handle = RequestHandle(
                request_id=request_id,
                future=future,
                request=request,
                status=RequestStatus.QUEUED
            )

            # Check queue capacity
            queue = self._request_queues[priority]
            if queue.qsize() >= self._config.queue_max_size:
                # Queue is full, emit backpressure event
                if self.event_bus:
                    await self.event_bus.emit("request.queue_full", {
                        'priority': priority.name,
                        'queue_size': queue.qsize(),
                        'timestamp': datetime.now().isoformat()
                    })

                # Reject request
                future.set_exception(asyncio.QueueFull("Request queue is full"))
                return handle

            # Add to tracking
            async with self._request_lock:
                self._active_requests[request_id] = handle

                if self._config.enable_request_deduplication:
                    request_key = self._generate_request_key(screenshot_id, prompt, model_name)
                    async with self._dedup_lock:
                        self._pending_requests[request_key] = handle

            # Enqueue request
            await queue.put(handle)
            self._stats['total_requests'] += 1

            # Emit queued event
            if self.event_bus:
                await self.event_bus.emit("request.queued", {
                    'request_id': request_id,
                    'priority': priority.name,
                    'screenshot_id': screenshot_id,
                    'queue_depth': queue.qsize(),
                    'timestamp': datetime.now().isoformat()
                })

            logger.debug(f"Enqueued request {request_id} with priority {priority.name}")
            return handle

        except Exception as e:
            logger.error(f"Failed to enqueue request: {e}")
            # Create failed handle
            future = asyncio.Future()
            future.set_exception(e)
            return RequestHandle(
                request_id="error",
                future=future,
                request=None,
                status=RequestStatus.FAILED
            )

    async def cancel_request(self, handle: RequestHandle) -> bool:
        """
        Cancel a request if possible.

        Args:
            handle: RequestHandle to cancel

        Returns:
            True if cancellation was successful
        """
        try:
            if handle.cancel():
                handle.status = RequestStatus.CANCELLED
                self._stats['cancelled_requests'] += 1

                # Remove from tracking
                async with self._request_lock:
                    self._active_requests.pop(handle.request_id, None)

                    if (self._config.enable_request_deduplication and
                        handle.request and handle.request.screenshot_id):
                        request_key = self._generate_request_key(
                            handle.request.screenshot_id,
                            handle.request.prompt,
                            handle.request.model_name
                        )
                        async with self._dedup_lock:
                            self._pending_requests.pop(request_key, None)

                # Emit cancellation event
                if self.event_bus:
                    await self.event_bus.emit("request.cancelled", {
                        'request_id': handle.request_id,
                        'timestamp': datetime.now().isoformat()
                    })

                logger.debug(f"Cancelled request {handle.request_id}")
                return True

            return False

        except Exception as e:
            logger.error(f"Failed to cancel request: {e}")
            return False

    async def _process_request_queue(self) -> None:
        """Main queue processing loop."""
        try:
            while True:
                # Process queues by priority (highest first)
                handle = None

                for priority in sorted(RequestPriority, key=lambda x: x.value, reverse=True):
                    queue = self._request_queues[priority]

                    try:
                        handle = await asyncio.wait_for(queue.get(), timeout=0.1)
                        break
                    except asyncio.TimeoutError:
                        continue

                if handle is None:
                    continue

                # Process the request
                task = asyncio.create_task(self._process_request(handle))
                self._processing_tasks.add(task)

                # Clean up completed tasks
                completed_tasks = [t for t in self._processing_tasks if t.done()]
                for task in completed_tasks:
                    self._processing_tasks.remove(task)
                    try:
                        await task  # Retrieve any exceptions
                    except Exception as e:
                        logger.error(f"Error in processing task: {e}")

        except asyncio.CancelledError:
            logger.info("Request queue processor cancelled")
        except Exception as e:
            logger.error(f"Error in request queue processor: {e}")

    async def _process_request(self, handle: RequestHandle) -> None:
        """Process a single request with retry logic."""
        request = handle.request
        retry_count = 0
        last_error = None

        # Handle case where request is None (error case)
        if request is None:
            error_msg = "Cannot process request: request object is None"
            if not handle.future.done():
                handle.future.set_exception(Exception(error_msg))
            handle.status = RequestStatus.FAILED
            self._stats['failed_requests'] += 1
            logger.error(error_msg)
            return

        try:
            # Acquire processing semaphore
            async with self._processing_semaphore:
                # Apply rate limiting
                await self._apply_rate_limit()

                # Update status
                handle.status = RequestStatus.PROCESSING

                # Emit processing started event
                if self.event_bus:
                    await self.event_bus.emit("request.started", {
                        'request_id': request.id,
                        'screenshot_id': request.screenshot_id,
                        'timestamp': datetime.now().isoformat()
                    })

                while retry_count <= request.max_retries:
                    try:
                        start_time = time.time()

                        # Execute request with timeout
                        response = await asyncio.wait_for(
                            self._execute_ollama_request(request),
                            timeout=request.timeout
                        )

                        processing_time = time.time() - start_time
                        response['processing_time'] = processing_time

                        # Complete the request
                        handle.future.set_result(response)
                        handle.status = RequestStatus.COMPLETED

                        # Update statistics
                        self._stats['completed_requests'] += 1
                        self._stats['total_processing_time'] += processing_time

                        # Emit completion event
                        if self.event_bus:
                            await self.event_bus.emit("request.completed", {
                                'request_id': request.id,
                                'screenshot_id': request.screenshot_id,
                                'processing_time': processing_time,
                                'retry_count': retry_count,
                                'timestamp': datetime.now().isoformat()
                            })

                        logger.debug(f"Completed request {request.id} in {processing_time:.2f}s")
                        break

                    except asyncio.TimeoutError:
                        last_error = f"Request timeout after {request.timeout}s"
                        logger.warning(f"Request {request.id} timed out (attempt {retry_count + 1})")

                        if retry_count >= request.max_retries:
                            handle.status = RequestStatus.TIMEOUT
                            self._stats['timeout_requests'] += 1
                            break

                    except Exception as e:
                        last_error = str(e)
                        logger.warning(f"Request {request.id} failed (attempt {retry_count + 1}): {e}")

                        if retry_count >= request.max_retries:
                            handle.status = RequestStatus.FAILED
                            self._stats['failed_requests'] += 1
                            break

                    # Wait before retry
                    retry_count += 1
                    if retry_count <= request.max_retries:
                        delay = self._config.retry_delay * (self._config.retry_backoff_multiplier ** (retry_count - 1))
                        await asyncio.sleep(delay)

                # If we exhausted retries, set error
                if not handle.future.done():
                    error_msg = f"Request failed after {retry_count} attempts: {last_error}"
                    handle.future.set_exception(Exception(error_msg))

                    # Emit failure event
                    if self.event_bus:
                        await self.event_bus.emit("request.failed", {
                            'request_id': request.id,
                            'screenshot_id': request.screenshot_id,
                            'error': error_msg,
                            'retry_count': retry_count,
                            'timestamp': datetime.now().isoformat()
                        })

        except Exception as e:
            if not handle.future.done():
                handle.future.set_exception(e)
            handle.status = RequestStatus.FAILED
            self._stats['failed_requests'] += 1
            logger.error(f"Unexpected error processing request {request.id}: {e}")

        finally:
            # Clean up tracking
            await self._cleanup_request(handle)

    async def _execute_ollama_request(self, request: OllamaRequest) -> Dict[str, Any]:
        """Execute the actual Ollama request."""
        try:
            response = await self.ollama_client.send_chat_message(
                screenshot_id=request.screenshot_id,
                prompt=request.prompt,
                image_path=request.image_path,
                stream_callback=request.stream_callback
            )

            return response

        except Exception as e:
            logger.error(f"Ollama request execution failed: {e}")
            raise

    async def _apply_rate_limit(self) -> None:
        """Apply rate limiting between requests."""
        try:
            if self._config.request_rate_limit <= 0:
                return

            async with self._rate_limit_lock:
                now = time.time()
                time_since_last = now - self._last_request_time

                if time_since_last < self._config.request_rate_limit:
                    delay = self._config.request_rate_limit - time_since_last
                    await asyncio.sleep(delay)

                self._last_request_time = time.time()

        except Exception as e:
            logger.error(f"Failed to apply rate limit: {e}")

    async def _cleanup_request(self, handle: RequestHandle) -> None:
        """Clean up request tracking."""
        try:
            async with self._request_lock:
                # Move from active to completed
                self._active_requests.pop(handle.request_id, None)
                self._completed_requests[handle.request_id] = handle

                # Clean up deduplication tracking
                if (self._config.enable_request_deduplication and
                    handle.request and handle.request.screenshot_id):
                    request_key = self._generate_request_key(
                        handle.request.screenshot_id,
                        handle.request.prompt,
                        handle.request.model_name
                    )
                    async with self._dedup_lock:
                        self._pending_requests.pop(request_key, None)

                # Limit completed requests history
                if len(self._completed_requests) > 100:
                    # Remove oldest completed requests
                    oldest_ids = list(self._completed_requests.keys())[:50]
                    for old_id in oldest_ids:
                        self._completed_requests.pop(old_id, None)

        except Exception as e:
            logger.error(f"Failed to cleanup request: {e}")

    async def get_queue_status(self) -> QueueStatus:
        """Get current queue status."""
        try:
            # Count queued requests by priority
            queue_depths = {}
            total_queued = 0

            for priority in RequestPriority:
                queue_size = self._request_queues[priority].qsize()
                queue_depths[priority] = queue_size
                total_queued += queue_size

            # Count processing requests
            processing_count = len([h for h in self._active_requests.values()
                                  if h.status == RequestStatus.PROCESSING])

            # Calculate average processing time
            completed = self._stats['completed_requests']
            avg_time = (self._stats['total_processing_time'] / completed) if completed > 0 else 0.0

            return QueueStatus(
                total_queued=total_queued,
                processing_count=processing_count,
                completed_count=self._stats['completed_requests'],
                failed_count=self._stats['failed_requests'],
                average_processing_time=avg_time,
                queue_depth_by_priority=queue_depths
            )

        except Exception as e:
            logger.error(f"Failed to get queue status: {e}")
            return QueueStatus(
                total_queued=0,
                processing_count=0,
                completed_count=0,
                failed_count=0,
                average_processing_time=0.0,
                queue_depth_by_priority={}
            )

    async def configure_limits(self, max_concurrent: Optional[int] = None,
                             timeout: Optional[float] = None) -> None:
        """
        Configure request limits dynamically.

        Args:
            max_concurrent: Maximum concurrent requests
            timeout: Default request timeout
        """
        try:
            if max_concurrent is not None:
                self._config.max_concurrent = max_concurrent
                self._processing_semaphore = asyncio.Semaphore(max_concurrent)
                logger.info(f"Updated max concurrent requests to {max_concurrent}")

            if timeout is not None:
                self._config.default_timeout = timeout
                logger.info(f"Updated default timeout to {timeout}s")

        except Exception as e:
            logger.error(f"Failed to configure limits: {e}")

    def get_request_statistics(self) -> Dict[str, Any]:
        """Get request processing statistics."""
        completed = self._stats['completed_requests']
        total = self._stats['total_requests']

        return {
            'total_requests': total,
            'completed_requests': completed,
            'failed_requests': self._stats['failed_requests'],
            'cancelled_requests': self._stats['cancelled_requests'],
            'timeout_requests': self._stats['timeout_requests'],
            'success_rate': round((completed / total * 100) if total > 0 else 0, 1),
            'average_processing_time': round(
                (self._stats['total_processing_time'] / completed) if completed > 0 else 0, 2
            ),
            'active_requests': len(self._active_requests),
            'configuration': {
                'max_concurrent': self._config.max_concurrent,
                'queue_max_size': self._config.queue_max_size,
                'default_timeout': self._config.default_timeout,
                'max_retries': self._config.max_retries
            }
        }

    async def _handle_settings_changed(self, event_data) -> None:
        """Handle settings change events."""
        try:
            data = event_data.get('data', {})
            key = data.get('key', '')

            if key.startswith('request_management.'):
                await self._load_settings()
                logger.info("Reloaded request management settings")

        except Exception as e:
            logger.error(f"Failed to handle settings change: {e}")

    async def _handle_cancel_all_requests(self, event_data) -> None:
        """Handle request to cancel all pending requests."""
        try:
            cancelled_count = 0

            async with self._request_lock:
                for handle in list(self._active_requests.values()):
                    if handle.status in [RequestStatus.QUEUED, RequestStatus.PROCESSING]:
                        if handle.cancel():
                            cancelled_count += 1

            logger.info(f"Cancelled {cancelled_count} requests")

            if self.event_bus:
                await self.event_bus.emit("request.bulk_cancelled", {
                    'cancelled_count': cancelled_count,
                    'timestamp': datetime.now().isoformat()
                })

        except Exception as e:
            logger.error(f"Failed to cancel all requests: {e}")

    async def shutdown(self) -> None:
        """Shutdown the request manager."""
        try:
            logger.info("Shutting down RequestManager")

            # Cancel queue processor
            if self._queue_processor_task and not self._queue_processor_task.done():
                self._queue_processor_task.cancel()
                try:
                    await self._queue_processor_task
                except asyncio.CancelledError:
                    pass

            # Cancel all processing tasks
            for task in list(self._processing_tasks):
                if not task.done():
                    task.cancel()

            # Wait for processing tasks to complete
            if self._processing_tasks:
                await asyncio.gather(*self._processing_tasks, return_exceptions=True)

            # Cancel all active requests
            async with self._request_lock:
                for handle in list(self._active_requests.values()):
                    handle.cancel()

            logger.info("RequestManager shutdown complete")

        except Exception as e:
            logger.error(f"Error during RequestManager shutdown: {e}")
