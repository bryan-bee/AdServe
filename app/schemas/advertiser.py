from pydantic import BaseModel, ConfigDict
import uuid 

class AdvertiserCreate(BaseModel):
    """Request body for POST /advertisers - only what the caller provides."""

    name: str


class AdvertiserRead(BaseModel):
    """Response shape for an advertiser, including server-generated fields
    like `id`. `from_attributes=True` lets Pydantic build this directly
    from a SQLAlchemy Advertiser object's attributes, rather than
    requiring a plain dict."""

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str


class AdvertiserCreated(AdvertiserRead):
    """Response shape for POST /advertisers ONLY - the one and only time
    the plaintext API key is ever returned. Only its SHA-256 hash is
    stored (see app/core/security.py), so a caller who loses this value
    cannot recover it from the server; they would need a new advertiser.
    Deliberately a separate schema from AdvertiserRead so that GET
    /advertisers, which returns every advertiser, can never accidentally
    include a key field."""

    api_key: str