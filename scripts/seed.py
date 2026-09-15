from faker import Faker

from app.db.session import SessionLocal
from app.models.advertiser import Advertiser
from sqlalchemy import text, insert

import random
import uuid
from datetime import timedelta, timezone
from decimal import Decimal

from app.models.campaign import Campaign, CampaignStatus
from app.models.audience_targeting import AudienceTargeting
from app.models.enums import DeviceType
from app.models.interest import Interest
from app.models.user import User, user_interests


fake = Faker()

NUM_ADVERTISERS = 50
MIN_CAMPAIGNS_PER_ADVERTISER = 3
MAX_CAMPAIGNS_PER_ADVERTISER = 4

INTEREST_NAMES = [
    "gaming", "fitness", "technology", "makeup", "travel",
    "sports", "camping", "music", "movies_tv", "cooking",
    "fashion", "finance", "automotive", "pets", "home_garden",
    "reading", "photography", "art_design", "wellness", "parenting",
]

NUM_USERS = 500_000  # bump to 500_000 once this checks out
MIN_INTERESTS_PER_USER = 1
MAX_INTERESTS_PER_USER = 4


def seed_advertisers(db):
    advertisers = []
    for _ in range(NUM_ADVERTISERS):
        advertiser = Advertiser(name=fake.company())
        db.add(advertiser)
        advertisers.append(advertiser)
    db.commit()
    return advertisers


def reset_tables(db):
    db.execute(text("TRUNCATE advertisers, interests, users CASCADE"))
    db.commit()


def seed_interests(db):
    interests = [Interest(name=name) for name in INTEREST_NAMES]
    db.add_all(interests)
    db.commit()
    return interests


def seed_campaigns(db, advertisers):
    campaigns = []
    for advertiser in advertisers:
        num_campaigns = random.randint(MIN_CAMPAIGNS_PER_ADVERTISER, MAX_CAMPAIGNS_PER_ADVERTISER)
        for _ in range(num_campaigns):
            start_date = fake.date_time_between(start_date="-6M", end_date="now", tzinfo=timezone.utc)
            end_date = start_date + timedelta(days=random.randint(14, 90))

            campaign = Campaign(
                advertiser_id=advertiser.id,
                budget=Decimal(random.randrange(500, 50000)) / 100 * 100,
                start_date=start_date,
                end_date=end_date,
                status=random.choice(list(CampaignStatus)),
            )
            db.add(campaign)
            campaigns.append(campaign)
    db.commit()
    return campaigns


def seed_targeting(db, campaigns, interests):
    targets = []
    for campaign in campaigns:
        num_interests = random.choices([0, 1, 2, 3, 4], weights=[10, 25, 25, 20, 20])[0]
        targeting = AudienceTargeting(
            campaign_id=campaign.id,
            device_type=random.choice(list(DeviceType)) if random.random() < 0.5 else None,
            min_age=random.randint(18, 30) if random.random() < 0.5 else None,
            max_age=random.randint(35, 65) if random.random() < 0.5 else None,
            country=fake.country_code() if random.random() < 0.5 else None,
            interests=random.sample(interests, num_interests),
        )
        db.add(targeting)
        targets.append(targeting)
    db.commit()
    return targets


def seed_users(db, interests):
    user_rows = []
    user_interest_rows = []

    for _ in range(NUM_USERS):
        user_id = uuid.uuid4()
        user_rows.append({
            "id": user_id,
            "name": fake.name(),
            "birthdate": fake.date_of_birth(minimum_age=13, maximum_age=80),
            "country": fake.country_code(),
            "device_type": random.choice(list(DeviceType)),
        })

        num_interests = random.randint(MIN_INTERESTS_PER_USER, MAX_INTERESTS_PER_USER)
        for interest in random.sample(interests, num_interests):
            user_interest_rows.append({
                "user_id": user_id,
                "interest_id": interest.id,
            })

    db.execute(insert(User), user_rows)
    db.execute(insert(user_interests), user_interest_rows)
    db.commit()

    return user_rows


if __name__ == "__main__":
    db = SessionLocal()
    try:
        reset_tables(db)

        advertisers = seed_advertisers(db)
        print(f"Seeded {len(advertisers)} advertisers")

        campaigns = seed_campaigns(db, advertisers)
        print(f"Seeded {len(campaigns)} campaigns")

        interests = seed_interests(db)
        print(f"Seeded {len(interests)} interests")

        targeting = seed_targeting(db, campaigns, interests)
        print(f"Seeded {len(targeting)} targetings")

        users = seed_users(db, interests)
        print(f"Seeded {len(users)} users")
    finally:
        db.close()
