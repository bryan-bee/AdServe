import uuid

from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base
from sqlalchemy import String, Uuid


class Advertiser(Base):
    """An organization that runs ad campaigns. Owns zero or more Campaigns."""

    __tablename__ = "advertisers"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

