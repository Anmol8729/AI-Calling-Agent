"""Pub/sub for real-time dashboard notifications.

Why this is not just in-memory any more
---------------------------------------
Dashboards hold a WebSocket to ONE process. Events are published by whichever
process handled the request (or the background worker). With purely in-process
fan-out, running two replicas silently breaks correctness rather than merely
scaling badly:

    replica A  <- dashboard WebSocket
    replica B  <- the agent's "call started" request lands here
    => publish() runs on B, the subscriber lives on A, the bell never fires

So the bell worked only while exactly one process existed. Adding a replica made
notifications intermittent in a way that looks like a flaky UI, not a topology bug.

Now `publish()` also forwards to Redis, and each process subscribes to that
channel and re-delivers to its own local queues. Any process can publish and every
connected dashboard hears it.

Redis is optional. Without it we fall back to in-process fan-out and log a warning,
because a notification feed is not worth refusing to boot over — but the operator
needs to know that scaling out will drop events.

Events are still NOT durable: they reach clients connected at that moment. The bell
also seeds recent history over REST, so a brief disconnect is not a problem.
"""

import asyncio
import json
import logging
from collections import defaultdict
from typing import Optional

from backend.config.settings import settings

logger = logging.getLogger("events")

# clinic_id (str) -> set[asyncio.Queue] held by THIS process.
_subscribers = defaultdict(set)

_CHANNEL = "clarivo:events"

# Set up by start_event_bridge(); None when running in-process only.
_redis = None
_bridge_task: Optional[asyncio.Task] = None
# Marks events this process published, so it can ignore its own echo from Redis
# instead of delivering every local notification twice.
_INSTANCE_ID = None


def subscribe(clinic_id) -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    _subscribers[str(clinic_id)].add(queue)
    return queue


def unsubscribe(clinic_id, queue) -> None:
    subs = _subscribers.get(str(clinic_id))
    if subs:
        subs.discard(queue)
        if not subs:
            _subscribers.pop(str(clinic_id), None)


def _deliver_local(clinic_id, event: dict) -> None:
    """Fan out to queues in THIS process. Drops for a full (stuck tab) queue."""
    for queue in list(_subscribers.get(str(clinic_id), ())):
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            pass


def publish(clinic_id, event: dict) -> None:
    """Deliver an event to every dashboard connected for this clinic.

    Non-blocking and safe to call from sync or async code. No-ops when clinic_id
    is None.
    """
    if clinic_id is None:
        return

    _deliver_local(clinic_id, event)

    # Then hand it to the other replicas, if a bus is configured.
    if _redis is None:
        return
    try:
        payload = json.dumps({
            "clinic_id": str(clinic_id),
            "event": event,
            "origin": _INSTANCE_ID,
        })
    except (TypeError, ValueError) as e:
        logger.error(f"Event is not JSON-serialisable, not broadcasting: {e}")
        return

    async def _send():
        try:
            await _redis.publish(_CHANNEL, payload)
        except Exception as e:  # noqa: BLE001 — a notification must never break a request
            logger.error(f"Failed to broadcast event to Redis: {e}")

    try:
        # publish() is called from sync paths too, so schedule rather than await.
        asyncio.get_running_loop().create_task(_send())
    except RuntimeError:
        # No running loop (a sync context outside the server) — local delivery
        # already happened, which is the best we can do here.
        pass


async def _bridge_loop():
    """Re-deliver events published by OTHER processes into local queues."""
    pubsub = _redis.pubsub()
    await pubsub.subscribe(_CHANNEL)
    logger.info(f"Event bridge subscribed to {_CHANNEL} (multi-replica delivery active).")
    try:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            try:
                data = json.loads(message["data"])
            except (TypeError, ValueError):
                continue
            # Skip our own echo; publish() already delivered it locally.
            if data.get("origin") == _INSTANCE_ID:
                continue
            _deliver_local(data.get("clinic_id"), data.get("event") or {})
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.error(f"Event bridge stopped: {e}")
    finally:
        try:
            await pubsub.unsubscribe(_CHANNEL)
            await pubsub.close()
        except Exception:  # noqa: BLE001
            pass


async def start_event_bridge() -> bool:
    """Connect the cross-process bus. Returns True when it is active.

    Called from the app lifespan. Falls back to in-process delivery on any failure.
    """
    global _redis, _bridge_task, _INSTANCE_ID

    uri = (settings.REDIS_URL or "").strip()
    if not uri:
        logger.warning(
            "REDIS_URL is not set: dashboard notifications are delivered in-process "
            "only. With more than one replica, events published by one process will "
            "not reach dashboards connected to another."
        )
        return False

    try:
        import uuid

        import redis.asyncio as aioredis

        client = aioredis.from_url(uri, decode_responses=True)
        await client.ping()
        _redis = client
        _INSTANCE_ID = uuid.uuid4().hex
        _bridge_task = asyncio.create_task(_bridge_loop())
        return True
    except Exception as e:  # noqa: BLE001
        logger.error(
            f"Could not start the Redis event bridge ({e}). Notifications will be "
            "delivered in-process only, which breaks with multiple replicas."
        )
        _redis = None
        return False


async def stop_event_bridge() -> None:
    global _redis, _bridge_task
    if _bridge_task is not None:
        _bridge_task.cancel()
        try:
            await _bridge_task
        except asyncio.CancelledError:
            pass
        _bridge_task = None
    if _redis is not None:
        try:
            await _redis.aclose()
        except Exception:  # noqa: BLE001
            pass
        _redis = None


def is_distributed() -> bool:
    """True when events cross process boundaries. Surfaced in diagnostics."""
    return _redis is not None
