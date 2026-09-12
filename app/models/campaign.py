import uuid
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base
from sqlalchemy import String, Uuid, ForeignKey, Numeric, DateTime, Enum as SqlEnum
from decimal import Decimal
from datetime import datetime
import enum

class CampaignStatus(str, enum.Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    ENDED = "ended"

class Campaign(Base):
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

