from contextlib import asynccontextmanager
import os

import anyio.to_thread
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, generate_latest, multiprocess
from prometheus_fastapi_instrumentator import Instrumentator

from app.api.routes.health import router as health_router
from app.core.config import settings
from app.db.session import DB_MAX_OVERFLOW, DB_POOL_SIZE
from app.api.routes.advertisers import router as advertisers_router
from app.api.routes.campaigns import router as campaigns_router
from app.api.routes.auction import router as auction_router
from app.api.routes.impressions import router as impressions_router
from app.api.routes.clicks import router as clicks_router
from app.api.routes.analytics import router as analytics_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs once per worker process at startup (each `uvicorn --workers N`
    worker is a separate process with its own event loop, so this fires N
    times independently - once per worker, not once per fleet).

    FastAPI runs every synchronous path function and dependency (including
    our `def run_auction`) via Starlette's run_in_threadpool, which by
    default shares ONE global capacity limiter across the whole process,
    hard-coded in anyio to allow 40 concurrent threads. That number has
    nothing to do with this app's actual capacity to serve them: our DB
    pool allows only DB_POOL_SIZE + DB_MAX_OVERFLOW connections per worker.
    Left at anyio's default, up to 40 requests per worker can be mid-flight
    at once, but only that many connections can ever be checked out - the
    rest sit blocked holding a live OS thread while queuing for a pool
    slot that won't free up any faster for the wait.

    Resizing the limiter to match the pool exactly means at most
    DB_POOL_SIZE + DB_MAX_OVERFLOW requests ever run at once per worker;
    anything beyond that queues cheaply as a suspended coroutine in the
    event loop - no OS thread, no half-finished DB session - until a slot
    opens up.

    This match only holds because the ONE other consumer of this same pool
    - the background cache-refresh thread in app/services/auction.py - was
    moved to its own separate, dedicated pool (BackgroundSessionLocal).
    That thread runs on a raw threading.Thread, not through anyio, so it
    was invisible to this limiter; sizing the limiter to exactly match the
    pool while that thread could still silently draw from the SAME pool
    caused a real, reproduced `sqlalchemy.exc.TimeoutError: QueuePool
    limit ... reached` under load. See STUDY_NOTES.md §17 for the full
    load-test evidence, including that failure and its fix."""
    anyio.to_thread.current_default_thread_limiter().total_tokens = DB_POOL_SIZE + DB_MAX_OVERFLOW
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.include_router(health_router)
app.include_router(advertisers_router, prefix="/advertisers", tags=["advertisers"])
app.include_router(campaigns_router, prefix="/campaigns", tags=["campaigns"])
app.include_router(auction_router, prefix="/auction", tags=["auction"])
app.include_router(impressions_router, prefix="/impressions", tags=["impressions"])
app.include_router(clicks_router, prefix="/clicks", tags=["clicks"])
app.include_router(analytics_router, prefix="/analytics", tags=["analytics"])

# The React dashboard (frontend/) is served by Vite on its own port during
# development, which makes every request to this API cross-origin - the
# browser blocks the response unless the server explicitly opts in. Scoped
# to the Vite dev origins only, with credentials off: a wildcard "*" here
# would let any website on the internet read this API using a visitor's
# browser, which is exactly the thing CORS exists to prevent.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-API-Key", "Idempotency-Key"],
)

# .instrument(app) records every route's request count, latency histogram,
# and status code via ASGI middleware - this part is identical whether
# there's one worker or many, since every worker independently records its
# own requests either way.
instrumentator = Instrumentator().instrument(app)

# Exposing those metrics is NOT identical across worker counts, and this
# is a real bug that was caught by actually scraping /metrics under
# `uvicorn --workers 4` rather than assuming Instrumentator().expose(app)
# would just work: each worker is a SEPARATE OS process with its OWN
# in-memory Counter/Histogram objects. `uvicorn --workers N` load-balances
# incoming connections across those processes, so a plain
# `Instrumentator().expose(app)` answers GET /metrics from whichever ONE
# worker happens to receive that specific request - repeated scrapes
# return DIFFERENT, inconsistent numbers depending on which worker
# answered, not the true total across the fleet. Confirmed directly:
# curling /metrics six times in a row cycled between three different
# values (5, 6, 33) for the exact same counter - see STUDY_NOTES.md §23.
#
# The fix is prometheus_client's own multiprocess mode: when
# PROMETHEUS_MULTIPROC_DIR is set (before this module - and therefore
# every metric object in app/core/metrics.py - is first imported in each
# worker), every Counter/Histogram automatically writes its values to a
# per-PID file in that directory instead of pure in-memory state. A
# request for /metrics then needs to build a FRESH CollectorRegistry and
# MultiProcessCollector on every single call (not once at startup) - that
# collector's whole job is reading and merging every worker's file at
# scrape time, so it must re-read the directory fresh each time, not
# cache a stale in-memory view from whenever it happened to be built.
#
# PROMETHEUS_MULTIPROC_DIR must also be emptied once before workers start
# (not from inside this per-worker module) - see the startup command in
# STUDY_NOTES.md §23 - otherwise files left behind by a PREVIOUS run's
# now-dead worker PIDs get merged in forever alongside the current run.
if "PROMETHEUS_MULTIPROC_DIR" in os.environ:
    @app.get("/metrics")
    def metrics():
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)
else:
    # Single-process case (tests via TestClient, or a plain `uvicorn`
    # run with no --workers) - no cross-process merging needed, so
    # Instrumentator's own default in-memory exposition is correct as-is.
    instrumentator.expose(app)
