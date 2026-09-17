from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.security import generate_api_key, hash_api_key
from app.db.session import get_db
from app.models.advertiser import Advertiser
from app.schemas.advertiser import AdvertiserCreate, AdvertiserCreated, AdvertiserRead

router = APIRouter()

@router.get("", response_model=list[AdvertiserRead])
def list_advertisers(db: Session = Depends(get_db)):
    """List every advertiser.

    Deliberately unauthenticated and deliberately returning AdvertiserRead
    (which has no key field) rather than AdvertiserCreated - see
    STUDY_NOTES.md §24.1 for why read endpoints stay open here.

    Returns:
        All `Advertiser` rows currently in the database, in no guaranteed order.
    """
    return db.query(Advertiser).all()

@router.post("", response_model=AdvertiserCreated, status_code=201)
def create_advertiser(payload: AdvertiserCreate, db: Session = Depends(get_db)):
    """Create a new advertiser and issue its API key.

    Deliberately NOT authenticated: this is the sign-up step, and requiring
    an existing key to create your first account would be circular. Every
    endpoint that acts on an existing advertiser's behalf does require the
    key this returns.

    Args:
        payload: The advertiser's name.

    Returns:
        The newly created advertiser, including its generated `id` and -
        exactly once, never again - the plaintext `api_key`. Only a SHA-256
        hash of that key is stored server-side.
    """
    api_key = generate_api_key()
    new_advertiser = Advertiser(name=payload.name, api_key_hash=hash_api_key(api_key))
    db.add(new_advertiser)
    db.commit()

    # Built explicitly rather than returned as the ORM object: `api_key`
    # exists only in this function's memory and on the Advertiser row's
    # hash - there is no `new_advertiser.api_key` attribute for
    # from_attributes to read, by design.
    return AdvertiserCreated(id=new_advertiser.id, name=new_advertiser.name, api_key=api_key)
