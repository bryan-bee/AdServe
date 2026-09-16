import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Conversion(Base):
    """A user completing the advertiser's desired action after a click.
    Not unique on click_id - the same click can lead to more than one."""

    __tablename__ = "conversions"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    click_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("clicks.id", ondelete="CASCADE"), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
