import uuid

from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base
from sqlalchemy import String, Uuid


class Advertiser(Base):
    """An organization that runs ad campaigns. Owns zero or more Campaigns."""

    __tablename__ = "advertisers"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # SHA-256 of this advertiser's API key - never the key itself, which is
    # shown once at creation and then unrecoverable (see
    # app/core/security.py). Indexed because every authenticated request
    # looks an advertiser up by exactly this column. Nullable because the
    # ~5,000 advertisers seeded by scripts/seed.py predate authentication
    # entirely and have no key - they simply can't authenticate, which is
    # correct: they're simulation fixtures, not real accounts.
    api_key_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True, index=True
    )

