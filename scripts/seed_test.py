"""Seed the dedicated test database (adserve_test) with a small, deterministic
dataset for integration tests. Never touches the main dev database.

Run with: python -m scripts.seed_test
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.advertiser import Advertiser
from app.models.audience_targeting import AudienceTargeting
from app.models.campaign import Campaign, CampaignStatus
from app.models.enums import DeviceType
from app.models.interest import Interest
from app.models.user import User

test_engine = create_engine(settings.test_database_url)
TestSessionLocal = sessionmaker(bind=test_engine)


def reset_tables(db):
    db.execute(text("TRUNCATE advertisers, interests, users CASCADE"))
    db.commit()


def seed(db):
    gaming = Interest(name="gaming")
    cooking = Interest(name="cooking")
    db.add_all([gaming, cooking])
    db.commit()

    advertiser = Advertiser(name="Test Advertiser Inc")
    db.add(advertiser)
    db.commit()

    now = datetime.now(timezone.utc)

    # A genuinely eligible campaign: active, within its window, budget untouched.
    active_campaign = Campaign(
        advertiser_id=advertiser.id,
        budget=Decimal("100.00"),
        start_date=now - timedelta(days=10),
        end_date=now + timedelta(days=10),
        status=CampaignStatus.ACTIVE,
    )
    # Deliberately stale: end_date already passed, but status still says
    # "active" - exactly the scenario the auction's live date check exists
    # to catch, regardless of what status claims.
    expired_campaign = Campaign(
        advertiser_id=advertiser.id,
        budget=Decimal("100.00"),
        start_date=now - timedelta(days=30),
        end_date=now - timedelta(days=1),
        status=CampaignStatus.ACTIVE,
    )
    db.add_all([active_campaign, expired_campaign])
    db.commit()

    active_targeting = AudienceTargeting(
        campaign_id=active_campaign.id,
        min_age=18,
        interests=[gaming],
    )
    expired_targeting = AudienceTargeting(campaign_id=expired_campaign.id)
    db.add_all([active_targeting, expired_targeting])
    db.commit()

    user = User(
        name="Test User",
        birthdate=now.date().replace(year=now.year - 25),
        country="US",
        device_type=DeviceType.MOBILE,
        interests=[gaming],
    )
    db.add(user)
    db.commit()

    return {
        "advertiser": advertiser,
        "active_campaign": active_campaign,
        "expired_campaign": expired_campaign,
        "user": user,
    }


if __name__ == "__main__":
    db = TestSessionLocal()
    try:
        reset_tables(db)
        result = seed(db)
        print(
            f"Seeded test DB: user={result['user'].id}, "
            f"active_campaign={result['active_campaign'].id}, "
            f"expired_campaign={result['expired_campaign'].id}"
        )
    finally:
        db.close()
