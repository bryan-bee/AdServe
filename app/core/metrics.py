"""Custom business metrics (Step 9), on top of prometheus-fastapi-
instrumentator's automatic HTTP metrics (request count/latency/in-progress
by route+method+status, wired up in app/main.py).

Counter objects are created ONCE at import time, same pattern as the
Producer in app/services/events.py and engine in app/db/session.py - a
Counter IS the running total; there's no per-request object to construct.
Every uvicorn worker gets its own copy of these (separate processes,
separate memory) - Prometheus scrapes each worker's own /metrics endpoint
independently and sums across them at query time, not something this
module has to handle itself.
"""
from prometheus_client import Counter

auction_wins_total = Counter(
    "adserve_auction_wins_total",
    "Auction requests that resulted in a campaign winning (an ad was shown).",
)
auction_no_fill_total = Counter(
    "adserve_auction_no_fill_total",
    "Auction requests where no campaign was eligible (204 No Content - a 'no fill').",
)
suspicious_clicks_total = Counter(
    "adserve_suspicious_clicks_total",
    "Clicks flagged by the click-fraud timing heuristic as implausibly fast "
    "after their impression (recorded, not rejected - see STUDY_NOTES.md §27).",
)
idempotent_replays_total = Counter(
    "adserve_idempotent_replays_total",
    "Requests answered from a stored Idempotency-Key response instead of "
    "being processed again - i.e. client retries that were successfully "
    "prevented from double-recording an event.",
    ["endpoint"],
)
