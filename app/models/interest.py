import uuid

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Uuid

from app.db.base import Base


class Interest(Base):
    __tablename__ = "interests"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
