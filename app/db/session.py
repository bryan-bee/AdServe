from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings


# pool_size + max_overflow is the max connections ONE process can hold open.
# Postgres here is capped at max_connections=100 (see STUDY_NOTES.md §15/16),
# and each `uvicorn --workers N` process creates its own independent engine -
# these numbers are multiplied by N, not shared.
#
# Exported (not just used locally) because app/main.py uses these same two
# numbers to size anyio's threadpool limiter to match - see STUDY_NOTES.md
# §17 for why that pairing matters: without it, far more concurrent requests
# are allowed to run per worker than this pool can ever serve.
#
# pool_timeout is set short (3s, vs SQLAlchemy's 30s default) DELIBERATELY:
# if every connection really is busy under genuine overload, a request
# should fail fast with a clear error rather than hang for 30 seconds first
# - a pile of 30-second hangs is what turned a temporary overload into
# something that looked, from outside, like the whole server had frozen.
DB_POOL_SIZE = 6
DB_MAX_OVERFLOW = 4
DB_POOL_TIMEOUT_SECONDS = 3
engine = create_engine(
    settings.database_url,
    pool_size=DB_POOL_SIZE,
    max_overflow=DB_MAX_OVERFLOW,
    pool_timeout=DB_POOL_TIMEOUT_SECONDS,
)

SessionLocal = sessionmaker(engine)

# A SEPARATE, tiny, dedicated engine/pool used ONLY by the background
# cache-refresh thread in app/services/auction.py - never by request
# handling. That thread runs on a raw threading.Thread, not through
# anyio's threadpool, so it is invisible to the request-concurrency limiter
# in app/main.py that's sized to exactly match `engine`'s pool. Before this
# split existed, the background refresh drew from the SAME pool as
# requests, silently consuming one of the exact number of connections the
# limiter assumed were reserved for it - the one case where demand could
# exceed the limiter's accounting, confirmed via a real
# `sqlalchemy.exc.TimeoutError: QueuePool limit ... reached` under load
# (see STUDY_NOTES.md §17). At most one worker across the whole cluster
# ever runs this refresh at a time (CANDIDATES_REFRESH_LOCK_KEY is
# Redis-wide), so this budget is deliberately tiny - it's headroom for
# structural isolation, not for real concurrent use.
BACKGROUND_POOL_SIZE = 1
BACKGROUND_MAX_OVERFLOW = 0
background_engine = create_engine(
    settings.database_url,
    pool_size=BACKGROUND_POOL_SIZE,
    max_overflow=BACKGROUND_MAX_OVERFLOW,
    pool_timeout=DB_POOL_TIMEOUT_SECONDS,
)
BackgroundSessionLocal = sessionmaker(background_engine)

# Worst-case total connections per worker: DB_POOL_SIZE + DB_MAX_OVERFLOW
# (10, for requests) + BACKGROUND_POOL_SIZE + BACKGROUND_MAX_OVERFLOW (1,
# for the rare background refresh - no overflow needed since the Redis
# lock guarantees at most one refresh runs at all, cluster-wide) = 11.
# Across 8 workers: 8 * 11 = 88, comfortably under Postgres's
# max_connections=100, with more headroom than before (80/100) despite now
# giving the background path its own real isolation.

def get_db():
    """FastAPI dependency (use via `Depends(get_db)`) that opens a session
    per request and always closes it afterward, success or failure.
    Standalone scripts (seed.py etc.) don't use this - they call
    SessionLocal() directly, since there's no per-request lifecycle to
    manage."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()