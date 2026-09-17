"""Tests for the Step 11 hardening work: API-key authentication,
authorization (ownership), rate limiting, and idempotency keys.

These hit the real app through TestClient, so unlike the service-level
tests they exercise headers, status codes and dependencies exactly as a
real client would. `get_db` is overridden onto the transactional `db`
fixture so nothing these tests write ever leaves the test database, and
the Redis-backed features are pointed at the isolated test Redis for the
same reason (see tests/conftest.py's redis_cache docstring for the real
incident that made this isolation non-optional).
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import uuid

import pytest
import redis
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import generate_api_key, hash_api_key
from app.db.session import get_db
from app.main import app
from app.models.advertiser import Advertiser
from app.models.campaign import Campaign, CampaignStatus


@pytest.fixture
def client(db):
    """A TestClient whose requests use the transactional test-db session,
    so anything an endpoint writes is rolled back with the fixture."""
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def test_redis(monkeypatch):
    """Point the rate limiter and idempotency store at the isolated test
    Redis database, and clear it, so these tests can't be tripped by - or
    trip - real dev traffic's counters."""
    test_client = redis.Redis.from_url(settings.test_redis_url, decode_responses=True)
    test_client.flushdb()
    monkeypatch.setattr("app.core.rate_limit.redis_client", test_client)
    monkeypatch.setattr("app.core.idempotency.redis_client", test_client)
    yield test_client
    test_client.flushdb()


def _campaign_payload():
    now = datetime.now(timezone.utc)
    return {
        "budget": "500.00",
        "start_date": (now - timedelta(days=1)).isoformat(),
        "end_date": (now + timedelta(days=30)).isoformat(),
        "status": "active",
    }


# --- Authentication ---------------------------------------------------


def test_create_advertiser_returns_api_key_once(client):
    response = client.post("/advertisers", json={"name": "Key Co"})
    assert response.status_code == 201
    body = response.json()
    assert "api_key" in body and len(body["api_key"]) > 20


def test_created_advertiser_stores_only_the_hash(client, db):
    api_key = client.post("/advertisers", json={"name": "Hash Co"}).json()["api_key"]
    advertiser = db.query(Advertiser).filter(Advertiser.name == "Hash Co").one()
    # The plaintext key must not be recoverable from the database.
    assert advertiser.api_key_hash == hash_api_key(api_key)
    assert api_key not in (advertiser.api_key_hash or "")


def test_create_campaign_requires_api_key(client):
    response = client.post("/campaigns", json=_campaign_payload())
    assert response.status_code == 401


def test_create_campaign_rejects_unknown_api_key(client):
    response = client.post(
        "/campaigns", json=_campaign_payload(), headers={"X-API-Key": generate_api_key()}
    )
    assert response.status_code == 401


def test_create_campaign_succeeds_with_valid_key(client):
    api_key = client.post("/advertisers", json={"name": "Valid Co"}).json()["api_key"]
    response = client.post(
        "/campaigns", json=_campaign_payload(), headers={"X-API-Key": api_key}
    )
    assert response.status_code == 201


def test_campaign_owner_comes_from_key_not_request_body(client):
    """The core authorization fix: a caller cannot create a campaign under
    somebody else's advertiser id, even by naming it explicitly."""
    victim = client.post("/advertisers", json={"name": "Victim Co"}).json()
    attacker_key = client.post("/advertisers", json={"name": "Attacker Co"}).json()["api_key"]

    payload = _campaign_payload() | {"advertiser_id": victim["id"]}
    created = client.post("/campaigns", json=payload, headers={"X-API-Key": attacker_key})

    assert created.status_code == 201
    # The injected advertiser_id was ignored entirely, not honoured.
    assert created.json()["advertiser_id"] != victim["id"]


# --- Authorization (ownership) ----------------------------------------


def test_cannot_set_targeting_on_another_advertisers_campaign(client, db):
    owner_key = client.post("/advertisers", json={"name": "Owner Co"}).json()["api_key"]
    other_key = client.post("/advertisers", json={"name": "Other Co"}).json()["api_key"]

    campaign_id = client.post(
        "/campaigns", json=_campaign_payload(), headers={"X-API-Key": owner_key}
    ).json()["id"]

    response = client.post(
        f"/campaigns/{campaign_id}/targeting",
        json={"country": "US"},
        headers={"X-API-Key": other_key},
    )
    # 404, not 403 - deliberately indistinguishable from a campaign that
    # doesn't exist, so ids can't be enumerated by probing.
    assert response.status_code == 404


