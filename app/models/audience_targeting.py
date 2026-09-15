from app.db.base import Base
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import Uuid, ForeignKey, Enum as SqlEnum, Integer, String
from uuid import UUID, uuid4
from app.models.enums import DeviceType
from sqlalchemy import Table, Column
from sqlalchemy.orm import relationship
from app.models.interest import Interest


targeting_interests = Table(
        "targeting_interests",
        Base.metadata,
        Column("targeting_id", Uuid, ForeignKey("audience_targeting.id", ondelete="CASCADE"), primary_key=True),
        Column("interest_id", Uuid, ForeignKey("interests.id", ondelete="CASCADE"), primary_key=True),
    )


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
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    interests: Mapped[list[Interest]] = relationship(secondary=targeting_interests)
