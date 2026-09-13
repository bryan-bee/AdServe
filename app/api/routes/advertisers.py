from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.advertiser import Advertiser
from app.schemas.advertiser import AdvertiserRead

router = APIRouter()

@router.get("", response_model=list[AdvertiserRead])
def list_advertisers(db: Session = Depends(get_db)):
    return db.query(Advertiser).all()
