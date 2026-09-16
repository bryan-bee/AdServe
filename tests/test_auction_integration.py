from app.models.audience_targeting import AudienceTargeting
from app.models.campaign import Campaign
from app.models.user import User
from app.services.auction import COST_PER_WIN, filter_eligible_campaigns, record_win


def test_filter_eligible_campaigns_excludes_expired_campaign(db):
    user = db.query(User).filter(User.name == "Test User").one()

    # The seed data intentionally leaves this campaign's status as "active"
    # even though its end_date has already passed - the filter must catch
    # that from the live date check, not trust the stale status field.
    active_campaign = (
        db.query(Campaign)
        .join(AudienceTargeting)
        .filter(AudienceTargeting.min_age == 18)
        .one()
    )
    expired_campaign = (
        db.query(Campaign)
        .join(AudienceTargeting)
        .filter(AudienceTargeting.min_age.is_(None))
        .one()
    )

    eligible_ids = {c.id for c in filter_eligible_campaigns(db, user)}

    assert active_campaign.id in eligible_ids
    assert expired_campaign.id not in eligible_ids


def test_record_win_increments_spent(db):
    user = db.query(User).filter(User.name == "Test User").one()
    campaign = db.query(Campaign).first()
    before = campaign.spent

    impression = record_win(db, campaign, user)

    assert campaign.spent == before + COST_PER_WIN
    assert impression.user_id == user.id
    assert impression.campaign_id == campaign.id
