import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.click import Click
from app.models.impression import Impression
from app.schemas.click import ClickRead

router = APIRouter()


@router.post("/{impression_id}/clicks", response_model=ClickRead, status_code=201)
def record_click(impression_id: uuid.UUID, db: Session = Depends(get_db)):
    """Record that a specific impression was clicked.

    Args:
        impression_id: The impression that was clicked.

    Returns:
        The newly created click.

    Raises:
        HTTPException: 404 if the impression doesn't exist.
    """
    impression = db.get(Impression, impression_id)
    if impression is None:
        raise HTTPException(status_code=404, detail="Impression not found")

    click = Click(impression_id=impression_id, occurred_at=datetime.now(timezone.utc))
    db.add(click)
    db.commit()
    db.refresh(click)
    return click
