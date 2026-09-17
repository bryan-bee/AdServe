"""Publishing side of AdServe's event pipeline (Step 8).

Endpoints that used to write directly to Postgres (clicks, conversions)
instead publish a small JSON event to one shared Kafka topic
(`adserve.events`) and return immediately. A separate, standalone process
(`scripts/consume_events.py`) subscribes to that topic and does the actual
database write. See STUDY_NOTES.md §20 for the full concept explanation and
the reasoning behind every choice made here.
"""
import json

from confluent_kafka import Producer

from app.core.config import settings

# One Producer per process, created at import time and reused for every
# request - the same pattern as `engine` in app/db/session.py. Each one
# owns a real connection and its own background I/O thread; creating one
# per request would be wasteful and would also drop most of the batching
# that makes this fast in the first place.
_producer = Producer({"bootstrap.servers": settings.kafka_bootstrap_servers})


def _delivery_report(err, msg) -> None:
    """Called asynchronously, later, once a specific message's outcome is
    known - never called synchronously from publish_event() itself. Only
    runs when something calls producer.poll()/flush() and this message's
    result is ready. By the time this fires, the HTTP request that
    produced the message has almost always already returned its response
    - logging is the right response here, not raising."""
    if err is not None:
        print(f"Kafka delivery failed: {err} (message: {msg.value()!r})")


def publish_event(event: dict, key: str) -> None:
    """Queue an event for delivery to the shared adserve.events topic.

    Returns as soon as the message is handed to librdkafka's internal
    queue - NOT once it's confirmed delivered to the broker. Delivery
    success/failure is only ever observed later, via _delivery_report.

    Args:
        event: A JSON-serializable dict. Must include an "event_type" key
            so a consumer reading this single shared topic (which carries
            more than one kind of event) can tell what it's looking at.
        key: Kafka routes messages with the same key to the same
            partition, and a partition preserves the order messages were
            produced in. Callers pick this so that events which must be
            processed in order relative to each other share a key - see
            the click/conversion endpoints for why they both key on the
            click's id.
    """
    _producer.produce(
        settings.kafka_events_topic,
        key=key,
        value=json.dumps(event),
        callback=_delivery_report,
    )
    # Non-blocking: serves any delivery callbacks that already completed,
    # without waiting for this message's own outcome. Called after every
    # produce() so failures get logged in a timely way without slowing
    # down the request that triggered them.
    _producer.poll(0)
