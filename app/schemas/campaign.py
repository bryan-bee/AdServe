from pydantic import BaseModel, ConfigDict
from uuid import UUID 
from decimal import Decimal
from app.models.campaign import CampaignStatus
from datetime import datetime


class CampaignCreate(BaseModel):
    advertiser_id: UUID
    budget: Decimal
    start_date: datetime
    end_date: datetime
    status: CampaignStatus = CampaignStatus.ACTIVE


class CampaignRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    advertiser_id: UUID
    budget: Decimal
    start_date: datetime
    end_date: datetime
    status: CampaignStatus