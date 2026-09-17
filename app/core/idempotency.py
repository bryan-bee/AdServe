"""Client-supplied idempotency keys for the event-recording endpoints
(Step 11).

The gap this closes is specific and worth being precise about, because
this project already has idempotency somewhere else that does NOT cover
it. §20.8's consumer deduplicates by primary key, which protects against
KAFKA redelivering the same message twice - a transport-level retry of an
already-published event.

It does nothing about an HTTP-level retry. `record_click` generates a
fresh `uuid4()` per call, so a client whose connection dropped and who
retries the same logical click produces a genuinely DIFFERENT click id,
publishes a second, distinct event, and the consumer - correctly, by its
own rules - writes both. Two clicks recorded, one real click. On an ad
platform that is double-counted billing and inflated CTR, which is the
same category of problem as §19's lost charges, just in the other
direction.

An idempotency key fixes it at the only layer that can: the client says
"this request and any retry of it are the same operation," and the server
remembers its answer. Same idea as Stripe's API. See STUDY_NOTES.md §26.
"""
import json

from fastapi import HTTPException, Header

from app.db.redis_client import redis_client

# How long a completed response stays replayable. 24h comfortably outlives
# any realistic client retry loop without keeping keys forever.
IDEMPOTENCY_TTL_SECONDS = 86_400
# How long the "I'm working on it" marker lives if the request dies
# mid-flight, before another attempt is allowed to claim the key.
IDEMPOTENCY_IN_PROGRESS_TTL_SECONDS = 60
_IN_PROGRESS = "__in_progress__"


def idempotency_key_header(idempotency_key: str | None = Header(default=None)) -> str | None:
    """FastAPI dependency exposing the optional `Idempotency-Key` header.

    Optional by design: a caller that doesn't care (the traffic simulator,
    Locust, a browser pixel firing once) is unaffected and pays nothing.
    """
    return idempotency_key


def claim_or_replay(scope: str, key: str | None) -> dict | None:
    """Try to claim this idempotency key for processing.

    Returns:
        None if the caller should go ahead and do the work (either no key
        was supplied, or this is the first time we've seen it).
        A dict - the previously-returned response body - if this exact key
        was already completed, in which case the caller should return that
        instead of doing the work a second time.

    Raises:
        HTTPException: 409 if the same key is currently in flight on
            another request. That's a genuine conflict rather than
            something to replay: the first attempt hasn't produced an
            answer yet, so there is nothing correct to return, and doing
            the work anyway would defeat the whole point.
    """
    if key is None:
        return None

    redis_key = f"idempotency:{scope}:{key}"
    # SET NX is the atomic "claim it if nobody else has" primitive - the
    # same pattern app/services/auction.py already uses for the cache
    # refresh lock. Checking-then-setting in two steps would let two
    # concurrent retries both decide they were first.
    claimed = redis_client.set(
        redis_key, _IN_PROGRESS, nx=True, ex=IDEMPOTENCY_IN_PROGRESS_TTL_SECONDS
    )
    if claimed:
        return None

    stored = redis_client.get(redis_key)
    if stored == _IN_PROGRESS:
        raise HTTPException(
            status_code=409,
            detail="A request with this Idempotency-Key is already in progress",
        )
    if stored is None:
        # Expired between the failed claim and this read - vanishingly
        # narrow, and treating it as "go ahead" is the safe reading: at
        # worst the work happens once more, which is what would have
        # happened without a key at all.
        return None
    return json.loads(stored)


def store_response(scope: str, key: str | None, body: dict) -> None:
    """Record the response for this key, so a later retry replays it
    instead of redoing the work. No-op when the caller supplied no key."""
    if key is None:
        return
    redis_client.set(
        f"idempotency:{scope}:{key}", json.dumps(body), ex=IDEMPOTENCY_TTL_SECONDS
    )
