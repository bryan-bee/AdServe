import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Click(Base):
    """A user clicking on a specific impression. Not unique on
    impression_id - the same impression can be clicked more than once."""

    __tablename__ = "clicks"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Indexed for the same reason as impressions' foreign keys - see §28.
    impression_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("impressions.id", ondelete="CASCADE"), nullable=False, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Flagged by the timing heuristic in app/api/routes/impressions.py as
    # implausibly fast after its impression. Stored rather than only
    # counted in Prometheus so it survives restarts and stays queryable
    # for analytics - the click is still recorded either way, deliberately
    # (see STUDY_NOTES.md §27 for why flagging beats blocking here).
    suspicious: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
