from dataclasses import dataclass
from datetime import datetime, timezone, date
from decimal import Decimal
import json
import threading
import time
import uuid
from sqlalchemy import select, update
from sqlalchemy.orm import Session, joinedload
from app.db.redis_client import redis_client
from app.db.session import BackgroundSessionLocal, SessionLocal
from app.models.campaign import Campaign, CampaignStatus
from app.models.audience_targeting import AudienceTargeting
from app.models.enums import DeviceType
from app.models.impression import Impression
from app.models.user import User, user_interests
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
# A second, tiny key holding ONLY the payload's freshness stamp - kept
# separate from the full ~650KB candidate payload. Every request needs to
# answer "is my copy still current?", and reading a few bytes to answer
# that is far cheaper than reading and json-parsing the whole payload just
# to look at one field inside it. Always written AFTER the main payload
# (see _query_candidates_and_cache) - never before - so any request that
# observes this stamp is guaranteed the payload it names is already in
# Redis. See STUDY_NOTES.md §15.
CANDIDATES_STAMP_KEY = "auction:campaign_candidates:stamp"
CANDIDATES_FRESH_SECONDS = 5
CANDIDATES_MAX_STALE_SECONDS = 30
CANDIDATES_REFRESH_LOCK_KEY = "auction:campaign_candidates:refresh_lock"
CANDIDATES_REFRESH_LOCK_TTL_SECONDS = 10
# For a genuine miss (nothing cached at all - cold start, or the max-stale
# window fully elapsed): how long a request waits, retrying the cache,
# while some other concurrent request holds the lock and computes it.
MISS_WAIT_RETRIES = 10
MISS_WAIT_INTERVAL_SECONDS = 0.05

# Per-process, in-memory copy of the deserialized candidate list, keyed by
# the freshness stamp it was built from. Without this, every request redid
# ~14ms of work in _deserialize_candidates (reading + json-parsing the
# cached payload, then constructing ~9,300 CandidateCampaign/
# CandidateTargeting/CandidateInterest objects) even though that work
# produces an IDENTICAL result for every request served during the same
# cache generation. Measured to be the dominant source of GIL-holding CPU
# time under concurrent load - see STUDY_NOTES.md §15.
#
# Thread-safety: every request thread reads this same list and the same
# objects inside it, but nothing downstream ever writes to a candidate's
# attributes - filter_eligible_campaigns/matches_targeting/score_campaign/
# pick_winner only ever read (see their docstrings), and record_win never
# mutates a shared candidate either: it re-fetches a private, real
# session-attached Campaign via db.get() before writing anything. So
# concurrent reads of this shared list are safe. Refreshing it (the two
# dict assignments below) is a plain reference swap - atomic under the
# GIL - so a thread that already grabbed the old list keeps using it
# safely to completion; it never sees a half-updated value.
_local_candidates_cache: dict = {"stamp": None, "candidates": None}


# Lightweight, plain-Python stand-ins for Campaign/AudienceTargeting/
# Interest, used for the read-only filter/score/pick-winner path instead
# of real SQLAlchemy-mapped objects. Real ORM instances carry real cost to
# construct - change-tracking history, relationship/collection sync, an
# internal state object - none of which this read-only path needs.
# Measured directly: deserializing ~2,257 cached candidates into real ORM
# objects cost ~81ms of GIL-holding CPU per cache hit; the same data into
# these plain dataclasses cost ~11ms, a ~7.6x reduction. That GIL-holding
# time was the actual cause of a concurrency regression - see
# STUDY_NOTES.md §14. matches_targeting/score_campaign only ever read
# attributes (never check the concrete type), so real ORM objects (as
# used throughout the test suite) work identically via duck typing.
@dataclass(slots=True)
class CandidateTargeting:
    min_age: int | None
    max_age: int | None
    country: str | None
    device_type: DeviceType | None
    # A ready-to-intersect frozenset, built ONCE per cache generation rather
    # than rebuilt per request per campaign. The set is what
    # matches_targeting/score_campaign actually need; storing the underlying
    # interest objects instead meant every request rebuilt ~2,200 sets (one
    # per candidate) out of ~5,000 tiny objects that only ever existed to be
    # read back into a set. Same reasoning as _local_candidates_cache above:
    # identical work, repeated per request, holding the GIL.
    interest_ids: frozenset[uuid.UUID]


@dataclass(slots=True)
class CandidateCampaign:
    id: uuid.UUID
    advertiser_id: uuid.UUID
    targeting: CandidateTargeting | None


