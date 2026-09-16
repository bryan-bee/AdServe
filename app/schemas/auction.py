import uuid

from pydantic import BaseModel


class AuctionRequest(BaseModel):
    user_id: uuid.UUID

class AuctionResponse(BaseModel):
    campaign_id: uuid.UUID
    advertiser_id: uuid.UUID
    