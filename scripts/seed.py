from faker import Faker

from app.db.session import SessionLocal
from app.models.advertiser import Advertiser
from sqlalchemy import text, insert

import random
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.models.campaign import Campaign, CampaignStatus
from app.models.audience_targeting import AudienceTargeting
from app.models.enums import DeviceType
from app.models.interest import Interest
from app.models.user import User, user_interests


fake = Faker()

NUM_ADVERTISERS = 5_000

# Long-tail campaign counts: most advertisers run a handful of campaigns,
# a small fraction run many. (min_campaigns, max_campaigns) per tier, with
# weights controlling how likely an advertiser is to land in each tier.
CAMPAIGN_TIERS = [(1, 3), (4, 10), (11, 50)]
CAMPAIGN_TIER_WEIGHTS = [70, 25, 5]

# Interests with a relative popularity weight (higher = more common), so
# sampling reflects the fact that real interests aren't equally popular -
# "music" is far more common than "birdwatching."
INTEREST_WEIGHTS = {
    "music": 100, "movies_tv": 95, "gaming": 85, "technology": 82,
    "sports": 80, "travel": 75, "fitness": 70, "cooking": 68,
    "comedy": 65, "news": 62, "fashion": 60, "reading": 58,
    "photography": 55, "finance": 52, "food_drink": 50, "automotive": 48,
    "pets": 47, "wellness": 45, "science": 43, "diy_crafts": 40,
    "parenting": 38, "business": 37, "education": 36, "home_garden": 34,
    "makeup": 33, "outdoors": 32, "art_design": 30, "real_estate": 28,
    "history": 27, "podcasts": 26, "board_games": 24, "anime": 23,
    "camping": 22, "hiking": 21, "yoga": 20, "crypto": 18,
    "astrology": 16, "birdwatching": 12, "collecting": 10, "philosophy": 8,
}
INTEREST_NAMES = list(INTEREST_WEIGHTS.keys())
INTEREST_WEIGHT_VALUES = list(INTEREST_WEIGHTS.values())

NUM_USERS = 2_000_000
USER_BATCH_SIZE = 50_000
MIN_INTERESTS_PER_USER = 1
MAX_INTERESTS_PER_USER = 4


def weighted_sample_without_replacement(population, weights, k):
    """Pick k unique items from population, biased by weights (no duplicates)."""
    population = list(population)
    weights = list(weights)
    chosen = []
    for _ in range(k):
        pick = random.choices(population, weights=weights, k=1)[0]
        idx = population.index(pick)
        population.pop(idx)
        weights.pop(idx)
        chosen.append(pick)
    return chosen


def seed_advertisers(db):
    """Create NUM_ADVERTISERS fake Advertiser rows."""
    advertisers = []
    for _ in range(NUM_ADVERTISERS):
        advertiser = Advertiser(name=fake.company())
        db.add(advertiser)
        advertisers.append(advertiser)
    db.commit()
    return advertisers


def reset_tables(db):
    """Wipe advertisers/interests/users (and everything that cascades from
    them - campaigns, audience_targeting, user_interests, targeting_interests)
    so every run of this script starts from a clean, reproducible slate."""
    db.execute(text("TRUNCATE advertisers, interests, users CASCADE"))
    db.commit()


def seed_interests(db):
    """Create one Interest row per name in INTEREST_WEIGHTS - the fixed
    vocabulary that both User and AudienceTargeting link to."""
    interests = [Interest(name=name) for name in INTEREST_NAMES]
    db.add_all(interests)
    db.commit()
    return interests


def seed_campaigns(db, advertisers):
    """Create a long-tail number of Campaign rows per advertiser (most get
    1-3, a few get up to 50 - see CAMPAIGN_TIERS/CAMPAIGN_TIER_WEIGHTS)."""
    campaigns = []
    for advertiser in advertisers:
        min_campaigns, max_campaigns = random.choices(CAMPAIGN_TIERS, weights=CAMPAIGN_TIER_WEIGHTS)[0]
        num_campaigns = random.randint(min_campaigns, max_campaigns)
        for _ in range(num_campaigns):
            start_date = fake.date_time_between(start_date="-6M", end_date="now", tzinfo=timezone.utc)
            end_date = start_date + timedelta(days=random.randint(14, 90))

            if end_date < datetime.now(timezone.utc):
                status = CampaignStatus.ENDED
            else:
                status = random.choices([CampaignStatus.ACTIVE, CampaignStatus.PAUSED], weights=[85, 15])[0]

            campaign = Campaign(
                advertiser_id=advertiser.id,
                budget=Decimal(random.randrange(500, 50000)) / 100 * 100,
                start_date=start_date,
                end_date=end_date,
                status=status,
            )
            db.add(campaign)
            campaigns.append(campaign)
    db.commit()
    return campaigns


def seed_targeting(db, campaigns, interests):
    """Create one AudienceTargeting row per campaign, with randomized
    age/device restrictions (each independently blank ~50% of the time),
    country restriction (blank ~15% of the time, since geographic
    targeting is close to universal in real campaigns), and a
    popularity-weighted set of 0-4 targeted interests."""
    targets = []
    total = len(campaigns)
    for i, campaign in enumerate(campaigns, start=1):
        num_interests = random.choices([0, 1, 2, 3, 4], weights=[10, 25, 25, 20, 20])[0]
        targeting = AudienceTargeting(
            campaign_id=campaign.id,
            device_type=random.choice(list(DeviceType)) if random.random() < 0.5 else None,
            min_age=random.randint(18, 30) if random.random() < 0.5 else None,
            max_age=random.randint(35, 65) if random.random() < 0.5 else None,
            country=fake.country_code() if random.random() < 0.85 else None,
            interests=weighted_sample_without_replacement(interests, INTEREST_WEIGHT_VALUES, num_interests),
        )
        db.add(targeting)
        targets.append(targeting)
        if i % 1000 == 0 or i == total:
            print(f"  ...{i}/{total} targeting rows built")
    db.commit()
    return targets


def seed_users(db, interests):
    """Bulk-insert NUM_USERS fake User rows (in USER_BATCH_SIZE-sized
    batches to bound memory usage), each with 1-4 popularity-weighted
    interests, linked via bulk inserts into the user_interests table."""
    total_seeded = 0

    for batch_start in range(0, NUM_USERS, USER_BATCH_SIZE):
        batch_size = min(USER_BATCH_SIZE, NUM_USERS - batch_start)

        user_rows = []
        user_interest_rows = []

        for _ in range(batch_size):
            user_id = uuid.uuid4()
            user_rows.append({
                "id": user_id,
                "name": fake.name(),
                "birthdate": fake.date_of_birth(minimum_age=13, maximum_age=80),
                "country": fake.country_code(),
                "device_type": random.choice(list(DeviceType)),
            })

            num_interests = random.randint(MIN_INTERESTS_PER_USER, MAX_INTERESTS_PER_USER)
            for interest in weighted_sample_without_replacement(interests, INTEREST_WEIGHT_VALUES, num_interests):
                user_interest_rows.append({
                    "user_id": user_id,
                    "interest_id": interest.id,
                })

        db.execute(insert(User), user_rows)
        db.execute(insert(user_interests), user_interest_rows)
        db.commit()

        total_seeded += batch_size
        print(f"  ...{total_seeded}/{NUM_USERS} users seeded")

    return total_seeded


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

        num_users = seed_users(db, interests)
        print(f"Seeded {num_users} users")
    finally:
        db.close()
