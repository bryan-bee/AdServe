from datetime import datetime, timezone, date
from decimal import Decimal
import json
import threading
import time
import uuid
from sqlalchemy.orm import Session, joinedload
from app.db.redis_client import redis_client
from app.db.session import SessionLocal
from app.models.campaign import Campaign, CampaignStatus
from app.models.audience_targeting import AudienceTargeting
from app.models.enums import DeviceType
from app.models.impression import Impression
from app.models.interest import Interest
from app.models.user import User
import random


# Flat placeholder cost charged to a campaign's spend each time it wins an
# auction. Shared between the eligibility check (is there room for one more
# win?) and record_win (actually charging for one) so the two can never
# drift out of sync.
COST_PER_WIN = Decimal("0.50")

# Redis cache for get_campaign_candidates - stale-while-revalidate. A
# single shared key, not per-user - the candidate list doesn't depend on
# who's asking. Reads within CANDIDATES_FRESH_SECONDS get the cached data
# with no extra work. Reads between the fresh and max-stale window still
# get the cached data immediately (no one waits), but trigger a background
# refresh so the *next* read is fresh again. Past the max-stale window
# (nothing refreshed it in time - e.g. a quiet traffic stretch), it's
# treated as a genuine miss and computed inline, blocking, same as before.
# The refresh lock prevents multiple concurrent stale reads from each
# spawning their own redundant background refresh - a real, measured
# "cache stampede" under Locust load is exactly what this replaced (see
# STUDY_NOTES.md §13): a plain short TTL meant every ~5s, dozens of
# concurrent requests all missed at once and all redid the expensive query
# simultaneously, making things *worse* than no caching at 100 concurrent
# users (median latency 11s -> 16s, RPS 7.2 -> 4.89, before this fix).
CANDIDATES_CACHE_KEY = "auction:campaign_candidates"
CANDIDATES_FRESH_SECONDS = 5
CANDIDATES_MAX_STALE_SECONDS = 30
CANDIDATES_REFRESH_LOCK_KEY = "auction:campaign_candidates:refresh_lock"
CANDIDATES_REFRESH_LOCK_TTL_SECONDS = 10
# For a genuine miss (nothing cached at all - cold start, or the max-stale
# window fully elapsed): how long a request waits, retrying the cache,
# while some other concurrent request holds the lock and computes it.
MISS_WAIT_RETRIES = 10
MISS_WAIT_INTERVAL_SECONDS = 0.05


def _serialize_candidates(candidates: list[Campaign]) -> str:
    """Convert candidate Campaigns to a JSON string for storing in Redis,
    tagged with when it was computed so get_campaign_candidates can tell
    fresh from stale-but-usable from too-old. Only includes what
    matches_targeting/score_campaign/the endpoint actually read - not the
    full row (budget/spent/dates/status don't matter once a campaign has
    already passed the SQL filter)."""
    return json.dumps({
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "candidates": [
            {
                "id": str(c.id),
                "advertiser_id": str(c.advertiser_id),
                "targeting": None if c.targeting is None else {
                    "min_age": c.targeting.min_age,
                    "max_age": c.targeting.max_age,
                    "country": c.targeting.country,
                    "device_type": c.targeting.device_type.value if c.targeting.device_type else None,
                    "interest_ids": [str(i.id) for i in c.targeting.interests],
                },
            }
            for c in candidates
        ],
    })


def _deserialize_candidates(rows: list[dict]) -> list[Campaign]:
    """Rebuild real (but session-detached) Campaign/AudienceTargeting/
    Interest objects from already-parsed cached rows - the same "construct
    an ORM object directly, not from a query" pattern already used
    throughout the test suite. matches_targeting/score_campaign only ever
    read attributes off these, so they work identically whether an object
    came from a fresh query or was rebuilt from cache."""
    candidates = []
    for row in rows:
        targeting = None
        if row["targeting"] is not None:
            t = row["targeting"]
            targeting = AudienceTargeting(
                min_age=t["min_age"],
                max_age=t["max_age"],
                country=t["country"],
                device_type=DeviceType(t["device_type"]) if t["device_type"] else None,
                interests=[Interest(id=uuid.UUID(iid)) for iid in t["interest_ids"]],
            )
        candidates.append(Campaign(
            id=uuid.UUID(row["id"]),
            advertiser_id=uuid.UUID(row["advertiser_id"]),
            targeting=targeting,
        ))
    return candidates


