from datetime import datetime, timezone, date
from decimal import Decimal
from sqlalchemy.orm import Session
from app.models.campaign import Campaign, CampaignStatus
from app.models.audience_targeting import AudienceTargeting
from app.models.impression import Impression
from app.models.user import User
import random


# Flat placeholder cost charged to a campaign's spend each time it wins an
# auction. Shared between the eligibility check (is there room for one more
# win?) and record_win (actually charging for one) so the two can never
# drift out of sync.
COST_PER_WIN = Decimal("0.50")

def get_campaign_candidates(db: Session) -> list[Campaign]:
    """Query campaigns eligible on their own attributes alone.

    Checks only what doesn't depend on which user is asking: active
    status, within the campaign's date window, and enough budget
    remaining to cover one more win. Per-user targeting (age/country/
    device/interests) is checked separately in matches_targeting, once
    this candidate list is already narrowed down.

    Returns:
        Campaigns passing the campaign-level checks, unfiltered by user.
    """
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
    """Compute a whole-number age in years from a birthdate.

    Args:
        birthdate: The person's date of birth.
        today: The date to compute age as of. Defaults to the real current
            date; overridable so this stays testable without depending on
            whatever day the code happens to run.

    Returns:
        Age in whole years, correctly handling whether this year's
        birthday has already happened (e.g. someone born March 15th is
        still one year younger on March 1st than on March 16th).
    """
    if today is None:
        today = date.today()
    return today.year - birthdate.year - ((today.month, today.day) < (birthdate.month, birthdate.day))


def matches_targeting(targeting: AudienceTargeting, user: User, user_age: int) -> bool:
    """Check whether a single targeting row matches a specific user.

    Every field follows the same rule: null/empty means unrestricted on
    that dimension, otherwise the user must satisfy it. Interests use
    "any overlap counts" - a user only needs to share one interest with
    the campaign's targeted list, not match all of them.

    Args:
        targeting: The campaign's audience targeting rules.
        user: The user being evaluated.
        user_age: The user's current age, precomputed by the caller (see
            compute_age) rather than derived here, since callers checking
            many campaigns against the same user shouldn't recompute it
            once per campaign.

    Returns:
        True if the user satisfies every targeting restriction.
    """
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
    """Get every campaign eligible to compete for this user's auction.

    Combines the cheap, campaign-level SQL filter (get_campaign_candidates)
    with the per-user targeting check (matches_targeting) run in Python
    against just that narrowed-down candidate set - not every campaign in
    the database.

    Args:
        db: Active database session.
        user: The user the auction is being run for.

    Returns:
        Campaigns eligible to be scored and potentially win, for this
        specific user, right now.
    """
    user_age = compute_age(user.birthdate)
    candidates = get_campaign_candidates(db)
    return [
        campaign for campaign in candidates
        if campaign.targeting is None or matches_targeting(campaign.targeting, user, user_age)
    ]


def score_campaign(campaign: Campaign, user: User) -> int:
    """Score how well a campaign matches a user, for ranking purposes.

    Deliberately kept as its own function, separate from filtering and
    auction mechanics, so a trained model's prediction can replace this
    scoring rule later without touching how eligibility or winner
    selection work.

    Args:
        campaign: An already-eligible campaign (see filter_eligible_campaigns).
        user: The user being scored against.

    Returns:
        A baseline of 1 (so even broad, untargeted campaigns can still
        occasionally win) plus one point per interest the campaign's
        targeting shares with the user.
    """
    targeting = campaign.targeting
    if targeting is None or not targeting.interests:
        return 1

    targeting_interest_ids = {i.id for i in targeting.interests}
    user_interest_ids = {i.id for i in user.interests}
    overlap = len(targeting_interest_ids & user_interest_ids)
    return 1 + overlap


def pick_winner(eligible_campaigns: list[Campaign], user: User) -> Campaign | None:
    """Pick a winning campaign via weighted-random selection.

    Deliberately not a hard "highest score always wins" - a campaign's
    odds are proportional to its score, so a strong match usually but not
    always wins, and broad/low-score campaigns still get a real, if
    smaller, chance. This function has no side effects (it doesn't touch
    the database), so it's safe to call repeatedly for testing/inspection
    without accidentally recording wins that never really happened - see
    record_win for the actual side-effecting step.

    Args:
        eligible_campaigns: Campaigns already filtered as eligible for this user.
        user: The user being auctioned to, passed through to score_campaign.

    Returns:
        The winning campaign, or None if eligible_campaigns is empty (a
        "no fill" - no ad to show this user right now).
    """
    if not eligible_campaigns:
        return None

    scores = [score_campaign(c, user) for c in eligible_campaigns]
    return random.choices(eligible_campaigns, weights=scores, k=1)[0]

def record_win(db: Session, campaign: Campaign, user: User) -> Impression:
    """Record that a campaign won an auction: charge it for the win and
    log an impression capturing the full decision-time context.

    Only ever increments spent - budget is the campaign's fixed original
    allocation and should never be modified after creation, so "remaining
    budget" stays a computed value (budget - spent) rather than something
    stored and mutated directly. The impression snapshots the user's
    attributes and interests as they are right now, since a planned future
    step will make user interests mutable over time - without this
    snapshot, this historical record would silently become inaccurate
    once that ships.

    Args:
        db: Active database session.
        campaign: The campaign that won and should be charged.
        user: The user the auction was run for.

    Returns:
        The newly created Impression row.
    """
    campaign.spent += COST_PER_WIN

    impression = Impression(
        user_id=user.id,
        campaign_id=campaign.id,
        occurred_at=datetime.now(timezone.utc),
        user_age=compute_age(user.birthdate),
        user_country=user.country,
        user_device_type=user.device_type,
        score=score_campaign(campaign, user),
        interests=list(user.interests),
    )
    db.add(impression)
    db.commit()
    db.refresh(impression)
    return impression