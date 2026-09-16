from contextlib import asynccontextmanager

import anyio.to_thread
from fastapi import FastAPI

from app.api.routes.health import router as health_router
from app.core.config import settings
from app.db.session import DB_MAX_OVERFLOW, DB_POOL_SIZE
from app.api.routes.advertisers import router as advertisers_router
from app.api.routes.campaigns import router as campaigns_router
from app.api.routes.auction import router as auction_router
from app.api.routes.impressions import router as impressions_router
from app.api.routes.clicks import router as clicks_router


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
