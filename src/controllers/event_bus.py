"""
EventBus Module

Provides asynchronous event distribution system for loose coupling between modules.
Implements publisher-subscriber pattern using asyncio for non-blocking event handling.
"""

import asyncio
import logging
import traceback
import weakref
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field
from uuid import uuid4
from collections import defaultdict, deque
import time

logger = logging.getLogger(__name__)


@dataclass
class EventData:
    """Container for event information."""
    event_type: str
    data: Any = None
    timestamp: float = field(default_factory=time.time)
    source: Optional[str] = None
    correlation_id: Optional[str] = None


@dataclass
class EventSubscription:
    """Represents an event subscription."""
    subscription_id: str
    event_type: str
    handler: Callable
    priority: int = 0
    once: bool = False
    weak_ref: bool = True


class EventBusError(Exception):
    """Base exception for EventBus related errors."""
    pass


class EventHandlerError(EventBusError):
    """Exception raised when event handler fails."""
    pass


class EventBus:
    """
    Asynchronous event distribution system.

    Provides loose coupling between application modules through an event-driven
    architecture. Supports priority-based event handling, one-time subscriptions,
    weak references, and event queuing.
    """

    def __init__(self, max_queue_size: int = 1000, enable_metrics: bool = True):
        """
        Initialize EventBus.

        Args:
            max_queue_size: Maximum number of queued events
            enable_metrics: Whether to collect event metrics
        """
        self._subscribers: Dict[str, List[EventSubscription]] = defaultdict(list)
        self._event_queue: deque = deque(maxlen=max_queue_size)
        self._processing_queue: bool = False
        self._shutdown_requested: bool = False
        self._enable_metrics = enable_metrics

        # Metrics tracking
        self._metrics = {
            'events_emitted': 0,
            'events_processed': 0,
            'handlers_called': 0,
            'handler_errors': 0,
            'queue_overflows': 0
        } if enable_metrics else {}

        # Event history for debugging (limited size)
        self._event_history: deque = deque(maxlen=100)

        # Lock for thread safety
        self._lock = asyncio.Lock()

        logger.info("EventBus initialized with max_queue_size=%d", max_queue_size)

    async def subscribe(
        self,
        event_type: str,
        handler: Callable,
        priority: int = 0,
        once: bool = False,
        weak_ref: bool = True
    ) -> str:
        """
        Subscribe to an event type.

        Args:
            event_type: Type of event to subscribe to
            handler: Callable to handle the event
            priority: Handler priority (higher = called first)
            once: If True, unsubscribe after first call
            weak_ref: If True, use weak reference to handler

        Returns:
            Subscription ID for later unsubscription

        Raises:
            EventBusError: If handler is not callable
        """
        if not callable(handler):
            raise EventBusError(f"Handler must be callable, got {type(handler)}")

        subscription_id = str(uuid4())

        # Create weak reference if requested and possible
        handler_ref = None
        if weak_ref:
            try:
                handler_ref = weakref.ref(handler)
                # Test if weak reference works
                if handler_ref() is None:
                    weak_ref = False
                    handler_ref = None
            except TypeError:
                # Some callables don't support weak references
                weak_ref = False
                handler_ref = None

        subscription = EventSubscription(
            subscription_id=subscription_id,
            event_type=event_type,
            handler=handler_ref if weak_ref and handler_ref is not None else handler,
            priority=priority,
            once=once,
            weak_ref=weak_ref
        )

        async with self._lock:
            self._subscribers[event_type].append(subscription)
            # Sort by priority (descending)
            self._subscribers[event_type].sort(key=lambda x: x.priority, reverse=True)

        logger.debug(
            "Subscribed to event '%s' with priority %d (ID: %s)",
            event_type, priority, subscription_id
        )

        return subscription_id

    async def unsubscribe(self, subscription_id: str) -> bool:
        """
        Unsubscribe from events.

        Args:
            subscription_id: ID returned from subscribe()

        Returns:
            True if subscription was found and removed
        """
        async with self._lock:
            for event_type, subscriptions in self._subscribers.items():
                for i, subscription in enumerate(subscriptions):
                    if subscription.subscription_id == subscription_id:
                        del subscriptions[i]
                        logger.debug(
                            "Unsubscribed from event '%s' (ID: %s)",
                            event_type, subscription_id
                        )
                        return True

        logger.warning("Subscription ID not found: %s", subscription_id)
        return False

    async def emit(
        self,
        event_type: str,
        data: Any = None,
        source: Optional[str] = None,
        correlation_id: Optional[str] = None
    ) -> None:
        """
        Emit an event asynchronously.

        Args:
            event_type: Type of event to emit
            data: Event data
            source: Source identifier for debugging
            correlation_id: Correlation ID for event tracking
        """
        if self._shutdown_requested:
            logger.warning("Ignoring event emission during shutdown: %s", event_type)
            return

        event_data = EventData(
            event_type=event_type,
            data=data,
            source=source,
            correlation_id=correlation_id
        )

        # Add to queue
        try:
            self._event_queue.append(event_data)
            if self._enable_metrics:
                self._metrics['events_emitted'] += 1
        except Exception:
            # Queue is full
            if self._enable_metrics:
                self._metrics['queue_overflows'] += 1
            logger.warning("Event queue overflow, dropping event: %s", event_type)
            return

        # Process queue if not already processing
        if not self._processing_queue:
            asyncio.create_task(self._process_event_queue())

        logger.debug("Emitted event: %s", event_type)

    async def emit_and_wait(
        self,
        event_type: str,
        data: Any = None,
        source: Optional[str] = None,
        correlation_id: Optional[str] = None,
        timeout: float = 5.0
    ) -> List[Any]:
        """
        Emit an event and wait for all handlers to complete.

        Args:
            event_type: Type of event to emit
            data: Event data
            source: Source identifier
            correlation_id: Correlation ID
            timeout: Maximum time to wait for handlers

        Returns:
            List of return values from handlers

        Raises:
            asyncio.TimeoutError: If handlers don't complete within timeout
        """
        event_data = EventData(
            event_type=event_type,
            data=data,
            source=source,
            correlation_id=correlation_id
        )

        return await asyncio.wait_for(
            self._process_event_immediate(event_data),
            timeout=timeout
        )

    async def _process_event_queue(self) -> None:
        """Process queued events asynchronously."""
        if self._processing_queue:
            return

        self._processing_queue = True

        try:
            while self._event_queue and not self._shutdown_requested:
                event_data = self._event_queue.popleft()
                await self._process_event_immediate(event_data)

                if self._enable_metrics:
                    self._metrics['events_processed'] += 1

                # Add to history for debugging
                self._event_history.append(event_data)

                # Yield control to allow other coroutines to run
                await asyncio.sleep(0)

        except Exception as e:
            logger.error("Error processing event queue: %s", e)
            logger.debug("Exception details:", exc_info=True)

        finally:
            self._processing_queue = False

    async def _process_event_immediate(self, event_data: EventData) -> List[Any]:
        """
        Process a single event immediately.

        Args:
            event_data: Event to process

        Returns:
            List of return values from handlers
        """
        results = []
        subscriptions_to_remove = []

        async with self._lock:
            subscriptions = self._subscribers.get(event_data.event_type, []).copy()

        for subscription in subscriptions:
            handler = None
            try:
                # Get handler (resolve weak reference if needed)
                handler = subscription.handler
                if subscription.weak_ref:
                    handler = handler()
                    if handler is None:
                        # Weak reference is dead, mark for removal
                        subscriptions_to_remove.append(subscription.subscription_id)
                        continue

                # Call handler
                if asyncio.iscoroutinefunction(handler):
                    result = await handler(event_data)
                else:
                    result = handler(event_data)

                results.append(result)

                if self._enable_metrics:
                    self._metrics['handlers_called'] += 1

                # Mark for removal if one-time subscription
                if subscription.once:
                    subscriptions_to_remove.append(subscription.subscription_id)

            except Exception as e:
                if self._enable_metrics:
                    self._metrics['handler_errors'] += 1

                logger.error(
                    "Error in event handler for '%s': %s",
                    event_data.event_type, e
                )
                logger.debug("Handler error details:", exc_info=True)

                # Emit error event (but don't create infinite loops)
                if event_data.event_type != "error.occurred":
                    await self.emit(
                        "error.occurred",
                        {
                            'error': str(e),
                            'original_event': event_data.event_type,
                            'handler': str(handler) if handler else "Unknown",
                            'traceback': traceback.format_exc()
                        },
                        source="EventBus"
                    )

        # Remove one-time subscriptions and dead weak references
        for subscription_id in subscriptions_to_remove:
            await self.unsubscribe(subscription_id)

        return results

    async def get_metrics(self) -> Dict[str, Any]:
        """
        Get event bus metrics.

        Returns:
            Dictionary of metrics data
        """
        if not self._enable_metrics:
            return {}

        async with self._lock:
            subscription_counts = {
                event_type: len(subscriptions)
                for event_type, subscriptions in self._subscribers.items()
            }

        return {
            **self._metrics.copy(),
            'queue_size': len(self._event_queue),
            'subscription_counts': subscription_counts,
            'total_event_types': len(self._subscribers)
        }

    async def get_event_history(self, limit: int = 50) -> List[EventData]:
        """
        Get recent event history for debugging.

        Args:
            limit: Maximum number of events to return

        Returns:
            List of recent events
        """
        return list(self._event_history)[-limit:]

    async def clear_dead_subscriptions(self) -> int:
        """
        Remove subscriptions with dead weak references.

        Returns:
            Number of subscriptions removed
        """
        removed_count = 0

        async with self._lock:
            for event_type, subscriptions in list(self._subscribers.items()):
                alive_subscriptions = []

                for subscription in subscriptions:
                    if subscription.weak_ref:
                        handler = subscription.handler()
                        if handler is None:
                            removed_count += 1
                            continue

                    alive_subscriptions.append(subscription)

                if alive_subscriptions:
                    self._subscribers[event_type] = alive_subscriptions
                else:
                    del self._subscribers[event_type]

        if removed_count > 0:
            logger.debug("Cleaned up %d dead subscriptions", removed_count)

        return removed_count

    async def shutdown(self, timeout: float = 5.0) -> None:
        """
        Shutdown the event bus gracefully.

        Args:
            timeout: Maximum time to wait for queue processing
        """
        logger.info("Shutting down EventBus...")
        self._shutdown_requested = True

        # Wait for queue to empty or timeout
        start_time = time.time()
        while self._event_queue and (time.time() - start_time) < timeout:
            await asyncio.sleep(0.1)

        # Clear all subscriptions
        async with self._lock:
            self._subscribers.clear()
            self._event_queue.clear()
            self._event_history.clear()

        logger.info("EventBus shutdown complete")

    def __len__(self) -> int:
        """Return number of queued events."""
        return len(self._event_queue)

    def is_shutdown(self) -> bool:
        """Check if shutdown has been requested."""
        return self._shutdown_requested


# Global event bus instance
_global_event_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """
    Get the global EventBus instance.

    Returns:
        Global EventBus instance
    """
    global _global_event_bus
    if _global_event_bus is None:
        _global_event_bus = EventBus()
    return _global_event_bus


def set_event_bus(event_bus: EventBus) -> None:
    """
    Set the global EventBus instance.

    Args:
        event_bus: EventBus instance to use globally
    """
    global _global_event_bus
    _global_event_bus = event_bus
