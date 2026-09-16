import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ClickRead(BaseModel):
    """Response shape for a recorded click."""

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    impression_id: uuid.UUID
    occurred_at: datetime
