import uuid

from pydantic import BaseModel


class AuctionRequest(BaseModel):
    """Which user to run the auction for. Attributes (age, interests, etc.)
    are looked up from the database, not sent in the request."""

    user_id: uuid.UUID

class AuctionResponse(BaseModel):
    """The winning campaign, returned on a 200. See app/api/routes/auction.py
    for the 204 "no fill" case when no campaign is eligible."""

    campaign_id: uuid.UUID
    advertiser_id: uuid.UUID
    impression_id: uuid.UUID
    