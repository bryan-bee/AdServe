from datetime import date, datetime, timezone
import uuid
from app.models.audience_targeting import AudienceTargeting
from app.models.enums import DeviceType
from app.models.interest import Interest
from app.models.user import User
from app.services.auction import matches_targeting, score_campaign, pick_winner, compute_age
from decimal import Decimal
from app.models.campaign import Campaign, CampaignStatus

def test_compute_age_before_birthday_this_year():
    birthdate = date(2000, 3, 15)
    today = date(2024, 3, 1)
    assert compute_age(birthdate, today) == 23


def test_compute_age_after_birthday_this_year():
    birthdate = date(2000, 3, 15)
    today = date(2024, 4, 1)
    assert compute_age(birthdate, today) == 24


def make_interest(name):
    return Interest(id=uuid.uuid4(), name=name)


def test_matches_targeting_fully_open():
    targeting = AudienceTargeting()
    user = User(country="US", device_type=DeviceType.MOBILE, interests=[])
    assert matches_targeting(targeting, user, user_age=30) is True


def test_matches_targeting_fails_below_min_age():
    targeting = AudienceTargeting(min_age=21)
    user = User(country="US", device_type=DeviceType.MOBILE, interests=[])
    assert matches_targeting(targeting, user, user_age=18) is False


def test_matches_targeting_passes_at_min_age():
    targeting = AudienceTargeting(min_age=21)
    user = User(country="US", device_type=DeviceType.MOBILE, interests=[])
    assert matches_targeting(targeting, user, user_age=21) is True


def test_matches_targeting_fails_wrong_country():
    targeting = AudienceTargeting(country="US")
    user = User(country="CA", device_type=DeviceType.MOBILE, interests=[])
    assert matches_targeting(targeting, user, user_age=30) is False


def test_matches_targeting_fails_wrong_device():
    targeting = AudienceTargeting(device_type=DeviceType.DESKTOP)
    user = User(country="US", device_type=DeviceType.MOBILE, interests=[])
    assert matches_targeting(targeting, user, user_age=30) is False


def test_matches_targeting_fails_no_interest_overlap():
    gaming = make_interest("gaming")
    cooking = make_interest("cooking")
    targeting = AudienceTargeting(interests=[gaming])
    user = User(country="US", device_type=DeviceType.MOBILE, interests=[cooking])
    assert matches_targeting(targeting, user, user_age=30) is False


def test_matches_targeting_passes_with_interest_overlap():
    gaming = make_interest("gaming")
    cooking = make_interest("cooking")
    targeting = AudienceTargeting(interests=[gaming, cooking])
    user = User(country="US", device_type=DeviceType.MOBILE, interests=[cooking])
    assert matches_targeting(targeting, user, user_age=30) is True


def test_matches_targeting_open_interests_matches_anyone():
    targeting = AudienceTargeting(interests=[])
    user = User(country="US", device_type=DeviceType.MOBILE, interests=[])
    assert matches_targeting(targeting, user, user_age=30) is True


def make_campaign(interests=None):
    targeting = AudienceTargeting(interests=interests or [])
    return Campaign(
        budget=Decimal("100"),
        spent=Decimal("0"),
        start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end_date=datetime(2024, 12, 31, tzinfo=timezone.utc),
        status=CampaignStatus.ACTIVE,
        targeting=targeting,
    )


def test_score_campaign_baseline_with_no_targeting():
    campaign = make_campaign()
    user = User(country="US", device_type=DeviceType.MOBILE, interests=[])
    assert score_campaign(campaign, user) == 1


def test_score_campaign_adds_overlap_count():
    gaming = make_interest("gaming")
    cooking = make_interest("cooking")
    reading = make_interest("reading")
    campaign = make_campaign(interests=[gaming, cooking])
    user = User(country="US", device_type=DeviceType.MOBILE, interests=[cooking, reading])
    assert score_campaign(campaign, user) == 2  # baseline 1 + 1 overlap (cooking)


def test_pick_winner_returns_none_for_empty_list():
    assert pick_winner([], user=None) is None


def test_pick_winner_returns_the_only_campaign():
    campaign = make_campaign()
    user = User(country="US", device_type=DeviceType.MOBILE, interests=[])
    assert pick_winner([campaign], user) is campaign


def test_pick_winner_favors_higher_score():
    gaming = make_interest("gaming")
    low_score_campaign = make_campaign(interests=[])
    high_score_campaign = make_campaign(interests=[gaming])
    user = User(country="US", device_type=DeviceType.MOBILE, interests=[gaming])

    wins = {id(low_score_campaign): 0, id(high_score_campaign): 0}
    for _ in range(1000):
        winner = pick_winner([low_score_campaign, high_score_campaign], user)
        wins[id(winner)] += 1

    assert wins[id(high_score_campaign)] > wins[id(low_score_campaign)]