from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.advertiser import Advertiser
from app.schemas.advertiser import AdvertiserRead, AdvertiserCreate

router = APIRouter()

@router.get("", response_model=list[AdvertiserRead])
def list_advertisers(db: Session = Depends(get_db)):
    return db.query(Advertiser).all()

@router.post("", response_model=AdvertiserRead, status_code=201)
def create_advertiser(payload: AdvertiserCreate, db: Session = Depends(get_db)):
    new_advertiser = Advertiser(name = payload.name)
    db.add(new_advertiser)
    db.commit()
    return new_advertiser