def _query_candidates_and_cache(db: Session) -> list[Campaign]:
    """Run the actual expensive query and populate the cache. Shared by a
    genuine cache miss (called inline, blocking) and a background refresh
    (called in its own thread, with its own session), so both paths always
    stay in sync with exactly one implementation of the query itself.

    Eagerly loads each campaign's targeting (and its interests), since
    matches_targeting/score_campaign access both on every candidate -
    without this, each access would lazily fire its own query, an N+1
    problem that gets worse the more candidates there are. Uses joinedload
    (a single JOIN) rather than selectinload for interests too - at this
    candidate volume, selectinload's giant `WHERE id IN (...)` parameter
    list was itself the bottleneck (measured ~300ms), even though the
    actual data was cheap to fetch (~13ms via a plain JOIN). Some row
    duplication from the many-to-many join is fine here - SQLAlchemy
    de-duplicates it back into distinct objects.
    """
    now = datetime.now(timezone.utc)
    candidates = (
        db.query(Campaign)
        .options(joinedload(Campaign.targeting).joinedload(AudienceTargeting.interests))
        .filter(
            Campaign.status == CampaignStatus.ACTIVE,
            Campaign.start_date <= now,
            Campaign.end_date >= now,
            Campaign.spent + COST_PER_WIN <= Campaign.budget,
        )
        .all()
    )
    redis_client.setex(CANDIDATES_CACHE_KEY, CANDIDATES_MAX_STALE_SECONDS, _serialize_candidates(candidates))
    return candidates


def _background_refresh_candidates_cache() -> None:
    """Refresh the cache in the background, assuming the caller ALREADY
    acquired the refresh lock synchronously before spawning this thread.

    Opens its own DB session, since a background thread can't safely reuse
    the original request's session. The lock is acquired by the caller
    rather than here deliberately: checking it in the request thread (one
    cheap Redis call) means we only ever spawn a thread for the single
    request that actually won the right to refresh, instead of spawning
    one per stale request and having all but one immediately exit. That
    wasted thread churn measurably hurt throughput under load."""
    db = SessionLocal()
    try:
        _query_candidates_and_cache(db)
    finally:
        db.close()
        redis_client.delete(CANDIDATES_REFRESH_LOCK_KEY)


def get_campaign_candidates(db: Session) -> list[Campaign]:
    """Query campaigns eligible on their own attributes alone.

    Checks only what doesn't depend on which user is asking: active
    status, within the campaign's date window, and enough budget
    remaining to cover one more win. Per-user targeting (age/country/
    device/interests) is checked separately in matches_targeting, once
    this candidate list is already narrowed down.

    Uses stale-while-revalidate caching (see the CANDIDATES_* constants
    above): a fresh cache hit returns immediately with no extra work; a
    stale-but-usable hit also returns immediately, but triggers a
    background refresh for next time; a genuine miss (nothing cached, or
    past the max-stale window) blocks and computes it inline, same as a
    plain cache would.

    Returns:
        Campaigns passing the campaign-level checks, unfiltered by user.
    """
    cached = redis_client.get(CANDIDATES_CACHE_KEY)

    if cached is not None:
        data = json.loads(cached)
        computed_at = datetime.fromisoformat(data["computed_at"])
        age_seconds = (datetime.now(timezone.utc) - computed_at).total_seconds()

        if age_seconds > CANDIDATES_FRESH_SECONDS and redis_client.set(
            CANDIDATES_REFRESH_LOCK_KEY, "1", nx=True, ex=CANDIDATES_REFRESH_LOCK_TTL_SECONDS
        ):
            threading.Thread(target=_background_refresh_candidates_cache, daemon=True).start()

        return _deserialize_candidates(data["candidates"])

    # Genuine miss - nothing cached at all (cold start, or the max-stale
    # window fully elapsed with no traffic to trigger a refresh). Same
    # lock as the background-refresh path: only the request that wins it
    # actually pays for the expensive query. Everyone else waits briefly
    # and retries the cache instead of each redoing the same work - this
    # is the same stampede risk as the background-refresh path, just for
    # the cold-start moment instead of the steady-state one.
    if redis_client.set(CANDIDATES_REFRESH_LOCK_KEY, "1", nx=True, ex=CANDIDATES_REFRESH_LOCK_TTL_SECONDS):
        try:
            return _query_candidates_and_cache(db)
        finally:
            redis_client.delete(CANDIDATES_REFRESH_LOCK_KEY)

    for _ in range(MISS_WAIT_RETRIES):
        time.sleep(MISS_WAIT_INTERVAL_SECONDS)
        cached = redis_client.get(CANDIDATES_CACHE_KEY)
        if cached is not None:
            data = json.loads(cached)
            return _deserialize_candidates(data["candidates"])

    # Still nothing after waiting (the lock holder crashed, or is just
    # unusually slow) - fall back to computing it ourselves rather than
    # blocking forever.
    return _query_candidates_and_cache(db)


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
    # campaign may have been rebuilt from the Redis cache (see
    # get_campaign_candidates), not loaded from this session - only a
    # real, session-attached object can be written to and committed.
    # If it's already in this session's identity map (the normal,
    # non-cached path), this is a no-op lookup, not a real extra query.
    campaign = db.get(Campaign, campaign.id)

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