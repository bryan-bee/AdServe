from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import require_advertiser
from app.db.session import get_db
from app.models.campaign import Campaign
from app.schemas.campaign import CampaignCreate, CampaignRead
from app.models.advertiser import Advertiser
from app.schemas.audience_targeting import AudienceTargetingCreate, AudienceTargetingRead
from app.models.audience_targeting import AudienceTargeting
import uuid


router = APIRouter()

@router.get("", response_model=list[CampaignRead])
def list_campaigns(db: Session = Depends(get_db)):
    """List every campaign.

    Returns:
        All `Campaign` rows currently in the database, in no guaranteed order.
    """
    return db.query(Campaign).all()

@router.post("", response_model = CampaignRead, status_code=201)
def create_campaign(
    payload: CampaignCreate,
    db: Session = Depends(get_db),
    advertiser: Advertiser = Depends(require_advertiser),
):
    """Create a new campaign, owned by the authenticated advertiser.

    Requires a valid `X-API-Key` header. The owning advertiser comes from
    that key, NOT from the request body - before authentication existed,
    this endpoint took an `advertiser_id` field and trusted it, so any
    caller could create campaigns under any advertiser's account and spend
    against a budget that wasn't theirs. There is no advertiser-existence
    check any more because there's nothing to check: an authenticated
    advertiser exists by definition.

    Args:
        payload: Budget, start/end dates, and status for the new campaign.
            Does not include targeting - see the separate
            `/campaigns/{campaign_id}/targeting` endpoints for that.

    Returns:
        The newly created campaign, including its generated `id`.

    Raises:
        HTTPException: 401 if the API key is missing or invalid.
    """
    new_campaign = Campaign(
        advertiser_id = advertiser.id,
        budget = payload.budget,
        start_date = payload.start_date,
        end_date = payload.end_date,
        status = payload.status
        )
    db.add(new_campaign)
    db.commit()
    return new_campaign


@router.get("/{campaign_id}/targeting", response_model = AudienceTargetingRead)
def get_targeting(campaign_id: uuid.UUID, db: Session = Depends(get_db)):
    """Get a campaign's audience targeting rules.

    Args:
        campaign_id: The campaign whose targeting to fetch.

    Returns:
        The campaign's `AudienceTargeting` row.

    Raises:
        HTTPException: 404 if the campaign doesn't exist, or 404 if it
            exists but has no targeting configured yet.
    """
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    targeting = db.query(AudienceTargeting).filter(AudienceTargeting.campaign_id == campaign_id).first()
    if targeting is None:
        raise HTTPException(status_code=404, detail=f"Audience Targeting for campaign {campaign_id} not found")
    return targeting


@router.post("/{campaign_id}/targeting", response_model = AudienceTargetingRead, status_code=201)
def create_targeting(
    payload: AudienceTargetingCreate,
    campaign_id: uuid.UUID,
    db: Session = Depends(get_db),
    advertiser: Advertiser = Depends(require_advertiser),
):
    """Set a campaign's audience targeting rules.

    Each campaign can have at most one targeting row - call this once per
    campaign, not to update an existing one. Every field is optional; a
    null field means "no restriction on that dimension" (e.g. a null
    `country` matches users in any country).

    Requires a valid `X-API-Key`, AND that the key's advertiser actually
    owns this campaign. Those are two genuinely different checks:
    authentication ("who are you?") is handled by require_advertiser,
    authorization ("are you allowed to touch THIS row?") has to be checked
    here, because knowing a caller is a real advertiser says nothing about
    whether this particular campaign is theirs. Skipping the second check
    would let any authenticated advertiser retarget a competitor's
    campaign - see STUDY_NOTES.md §24.2.

    Args:
        campaign_id: The campaign to attach targeting to.
        payload: Device type, age range, and country restrictions - any of
            which may be omitted.

    Returns:
        The newly created `AudienceTargeting` row.

    Raises:
        HTTPException: 401 if the API key is missing/invalid, 404 if the
            campaign doesn't exist OR belongs to a different advertiser
            (deliberately the same response - see below), or 409 if it
            already has targeting configured.
    """
    campaign = db.get(Campaign, campaign_id)
    # 404 rather than 403 for a campaign owned by someone else, on
    # purpose: a 403 would confirm that this campaign id exists, letting
    # an authenticated advertiser enumerate competitors' campaign ids by
    # watching which ones answer differently. "Not found" is the honest
    # answer from this caller's point of view.
    if campaign is None or campaign.advertiser_id != advertiser.id:
        raise HTTPException(status_code=404, detail="Campaign not found")
    targeting = db.query(AudienceTargeting).filter(AudienceTargeting.campaign_id == campaign_id).first()
    if targeting is not None:
        raise HTTPException(status_code=409, detail="Campaign's targeting already exists")
    new_targeting = AudienceTargeting(
    campaign_id = campaign_id,
    device_type = payload.device_type,
    min_age=payload.min_age,
    max_age=payload.max_age,
    country=payload.country,
    )
    db.add(new_targeting)
    db.commit()
    return new_targeting

