import random

from locust import HttpUser, task
from sqlalchemy import create_engine, text

from app.core.config import settings

engine = create_engine(settings.database_url)

with engine.connect() as conn:
    result = conn.execute(text("SELECT id from users ORDER BY random() LIMIT 5000"))
    USER_IDS = [str(row[0]) for row in result]


class AuctionUser(HttpUser):
    """Same as locustfile.py, minus wait_time - see STUDY_NOTES.md §15/§18.
    Locust's default wait_time inserts a 1-3s pause between each simulated
    user's requests, which is realistic for a real human but makes a sweep
    across user counts hard to compare: raising N mostly just adds more
    idle users, not more concurrent load. Removing it makes each user fire
    requests continuously, so N directly controls concurrent load - the
    property this sweep needs to find a real capacity ceiling."""

    @task
    def run_auction(self):
        user_id = random.choice(USER_IDS)
        self.client.post("/auction", json={"user_id": user_id})
