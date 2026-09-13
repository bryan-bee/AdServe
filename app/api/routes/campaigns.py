from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

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
    return db.query(Campaign).all()

@router.post("", response_model = CampaignRead, status_code=201)
def create_campaign(payload: CampaignCreate, db: Session = Depends(get_db)):
    advertiser = db.get(Advertiser, payload.advertiser_id)
    if advertiser is None:
        raise HTTPException(status_code=404, detail="Advertiser not found")

    new_campaign = Campaign(
        advertiser_id = payload.advertiser_id, 
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
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    targeting = db.query(AudienceTargeting).filter(AudienceTargeting.campaign_id == campaign_id).first()
    if targeting is None:
        raise HTTPException(status_code=404, detail=f"Audience Targeting for campaign {campaign_id} not found")
    return targeting


@router.post("/{campaign_id}/targeting", response_model = AudienceTargetingRead, status_code=201)
def create_targeting(payload: AudienceTargetingCreate, campaign_id: uuid.UUID, db: Session = Depends(get_db)):
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
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