def _build_candidates_payload(candidates: list[Campaign]) -> dict:
    """Build the cacheable payload from real Campaign ORM objects (as
    returned by the actual database query) - tagged with when it was
    computed so get_campaign_candidates can tell fresh from
    stale-but-usable from too-old. Only includes what
    matches_targeting/score_campaign/the endpoint actually read - not the
    full row (budget/spent/dates/status don't matter once a campaign has
    already passed the SQL filter)."""
    return {
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
    }


def _deserialize_candidates(rows: list[dict]) -> list[CandidateCampaign]:
    """Rebuild lightweight CandidateCampaign/CandidateTargeting objects
    from already-parsed cached rows. Used for
    both a cache hit and a fresh database query's result (see
    _query_candidates_and_cache), so filter_eligible_campaigns/
    matches_targeting/score_campaign/pick_winner always receive the same
    type regardless of whether this request was a hit or a miss."""
    candidates = []
    for row in rows:
        targeting = None
        if row["targeting"] is not None:
            t = row["targeting"]
            targeting = CandidateTargeting(
                min_age=t["min_age"],
                max_age=t["max_age"],
                country=t["country"],
                device_type=DeviceType(t["device_type"]) if t["device_type"] else None,
                interest_ids=frozenset(uuid.UUID(iid) for iid in t["interest_ids"]),
            )
        candidates.append(CandidateCampaign(
            id=uuid.UUID(row["id"]),
            advertiser_id=uuid.UUID(row["advertiser_id"]),
            targeting=targeting,
        ))
    return candidates


