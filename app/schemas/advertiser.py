from pydantic import BaseModel, ConfigDict
import uuid 

class AdvertiserCreate(BaseModel):
    """Request body for POST /advertisers - only what the caller provides."""

    name: str


class AdvertiserRead(BaseModel):
    """Response shape for an advertiser, including server-generated fields
    like `id`. `from_attributes=True` lets Pydantic build this directly
    from a SQLAlchemy Advertiser object's attributes, rather than
    requiring a plain dict."""

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str