from pydantic import BaseModel, ConfigDict
from uuid import UUID 
from app.models.audience_targeting import DeviceType

class AudienceTargetingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    campaign_id: UUID
    device_type: DeviceType | None = None
    min_age: int | None = None
    max_age: int | None = None
    country: str | None = None

class AudienceTargetingCreate(BaseModel):
    device_type: DeviceType | None = None
    min_age: int | None = None
    max_age: int | None = None
    country: str | None = None