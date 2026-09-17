import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Table, Uuid, Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import DeviceType
from app.models.interest import Interest

impression_interests = Table(
    "impression_interests",
    Base.metadata,
    Column("impression_id", Uuid, ForeignKey("impressions.id", ondelete="CASCADE"), primary_key=True),
    Column("interest_id", Uuid, ForeignKey("interests.id", ondelete="CASCADE"), primary_key=True),
)


class Impression(Base):
    """One auction win, with full context frozen at decision time - the
    user's attributes and interests may change later, but this row always
    reflects what was true at the moment this specific impression happened."""

    __tablename__ = "impressions"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Deliberately NOT indexed, after measuring both sides - see §30.3.
    # §28 added indexes here expecting the analytics queries to need them;
    # measurement showed the dashboard's GROUP BY correctly ignores them
    # (it reads every row anyway), while they cost ~0.60ms of index
    # maintenance on EVERY impression insert - the single hottest write in
    # the system. Their only real beneficiaries would be per-campaign
    # drill-down endpoints that don't exist and user/campaign deletes that
    # never happen (seed.py uses TRUNCATE, which bypasses FK checks), so
    # they were dropped again in migration `dcf2afa14820`. Re-add them the day a
    # query actually needs them, not before.
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    campaign_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("campaigns.id", ondelete="RESTRICT"), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    user_age: Mapped[int] = mapped_column(Integer, nullable=False)
    user_country: Mapped[str] = mapped_column(String(2), nullable=False)
    user_device_type: Mapped[DeviceType] = mapped_column(
        SqlEnum(DeviceType, values_callable=lambda enum_cls: [e.value for e in enum_cls]),
        nullable=False,
    )
    # Float, not Integer: since Step 8b (STUDY_NOTES.md §22), score_campaign
    # sums real per-interest weights (nudged by clicks, not always whole
    # numbers once decay - see scripts/consume_events.py - has been
    # applied) rather than counting whole matched interests.
    score: Mapped[float] = mapped_column(Float, nullable=False)
    interests: Mapped[list[Interest]] = relationship(secondary=impression_interests)
