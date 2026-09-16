import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ConversionRead(BaseModel):
    """Response shape for a recorded conversion."""

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    click_id: uuid.UUID
    occurred_at: datetime
