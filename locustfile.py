import random

from locust import HttpUser, task, between
from sqlalchemy import create_engine, text

from app.core.config import settings

engine = create_engine(settings.database_url)

with engine.connect() as conn:
    result = conn.execute(text("SELECT id from users ORDER BY random() LIMIT 5000"))
    USER_IDS = [str(row[0]) for row in result]

class AuctionUser(HttpUser):
    wait_time = between(1, 3)

    @task
    def run_auction(self):
        user_id = random.choice(USER_IDS)
        self.client.post("/auction", json={"user_id": user_id})