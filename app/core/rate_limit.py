"""Redis-backed rate limiting (Step 7's deferred item, built in Step 11).

A fixed-window counter: count how many requests a client has made in the
current N-second window, reject with 429 once they exceed the allowance.
See STUDY_NOTES.md §25 for the full design discussion, including why a
fixed window rather than a sliding-window log, and the one real weakness
this approach has (burst at a window boundary).
"""
from fastapi import HTTPException, Request

from app.db.redis_client import redis_client

# Deliberately generous enough that normal simulated traffic and the test
# suite never trip it, tight enough to demonstrate real protection. These
# are per-client-per-endpoint-group, not global.
AUCTION_RATE_LIMIT = 100
AUCTION_WINDOW_SECONDS = 10


def client_identifier(request: Request) -> str:
    """Who is this request from, for rate-limiting purposes?

    The client's IP address - the only identity available on these
    endpoints, since /auction, /impressions/{id}/clicks and
    /clicks/{id}/conversions are all deliberately unauthenticated (see
    STUDY_NOTES.md §24.1: they model traffic from end-user browsers, which
    have no API key to present).

    Known limitation, worth stating rather than hiding: behind a reverse
    proxy or load balancer, `request.client.host` is the PROXY's address,
    not the real client's - every user would then share one bucket. The
    real fix is reading X-Forwarded-For, but only when the proxy is
    trusted, because that header is caller-supplied and trivially spoofed
    otherwise - which would let an attacker mint a fresh rate-limit bucket
    per request just by changing a header. This project has no proxy in
    front of it yet (that's the still-open horizontal-scaling item), so
    the simple version is correct for now and would need revisiting the
    moment Nginx appears.
    """
    return request.client.host if request.client else "unknown"


def enforce_rate_limit(request: Request, bucket: str, limit: int, window_seconds: int) -> None:
    """Count this request against the caller's current window, and reject
    it if they're over the limit.

    The mechanism is two Redis commands:

        INCR key            -> atomically +1, returning the new count
        EXPIRE key N        -> only on the FIRST request of a window

    INCR is what makes this safe under real concurrency: it's a single
    atomic server-side operation, so N simultaneous requests from the same
    client get N distinct counter values rather than all reading the same
    number and writing back the same +1 (the identical lost-update shape
    that §19's Finding 3 fixed for campaign.spent, avoided here for the
    same reason - let the datastore do the arithmetic).

    EXPIRE is applied only when INCR returns 1 (i.e. we just created the
    key). Re-applying it on every request would slide the expiry forward
    continuously, so a client making steady traffic would never see their
    window reset - it would become "N requests ever", not "N per window".

    Raises:
        HTTPException: 429 with a Retry-After header once the caller
            exceeds `limit` within the window.
    """
    key = f"ratelimit:{bucket}:{client_identifier(request)}"
    count = redis_client.incr(key)
    if count == 1:
        redis_client.expire(key, window_seconds)

    if count > limit:
        # TTL tells the caller how long until the window actually resets,
        # rather than making them guess or hammer blindly.
        retry_after = max(redis_client.ttl(key), 1)
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: {limit} requests per {window_seconds}s",
            headers={"Retry-After": str(retry_after)},
        )


def auction_rate_limit(request: Request) -> None:
    """FastAPI dependency form, for the auction endpoint."""
    enforce_rate_limit(request, "auction", AUCTION_RATE_LIMIT, AUCTION_WINDOW_SECONDS)
