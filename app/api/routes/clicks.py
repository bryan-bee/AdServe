import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.click import Click
from app.models.conversion import Conversion
from app.schemas.conversion import ConversionRead

router = APIRouter()


@router.post("/{click_id}/conversions", response_model=ConversionRead, status_code=201)
def record_conversion(click_id: uuid.UUID, db: Session = Depends(get_db)):
    """Record that a specific click led to a conversion.

    Args:
        click_id: The click that converted.

    Returns:
        The newly created conversion.

    Raises:
        HTTPException: 404 if the click doesn't exist.
    """
    click = db.get(Click, click_id)
    if click is None:
        raise HTTPException(status_code=404, detail="Click not found")

    conversion = Conversion(click_id=click_id, occurred_at=datetime.now(timezone.utc))
    db.add(conversion)
    db.commit()
    db.refresh(conversion)
    return conversion
