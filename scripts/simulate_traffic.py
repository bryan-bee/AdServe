"""Fire simulated auction traffic (plus probabilistic clicks/conversions)
at the real running app, to populate realistic event data.

Requires the app to actually be running (uvicorn app.main:app).
Run with: python -m scripts.simulate_traffic
"""
import random

import httpx
from sqlalchemy import text

from app.db.session import SessionLocal
from app.models.audience_targeting import AudienceTargeting  # noqa: F401 - registers for Campaign.targeting relationship resolution
from app.models.campaign import Campaign
from app.models.user import User

BASE_URL = "http://127.0.0.1:8000"
NUM_REQUESTS = 500
CONVERSION_RATE = 0.10

BASE_CLICK_RATE = 0.01
PER_OVERLAP_BONUS = 0.02
MAX_CLICK_RATE = 0.2


def true_click_probability(campaign: Campaign, user: User) -> float:
    """The 'ground truth' of whether this simulated user would click - an
    evaluation harness, deliberately independent of score_campaign (the
    system under test).

    Computed directly from raw interest overlap between the user and the
    campaign's targeting, never from campaign.targeting's live score. If
    clicks were generated from score_campaign's own output instead, any
    future improvement to that scoring function would automatically look
    like a CTR improvement here too - even if the change didn't actually
    make ranking better - since the "test" would just be agreeing with
    itself. Keeping this function fixed and never touching it when
    score_campaign changes is what makes a future before/after CTR
    comparison a real, falsifiable measurement instead of a tautology.
    """
    targeting = campaign.targeting
    if targeting is None or not targeting.interests:
        return BASE_CLICK_RATE
    targeting_ids = {i.id for i in targeting.interests}
    user_ids = {i.id for i in user.interests}
    overlap = len(targeting_ids & user_ids)
    return min(BASE_CLICK_RATE + PER_OVERLAP_BONUS * overlap, MAX_CLICK_RATE)


def get_random_user_ids(db, count: int) -> list[str]:
    rows = db.execute(
        text("SELECT id FROM users ORDER BY random() LIMIT :count"),
        {"count": count},
    ).fetchall()
    return [str(row[0]) for row in rows]


def simulate_one(client: httpx.Client, db, user_id: str) -> str:
    response = client.post(f"{BASE_URL}/auction", json={"user_id": user_id})

    if response.status_code == 204:
        return "no_fill"

    response.raise_for_status()
    data = response.json()
    impression_id = data["impression_id"]

    user = db.get(User, user_id)
    campaign = db.get(Campaign, data["campaign_id"])

    if random.random() >= true_click_probability(campaign, user):
        return "impression_only"

    click_response = client.post(f"{BASE_URL}/impressions/{impression_id}/clicks")
    click_response.raise_for_status()

    if random.random() >= CONVERSION_RATE:
        return "click"

    click_id = click_response.json()["id"]
    client.post(f"{BASE_URL}/clicks/{click_id}/conversions").raise_for_status()
    return "conversion"


if __name__ == "__main__":
    db = SessionLocal()
    try:
        user_ids = get_random_user_ids(db, NUM_REQUESTS)

        counts = {"no_fill": 0, "impression_only": 0, "click": 0, "conversion": 0}
        with httpx.Client() as client:
            for i, user_id in enumerate(user_ids, start=1):
                outcome = simulate_one(client, db, user_id)
                counts[outcome] += 1
                if i % 200 == 0 or i == len(user_ids):
                    print(f"  ...{i}/{len(user_ids)} requests sent")

        print(f"\nDone: {counts}")
    finally:
        db.close()
