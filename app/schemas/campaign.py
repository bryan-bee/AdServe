from pydantic import BaseModel, ConfigDict
from uuid import UUID 
from decimal import Decimal
from app.models.campaign import CampaignStatus
from datetime import datetime


class CampaignCreate(BaseModel):
    """Request body for POST /campaigns.

    Deliberately has NO advertiser_id: which advertiser this campaign
    belongs to is derived from the authenticated API key, never from the
    request body. Letting a caller name the owner is exactly the
    authorization hole that authentication exists to close - see
    STUDY_NOTES.md §24.2.
    """

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