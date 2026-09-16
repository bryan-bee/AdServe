import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Click(Base):
    """A user clicking on a specific impression. Not unique on
    impression_id - the same impression can be clicked more than once."""

    __tablename__ = "clicks"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    impression_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("impressions.id", ondelete="CASCADE"), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
