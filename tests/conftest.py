import redis
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

# Import every model so Base.metadata knows about all tables before any
# test commits - otherwise SQLAlchemy can't resolve foreign keys between
# models that a given test doesn't happen to import directly.
from app.models.advertiser import Advertiser  # noqa: F401
from app.models.audience_targeting import AudienceTargeting  # noqa: F401
from app.models.campaign import Campaign  # noqa: F401
from app.models.interest import Interest  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.impression import Impression  # noqa: F401
from app.models.click import Click  # noqa: F401
from app.models.conversion import Conversion  # noqa: F401

test_engine = create_engine(settings.test_database_url)
TestSessionLocal = sessionmaker(bind=test_engine)


@pytest.fixture
def db():
    """A DB session wrapped in a transaction that's always rolled back
    afterward, so tests can freely insert/update/delete against the real
    test database without leaving any permanent changes behind."""
    connection = test_engine.connect()
    transaction = connection.begin()
    session = TestSessionLocal(bind=connection)

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def redis_cache(monkeypatch):
    """Isolates app/services/auction.py's candidate cache to a dedicated
    Redis logical database (TEST_REDIS_URL, index 1 - same server, separate
    keyspace from dev/prod's index 0), instead of the module-level
    `redis_client` it imports by default.

    Without this, a test calling filter_eligible_campaigns/
    get_campaign_candidates reads whatever's cached under
    `auction:campaign_candidates` in the SAME Redis instance dev/prod uses -
    on a cache hit, that candidate list is returned as-is, completely
    ignoring the isolated `db` fixture's test-only data. A dev session
    doing ordinary manual testing is enough to populate that shared cache
    with production-shaped campaigns, silently breaking this test's
    assumption that it only ever sees the seeded test data - a real
    failure this project hit, root-caused in STUDY_NOTES.md §17.

    `monkeypatch.setattr` on the module attribute (not just this fixture's
    own reference) is what actually redirects auction.py's calls, since it
    reads `redis_client` as a module-level name, not a parameter.
    `flushdb()` is safe here specifically because this logical database
    exists for nothing else."""
    test_client = redis.Redis.from_url(settings.test_redis_url, decode_responses=True)
    test_client.flushdb()
    monkeypatch.setattr("app.services.auction.redis_client", test_client)
    yield test_client
    test_client.flushdb()
