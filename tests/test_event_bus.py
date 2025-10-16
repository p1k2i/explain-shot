"""Unit tests for EventBus.

These tests were rewritten from the older ad-hoc scripts in /tests and
rewritten to use pytest + pytest-asyncio. They focus on the core,
non-GUI logic (subscribe/emit/unsubscribe/metrics/weakrefs).

Note: Install pytest-asyncio to run async tests (pip install pytest-asyncio).
"""

import asyncio
import gc
import pytest

from src.controllers.event_bus import EventBus


@pytest.mark.asyncio
async def test_emit_and_wait_calls_both_async_and_sync_handlers():
    bus = EventBus(enable_metrics=True)

    called = []

    async def async_handler(event):
        called.append(("async", event.data))
        return "async_result"

    def sync_handler(event):
        called.append(("sync", event.data))
        return "sync_result"

    sid1 = await bus.subscribe("tests.event", async_handler)
    sid2 = await bus.subscribe("tests.event", sync_handler)

    results = await bus.emit_and_wait("tests.event", data={"foo": "bar"}, timeout=2.0)

    # Both handlers should have run and returned values
    assert "async_result" in results
    assert "sync_result" in results

    metrics = await bus.get_metrics()
    assert metrics["handlers_called"] >= 2

    # Cleanup
    await bus.unsubscribe(sid1)
    await bus.unsubscribe(sid2)
    await bus.shutdown()


@pytest.mark.asyncio
async def test_once_subscription_removed_after_called():
    bus = EventBus()

    counter = {"count": 0}

    async def handler(event):
        counter["count"] += 1

    # Subscribe once
    _sid = await bus.subscribe("tests.once", handler, once=True)

    # First emit should call handler
    await bus.emit_and_wait("tests.once", data=1)

    # Second emit should not call handler again (subscription removed)
    # use normal emit which queues the event
    await bus.emit("tests.once", data=2)
    await asyncio.sleep(0.1)

    assert counter["count"] == 1

    await bus.shutdown()


@pytest.mark.asyncio
async def test_clear_dead_subscriptions_removes_weakrefs():
    bus = EventBus()

    class CallableObj:
        def __init__(self):
            self.called = False

        def __call__(self, event):
            self.called = True

    obj = CallableObj()

    # Subscribe with weak reference (object is callable)
    sid = await bus.subscribe("tests.weak", obj, weak_ref=True)
    assert sid is not None

    # Remove strong reference to object and force GC
    del obj
    gc.collect()

    removed = await bus.clear_dead_subscriptions()

    # At least one dead subscription should be removed
    assert removed >= 1

    await bus.shutdown()


@pytest.mark.asyncio
async def test_emit_ignored_during_shutdown():
    bus = EventBus(enable_metrics=True)

    # Simulate shutdown in progress
    bus._shutdown_requested = True

    # Emitting during shutdown should be ignored
    await bus.emit("tests.shutdown", data=None)

    metrics = await bus.get_metrics()
    assert metrics["events_emitted"] == 0

    await bus.shutdown()
