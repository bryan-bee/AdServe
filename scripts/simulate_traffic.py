"""Fire simulated auction traffic (plus probabilistic clicks/conversions)
at the real running app, to populate realistic event data.

Requires the app to actually be running (uvicorn app.main:app).
Run with: python -m scripts.simulate_traffic
"""
import random

import httpx
from sqlalchemy import text

from app.db.session import SessionLocal

BASE_URL = "http://127.0.0.1:8000"
NUM_REQUESTS = 500
CONVERSION_RATE = 0.10


def click_probability(score: int) -> float:
    """Higher-scoring (better-matched) impressions get clicked more often,
    so the simulated data actually contains a learnable match-quality ->
    engagement signal, rather than being pure noise."""
    return min(score * 0.02, 0.2)


def get_random_user_ids(db, count: int) -> list[str]:
    rows = db.execute(
        text("SELECT id FROM users ORDER BY random() LIMIT :count"),
        {"count": count},
    ).fetchall()
    return [str(row[0]) for row in rows]


def get_impression_score(db, impression_id: str) -> int:
    row = db.execute(
        text("SELECT score FROM impressions WHERE id = :id"),
        {"id": impression_id},
    ).fetchone()
    return row[0]


def simulate_one(client: httpx.Client, db, user_id: str) -> str:
    response = client.post(f"{BASE_URL}/auction", json={"user_id": user_id})

    if response.status_code == 204:
        return "no_fill"

    response.raise_for_status()
    impression_id = response.json()["impression_id"]

    score = get_impression_score(db, impression_id)
    if random.random() >= click_probability(score):
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