def test_owner_can_set_targeting_on_own_campaign(client):
    owner_key = client.post("/advertisers", json={"name": "Self Co"}).json()["api_key"]
    campaign_id = client.post(
        "/campaigns", json=_campaign_payload(), headers={"X-API-Key": owner_key}
    ).json()["id"]

    response = client.post(
        f"/campaigns/{campaign_id}/targeting",
        json={"country": "US"},
        headers={"X-API-Key": owner_key},
    )
    assert response.status_code == 201


# --- Rate limiting ----------------------------------------------------


def test_rate_limit_allows_under_the_threshold(client, test_redis, monkeypatch):
    monkeypatch.setattr("app.core.rate_limit.AUCTION_RATE_LIMIT", 3)
    unknown_user = str(uuid.uuid4())

    for _ in range(3):
        response = client.post("/auction", json={"user_id": unknown_user})
        # 404 (no such user) proves the request got PAST the rate limiter
        # and reached the handler, which is what's being tested here.
        assert response.status_code == 404


def test_rate_limit_rejects_over_the_threshold(client, test_redis, monkeypatch):
    monkeypatch.setattr("app.core.rate_limit.AUCTION_RATE_LIMIT", 3)
    unknown_user = str(uuid.uuid4())

    for _ in range(3):
        client.post("/auction", json={"user_id": unknown_user})

    response = client.post("/auction", json={"user_id": unknown_user})
    assert response.status_code == 429
    assert "Retry-After" in response.headers


def test_rate_limit_window_expires(client, test_redis, monkeypatch):
    """The counter is scoped to a window, not a permanent allowance -
    clearing the key stands in for the window elapsing, so the test
    doesn't have to sleep for real."""
    monkeypatch.setattr("app.core.rate_limit.AUCTION_RATE_LIMIT", 2)
    unknown_user = str(uuid.uuid4())

    for _ in range(3):
        client.post("/auction", json={"user_id": unknown_user})
    assert client.post("/auction", json={"user_id": unknown_user}).status_code == 429

    test_redis.flushdb()
    assert client.post("/auction", json={"user_id": unknown_user}).status_code == 404


# --- Idempotency ------------------------------------------------------


def test_conversion_without_idempotency_key_creates_distinct_events(client, test_redis):
    click_id = str(uuid.uuid4())
    first = client.post(f"/clicks/{click_id}/conversions").json()
    second = client.post(f"/clicks/{click_id}/conversions").json()
    # No key supplied - each call is treated as a genuinely new conversion.
    assert first["id"] != second["id"]


def test_conversion_with_idempotency_key_replays_same_response(client, test_redis):
    click_id = str(uuid.uuid4())
    headers = {"Idempotency-Key": str(uuid.uuid4())}

    first = client.post(f"/clicks/{click_id}/conversions", headers=headers)
    second = client.post(f"/clicks/{click_id}/conversions", headers=headers)

    assert first.status_code == 201 and second.status_code == 201
    # Byte-for-byte the same conversion, not a second one.
    assert first.json() == second.json()


def test_different_idempotency_keys_are_independent(client, test_redis):
    click_id = str(uuid.uuid4())
    first = client.post(
        f"/clicks/{click_id}/conversions", headers={"Idempotency-Key": str(uuid.uuid4())}
    ).json()
    second = client.post(
        f"/clicks/{click_id}/conversions", headers={"Idempotency-Key": str(uuid.uuid4())}
    ).json()
    assert first["id"] != second["id"]


def test_in_flight_idempotency_key_conflicts(client, test_redis):
    """A key claimed but not yet completed returns 409 rather than
    replaying a response that doesn't exist yet."""
    key = str(uuid.uuid4())
    test_redis.set(f"idempotency:conversion:{key}", "__in_progress__", ex=60)

    response = client.post(
        f"/clicks/{uuid.uuid4()}/conversions", headers={"Idempotency-Key": key}
    )
    assert response.status_code == 409
