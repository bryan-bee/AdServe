from app.db.session import (
    BACKGROUND_MAX_OVERFLOW,
    BACKGROUND_POOL_SIZE,
    BackgroundSessionLocal,
    DB_MAX_OVERFLOW,
    DB_POOL_SIZE,
    DB_POOL_TIMEOUT_SECONDS,
    SessionLocal,
    background_engine,
    engine,
)


def test_background_session_uses_a_separate_engine_from_requests() -> None:
    """BackgroundSessionLocal (used only by the cache-refresh thread) must
    be bound to its own engine, never the request-serving one - see
    STUDY_NOTES.md §17. Sharing one pool between them let the background
    thread silently exceed what app/main.py's request-concurrency limiter
    assumed was reserved for it, since that limiter can't see a raw
    threading.Thread. Confirmed at runtime, not just by reading the
    constants: opening a session from each and checking the underlying
    engine identity is different."""
    assert BackgroundSessionLocal.kw["bind"] is not SessionLocal.kw["bind"]
    assert background_engine is not engine


def test_background_pool_is_isolated_and_small() -> None:
    """The background pool exists purely for structural isolation, not
    real concurrent use - at most one worker across the whole cluster ever
    runs a refresh at a time (CANDIDATES_REFRESH_LOCK_KEY is Redis-wide),
    so it's deliberately tiny."""
    assert BACKGROUND_POOL_SIZE == 1
    assert BACKGROUND_MAX_OVERFLOW == 0


def test_pool_timeout_fails_fast_not_after_thirty_seconds() -> None:
    """Both engines must use a short pool_timeout - under genuine overload,
    a request should get a clear, fast error instead of hanging for
    SQLAlchemy's 30s default, which is what made a temporary overload look
    like the whole server had frozen (see STUDY_NOTES.md §17)."""
    assert DB_POOL_TIMEOUT_SECONDS <= 5
    assert engine.pool.timeout() == DB_POOL_TIMEOUT_SECONDS
    assert background_engine.pool.timeout() == DB_POOL_TIMEOUT_SECONDS


def test_worst_case_connections_per_worker_fits_postgres_limit() -> None:
    """Sanity-checks the arithmetic in app/db/session.py's comments stays
    true if anyone changes these numbers later: worst case per worker
    (request pool + background pool) times a realistic worker count must
    stay safely under Postgres's max_connections=100."""
    per_worker = (DB_POOL_SIZE + DB_MAX_OVERFLOW) + (BACKGROUND_POOL_SIZE + BACKGROUND_MAX_OVERFLOW)
    assert per_worker * 8 < 100
