from pydantic import BaseModel, ConfigDict
import uuid 

class AdvertiserCreate(BaseModel):
    name: str


class AdvertiserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str