def _query_candidates_and_cache(db: Session) -> list[CandidateCampaign]:
    """Run the actual expensive query and populate the cache. Shared by a
    genuine cache miss (called inline, blocking) and a background refresh
    (called in its own thread, with its own session), so both paths always
    stay in sync with exactly one implementation of the query itself.

    Eagerly loads each campaign's targeting (and its interests), since
    building the cache payload reads both on every candidate - without
    this, each access would lazily fire its own query, an N+1 problem
    that gets worse the more candidates there are. Uses joinedload (a
    single JOIN) rather than selectinload for interests too - at this
    candidate volume, selectinload's giant `WHERE id IN (...)` parameter
    list was itself the bottleneck (measured ~300ms), even though the
    actual data was cheap to fetch (~13ms via a plain JOIN). Some row
    duplication from the many-to-many join is fine here - SQLAlchemy
    de-duplicates it back into distinct objects.

    Returns CandidateCampaign objects, not the real Campaign ORM instances
    just queried - built from the same payload that gets cached, so a
    cache miss and a subsequent cache hit are guaranteed to hand callers
    the exact same shape.
    """
    now = datetime.now(timezone.utc)
    real_candidates = (
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
    payload = _build_candidates_payload(real_candidates)
    computed_at = payload["computed_at"]
    redis_client.setex(CANDIDATES_CACHE_KEY, CANDIDATES_MAX_STALE_SECONDS, json.dumps(payload))
    # Written after the main payload, deliberately - see CANDIDATES_STAMP_KEY.
    redis_client.setex(CANDIDATES_STAMP_KEY, CANDIDATES_MAX_STALE_SECONDS, computed_at)

    candidates = _deserialize_candidates(payload["candidates"])
    # This call just built the canonical copy for this cache generation -
    # prime this process's memo with it directly instead of making the very
    # next request pay to re-fetch and re-parse what's already in hand.
    _local_candidates_cache["stamp"] = computed_at
    _local_candidates_cache["candidates"] = candidates
    return candidates


def _background_refresh_candidates_cache() -> None:
    """Refresh the cache in the background, assuming the caller ALREADY
    acquired the refresh lock synchronously before spawning this thread.

    Opens its own DB session from BackgroundSessionLocal - a separate,
    dedicated tiny pool from the one request handling uses (see
    app/db/session.py) - for two reasons: a background thread can't safely
    reuse the original request's session, AND this thread runs on a raw
    threading.Thread rather than through anyio's threadpool, so it would
    otherwise be invisible to the request-concurrency limiter in
    app/main.py that's sized to exactly match the request-serving pool.
    Drawing from that same pool let this thread silently exceed what the
    limiter assumed was reserved, confirmed via a real
    `sqlalchemy.exc.TimeoutError: QueuePool limit ... reached` under load -
    see STUDY_NOTES.md §17. The lock is acquired by the caller rather than
    here deliberately: checking it in the request thread (one cheap Redis
    call) means we only ever spawn a thread for the single request that
    actually won the right to refresh, instead of spawning one per stale
    request and having all but one immediately exit. That wasted thread
    churn measurably hurt throughput under load."""
    db = BackgroundSessionLocal()
    try:
        _query_candidates_and_cache(db)
    finally:
        db.close()
        redis_client.delete(CANDIDATES_REFRESH_LOCK_KEY)


def _fetch_and_memoize(stamp: str) -> list[CandidateCampaign] | None:
    """Return this process's deserialized candidate list for the cache
    generation identified by `stamp`, fetching and parsing the full Redis
    payload only if this process doesn't already have it memoized.

    Returns None if the stamp exists but the full payload has already
    expired out of Redis - a narrow TTL-boundary race, since the two keys
    are set together but not atomically. Callers treat that exactly like a
    cache miss rather than assuming anything."""
    if _local_candidates_cache["stamp"] == stamp:
        return _local_candidates_cache["candidates"]

    cached = redis_client.get(CANDIDATES_CACHE_KEY)
    if cached is None:
        return None

    candidates = _deserialize_candidates(json.loads(cached)["candidates"])
    _local_candidates_cache["stamp"] = stamp
    _local_candidates_cache["candidates"] = candidates
    return candidates


def get_campaign_candidates(db: Session) -> list[CandidateCampaign]:
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

    Every hit first reads only the tiny CANDIDATES_STAMP_KEY, not the full
    payload - and if this process already deserialized that exact stamp
    (see _local_candidates_cache), returns the memoized list with no
    further Redis calls or object construction at all. This is what
    actually fixed the throughput regression documented in
    STUDY_NOTES.md §14/§15: the earlier per-request rebuild was cheap in
    isolation but held the GIL long enough, on every single request, to
    cap concurrent throughput near serial.

    Returns:
        Campaigns passing the campaign-level checks, unfiltered by user.
    """
    stamp = redis_client.get(CANDIDATES_STAMP_KEY)

    if stamp is not None:
        candidates = _fetch_and_memoize(stamp)
        if candidates is not None:
            computed_at = datetime.fromisoformat(stamp)
            age_seconds = (datetime.now(timezone.utc) - computed_at).total_seconds()

            if age_seconds > CANDIDATES_FRESH_SECONDS and redis_client.set(
                CANDIDATES_REFRESH_LOCK_KEY, "1", nx=True, ex=CANDIDATES_REFRESH_LOCK_TTL_SECONDS
            ):
                threading.Thread(target=_background_refresh_candidates_cache, daemon=True).start()

            return candidates

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
        stamp = redis_client.get(CANDIDATES_STAMP_KEY)
        if stamp is not None:
            candidates = _fetch_and_memoize(stamp)
            if candidates is not None:
                return candidates

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


def _targeting_interest_ids(targeting: CandidateTargeting | AudienceTargeting) -> frozenset[uuid.UUID]:
    """Get a targeting row's interest ids as a set.

    CandidateTargeting (the production path) precomputes this once per cache
    generation, so this is a free attribute read. A real AudienceTargeting
    (tests, and any direct ORM use) has no such field, so the set is built
    on demand from its `interests` relationship - correct, just not free.
    """
    precomputed = getattr(targeting, "interest_ids", None)
    if precomputed is not None:
        return precomputed
    return frozenset(i.id for i in targeting.interests)


def matches_targeting(
    targeting: CandidateTargeting | AudienceTargeting,
    user: User,
    user_age: int,
    user_interest_ids: frozenset[uuid.UUID] | None = None,
) -> bool:
    """Check whether a single targeting row matches a specific user.

    Every field follows the same rule: null/empty means unrestricted on
    that dimension, otherwise the user must satisfy it. Interests use
    "any overlap counts" - a user only needs to share one interest with
    the campaign's targeted list, not match all of them.

    Args:
        targeting: The campaign's audience targeting rules - either the
            lightweight CandidateTargeting used in production (see
            get_campaign_candidates) or a real AudienceTargeting (as
            constructed directly in tests). Only attributes are read, so
            either works identically.
        user: The user being evaluated.
        user_age: The user's current age, precomputed by the caller (see
            compute_age) rather than derived here, since callers checking
            many campaigns against the same user shouldn't recompute it
            once per campaign.
        user_interest_ids: The user's interest ids as a set, precomputed by
            the caller for exactly the same reason as user_age - it's
            identical for every campaign checked in one auction. Optional
            purely so single-campaign callers (tests) can omit it; when
            omitted it's built here.

    Returns:
        True if the user satisfies every targeting restriction.
    """
    if user_interest_ids is None:
        user_interest_ids = frozenset(i.id for i in user.interests)

    if targeting.min_age is not None and user_age < targeting.min_age:
        return False
    if targeting.max_age is not None and user_age > targeting.max_age:
        return False
    if targeting.country is not None and targeting.country != user.country:
        return False
    if targeting.device_type is not None and targeting.device_type != user.device_type:
        return False

    targeting_interest_ids = _targeting_interest_ids(targeting)
    if targeting_interest_ids and not targeting_interest_ids & user_interest_ids:
        return False

    return True


def filter_eligible_campaigns(db: Session, user: User) -> list[CandidateCampaign]:
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
    # Built once here, not once per candidate - this is the same value for
    # every one of the ~2,200 campaigns checked below.
    user_interest_ids = frozenset(i.id for i in user.interests)
    candidates = get_campaign_candidates(db)
    return [
        campaign for campaign in candidates
        if campaign.targeting is None
        or matches_targeting(campaign.targeting, user, user_age, user_interest_ids)
    ]


def get_user_interest_weights(db: Session, user_id: uuid.UUID) -> dict[uuid.UUID, float]:
    """Real per-interest weights for one user, keyed by interest id.

    This is the READ side of Step 8b's preference-learning feedback loop
    (see STUDY_NOTES.md §22): scripts/consume_events.py's
    nudge_interests_from_click WRITES this same weight column every time
    the user clicks something, and score_campaign (below) is what
    actually makes those writes matter - an interest this user has
    engaged with repeatedly now outscores one they merely happen to share
    with a campaign but have never clicked on.

    One query, meant to be called ONCE per auction request (see
    run_auction) and the resulting dict threaded through to both
    pick_winner and record_win - not once per candidate campaign, which
    would repeat the exact same result ~2,200 times for no reason (the
    same lesson as user_age/user_interest_ids being hoisted once in
    filter_eligible_campaigns - see §19).

    Returns:
        {interest_id: weight}, covering only interests this user actually
        has a row for - an interest with no row (never seeded, never
        nudged into existence by a click) simply isn't a key here, not a
        0.0 entry.
    """
    rows = db.execute(
        select(user_interests.c.interest_id, user_interests.c.weight).where(
            user_interests.c.user_id == user_id
        )
    ).all()
    return {row.interest_id: row.weight for row in rows}


def score_campaign(
    campaign: CandidateCampaign | Campaign,
    user: User,
    user_interest_weights: dict[uuid.UUID, float] | None = None,
) -> float:
    """Score how well a campaign matches a user, for ranking purposes.

    Deliberately kept as its own function, separate from filtering and
    auction mechanics, so a trained model's prediction can replace this
    scoring rule later without touching how eligibility or winner
    selection work.

    Args:
        campaign: An already-eligible campaign (see filter_eligible_campaigns) -
            either the lightweight CandidateCampaign used in production or
            a real Campaign (as constructed directly in tests, or as
            re-fetched in record_win before writing). Only attributes are
            read, so either works identically.
        user: The user being scored against.
        user_interest_weights: This user's real, persisted per-interest
            weights (see get_user_interest_weights) - an interest nudged
            up by repeated clicks (Step 8b) counts for MORE here than one
            the user merely happens to share with the campaign but has
            never engaged with. Falls back to a flat weight of 1.0 for
            every interest in `user.interests` when omitted - this
            function's original plain-overlap-counting behavior,
            preserved for direct/test callers that don't have real
            weight data and don't need it (every existing test keeps
            passing unmodified via this fallback).

    Returns:
        A baseline of 1.0 (so even broad, untargeted campaigns can still
        occasionally win) plus the SUM of this user's weight for every
        interest the campaign's targeting shares with the user - not just
        a count of how many matched. Eligibility (matches_targeting) is
        unaffected by weight and stays a plain yes/no on the same
        membership check as before; weight only ever changes the ODDS
        among campaigns that are already eligible, never whether one is
        eligible at all.
    """
    targeting = campaign.targeting
    if targeting is None:
        return 1.0

    targeting_interest_ids = _targeting_interest_ids(targeting)
    if not targeting_interest_ids:
        return 1.0

    if user_interest_weights is None:
        user_interest_weights = {i.id: 1.0 for i in user.interests}

    matched_weight = sum(
        user_interest_weights[interest_id]
        for interest_id in targeting_interest_ids
        if interest_id in user_interest_weights
    )
    return 1.0 + matched_weight


def pick_winner(
    eligible_campaigns: list[CandidateCampaign],
    user: User,
    user_interest_weights: dict[uuid.UUID, float] | None = None,
) -> CandidateCampaign | None:
    """Pick a winning campaign via weighted-random selection.

    Deliberately not a hard "highest score always wins" - a campaign's
    odds are proportional to its score, so a strong match usually but not
    always wins, and broad/low-score campaigns still get a real, if
    smaller, chance. This function has no side effects (it doesn't touch
    the database itself - see user_interest_weights below), so it's safe
    to call repeatedly for testing/inspection without accidentally
    recording wins that never really happened - see record_win for the
    actual side-effecting step.

    Args:
        eligible_campaigns: Campaigns already filtered as eligible for this user.
        user: The user being auctioned to, passed through to score_campaign.
        user_interest_weights: This user's real per-interest weights (see
            get_user_interest_weights), fetched once by the caller (see
            run_auction) - not fetched here, so this function still never
            touches the database itself. Omitted (None) falls back to
            score_campaign's plain-overlap-counting behavior - what every
            existing test here still exercises, unmodified.

    Returns:
        The winning campaign, or None if eligible_campaigns is empty (a
        "no fill" - no ad to show this user right now).
    """
    if not eligible_campaigns:
        return None

    scores = [score_campaign(c, user, user_interest_weights) for c in eligible_campaigns]
    return random.choices(eligible_campaigns, weights=scores, k=1)[0]

def record_win(
    db: Session,
    campaign: CandidateCampaign,
    user: User,
    user_interest_weights: dict[uuid.UUID, float] | None = None,
) -> Impression:
    """Record that a campaign won an auction: charge it for the win and
    log an impression capturing the full decision-time context.

    Only ever increments spent - budget is the campaign's fixed original
    allocation and should never be modified after creation, so "remaining
    budget" stays a computed value (budget - spent) rather than something
    stored and mutated directly. The impression snapshots the user's
    attributes and interests as they are right now, since user interests
    (and now their weights - see Step 8b, STUDY_NOTES.md §21/§22) mutate
    over time - without this snapshot, this historical record would
    silently drift from what was actually true at decision time.

    Args:
        db: Active database session.
        campaign: The campaign that won and should be charged - the
            lightweight CandidateCampaign returned by pick_winner, never
            session-attached, so it can only be used for its `.id` here.
        user: The user the auction was run for.
        user_interest_weights: The SAME dict passed to the pick_winner
            call that chose this campaign (see run_auction) - deliberately
            reused, not re-fetched, so the `score` persisted onto the
            Impression row below always matches what actually decided the
            winner. Re-fetching here instead would risk a subtle
            inconsistency: a click landing between pick_winner and
            record_win (vanishingly unlikely in one request, but a real
            possibility once fully async) could change the weights
            mid-request, making the logged score describe a decision that
            wasn't actually the one made.

    Returns:
        The newly created Impression row.
    """
    # `campaign` is a lightweight CandidateCampaign (from
    # get_campaign_candidates/pick_winner), never session-attached, but it
    # already carries its targeting and interest ids in memory from the
    # candidate cache - so scoring it directly costs nothing. Scoring a
    # re-fetched ORM Campaign instead would lazy-load `targeting` and then
    # `targeting.interests`: two round trips for data already in hand.
    score = score_campaign(campaign, user, user_interest_weights)

    # Charge the win with a database-side increment, NOT a Python-side one.
    # `campaign.spent += COST_PER_WIN` reads the current value into this
    # process, adds to it here, and writes the result back - so two workers
    # that win this same campaign concurrently both read the same starting
    # value, both write the same result, and one charge silently vanishes
    # (a lost update). Letting Postgres evaluate `spent + 0.50` inside the
    # UPDATE makes the read and the write one atomic, row-locked operation,
    # so concurrent wins queue behind each other and every charge lands.
    #
    # This also removes the SELECT that loading a session-attached Campaign
    # used to require: nothing here needs any of the row's other columns.
    #
    # Note what this does NOT do: it doesn't enforce the budget ceiling.
    # Eligibility (spent + COST_PER_WIN <= budget) is checked against the
    # candidate cache, which is up to CANDIDATES_MAX_STALE_SECONDS old, so
    # a campaign can still be charged slightly past its budget. That's a
    # separate concern from losing charges outright, and the fix for it is
    # a conditional UPDATE whose rowcount decides whether the win counts.
    db.execute(
        update(Campaign)
        .where(Campaign.id == campaign.id)
        .values(spent=Campaign.spent + COST_PER_WIN)
    )

    impression = Impression(
        user_id=user.id,
        campaign_id=campaign.id,
        occurred_at=datetime.now(timezone.utc),
        user_age=compute_age(user.birthdate),
        user_country=user.country,
        user_device_type=user.device_type,
        score=score,
        interests=list(user.interests),
    )
    db.add(impression)
    db.commit()
    # No db.refresh() here: SessionLocal sets expire_on_commit=False, so
    # every attribute the caller reads (notably `id`) is already populated
    # in memory. Refreshing would be a third round trip for data we wrote.
    return impression