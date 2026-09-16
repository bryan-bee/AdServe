from datetime import datetime, timezone, date
from decimal import Decimal
from sqlalchemy.orm import Session
from app.models.campaign import Campaign, CampaignStatus
from app.models.audience_targeting import AudienceTargeting
from app.models.user import User
import random


COST_PER_WIN = Decimal("0.50")

def get_campaign_candidates(db: Session) -> list[Campaign]:
    now = datetime.now(timezone.utc)
    return (
        db.query(Campaign)
        .filter(
            Campaign.status == CampaignStatus.ACTIVE,
            Campaign.start_date <= now,
            Campaign.end_date >= now,
            Campaign.spent + COST_PER_WIN <= Campaign.budget,
        )
        .all()
    )


def compute_age(birthdate: date, today: date | None = None) -> int:
    if today is None:
        today = date.today()
    return today.year - birthdate.year - ((today.month, today.day) < (birthdate.month, birthdate.day))


def matches_targeting(targeting: AudienceTargeting, user: User, user_age: int) -> bool:
    if targeting.min_age is not None and user_age < targeting.min_age:
        return False
    if targeting.max_age is not None and user_age > targeting.max_age:
        return False
    if targeting.country is not None and targeting.country != user.country:
        return False
    if targeting.device_type is not None and targeting.device_type != user.device_type:
        return False

    if targeting.interests:
        targeting_interest_ids = {i.id for i in targeting.interests}
        user_interest_ids = {i.id for i in user.interests}
        if not targeting_interest_ids & user_interest_ids:
            return False

    return True


def filter_eligible_campaigns(db: Session, user: User) -> list[Campaign]:
    user_age = compute_age(user.birthdate)
    candidates = get_campaign_candidates(db)
    return [
        campaign for campaign in candidates
        if campaign.targeting is None or matches_targeting(campaign.targeting, user, user_age)
    ]


def score_campaign(campaign: Campaign, user: User) -> int:
    targeting = campaign.targeting
    if targeting is None or not targeting.interests:
        return 1

    targeting_interest_ids = {i.id for i in targeting.interests}
    user_interest_ids = {i.id for i in user.interests}
    overlap = len(targeting_interest_ids & user_interest_ids)
    return 1 + overlap


def pick_winner(eligible_campaigns: list[Campaign], user: User) -> Campaign | None:
    if not eligible_campaigns:
        return None

    scores = [score_campaign(c, user) for c in eligible_campaigns]
    return random.choices(eligible_campaigns, weights=scores, k=1)[0]

def record_win(db: Session, campaign: Campaign) -> None:
    campaign.spent += COST_PER_WIN
    db.commit()