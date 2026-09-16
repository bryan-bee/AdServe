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
