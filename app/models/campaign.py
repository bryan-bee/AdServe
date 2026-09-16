import uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base
from sqlalchemy import String, Uuid, ForeignKey, Numeric, DateTime, Enum as SqlEnum
from decimal import Decimal
from datetime import datetime
from sqlalchemy import text
from typing import TYPE_CHECKING


import enum
if TYPE_CHECKING:
    from app.models.audience_targeting import AudienceTargeting
    
class CampaignStatus(str, enum.Enum):
    """A campaign's own advertiser-controlled state. The auction also
    independently checks the campaign's date window and budget - a
    campaign can still be excluded even when status says ACTIVE, e.g. if
    its end_date has already passed."""

    ACTIVE = "active"
    PAUSED = "paused"
    ENDED = "ended"

class Campaign(Base):
    """An advertiser's ad campaign - a budget, a date window, and a status.

    `budget` is the fixed total allocation and is never modified after
    creation; `spent` tracks usage against it, so remaining budget is
    always `budget - spent` rather than a separately stored value.
    """

    __tablename__ = "campaigns"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    advertiser_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("advertisers.id", ondelete="RESTRICT"), nullable=False)
    budget: Mapped[Decimal] = mapped_column(Numeric(12,4), nullable=False)
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[CampaignStatus] = mapped_column(
        SqlEnum(CampaignStatus, values_callable=lambda enum_cls: [e.value for e in enum_cls]),
        nullable=False,
    )
    spent: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=Decimal("0"), server_default=text("0"))
    targeting: Mapped["AudienceTargeting"] = relationship(back_populates="campaign", uselist=False)


