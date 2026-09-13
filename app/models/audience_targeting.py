from app.db.base import Base
from sqlalchemy.orm import Mapped, mapped_column
import enum
from sqlalchemy import Uuid, ForeignKey, Enum as SqlEnum, Integer, String
from uuid import UUID, uuid4

class DeviceType(str, enum.Enum):
    DESKTOP = "desktop"
    MOBILE = "mobile"
    TABLET = "tablet"

class AudienceTargeting(Base):
    __tablename__ = "audience_targeting"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    campaign_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("campaigns.id", ondelete="CASCADE"), unique=True, nullable=False)
    device_type: Mapped[DeviceType | None] = mapped_column(
        SqlEnum(DeviceType, values_callable=lambda enum_cls: [e.value for e in enum_cls]),
        nullable = True,
    )
    min_age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    country: Mapped[str | None] = mapped_column(String, nullable=True)

