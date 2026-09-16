import anyio.to_thread
from fastapi.testclient import TestClient

from app.db.session import DB_MAX_OVERFLOW, DB_POOL_SIZE
from app.main import app


async def _get_limiter_tokens() -> float:
    return anyio.to_thread.current_default_thread_limiter().total_tokens


def test_startup_sizes_threadpool_to_connection_pool() -> None:
    """The app's lifespan handler must resize anyio's default thread
    limiter to match DB_POOL_SIZE + DB_MAX_OVERFLOW - see app/main.py and
    STUDY_NOTES.md §17. Left at anyio's hard-coded default of 40, far more
    concurrent requests are allowed to run per worker than the DB pool can
    ever serve, which is what caused real request failures under heavy
    concurrent load (500 errors, connection resets) before this fix.

    Uses TestClient's portal to run the assertion on the SAME event loop
    the lifespan handler started on - anyio's thread limiter is tied to
    the running event loop, so checking it from outside that loop would
    silently read a different, never-resized instance."""
    with TestClient(app) as client:
        tokens = client.portal.call(_get_limiter_tokens)

    assert tokens == DB_POOL_SIZE + DB_MAX_OVERFLOW
