from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.campaign import Campaign
from app.schemas.campaign import CampaignCreate, CampaignRead
from app.models.advertiser import Advertiser

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


