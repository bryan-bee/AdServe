"""API-key authentication for advertiser-facing write endpoints (Step 11).

Before this, the API had zero authentication: anyone who could reach the
server could create a campaign under ANY advertiser's id, which in a real
ad platform means spending someone else's budget. See STUDY_NOTES.md §24
for the full threat model and why different endpoint groups are protected
differently.
"""
import hashlib
import secrets

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.advertiser import Advertiser


def generate_api_key() -> str:
    """A fresh, random API key, shown to the caller exactly once (see
    create_advertiser) and never recoverable afterward - only its hash is
    stored. `token_urlsafe(32)` is 32 bytes (256 bits) of
    cryptographically-secure randomness, URL/header-safe."""
    return secrets.token_urlsafe(32)


def hash_api_key(api_key: str) -> str:
    """Hash an API key for storage and lookup.

    SHA-256, deliberately - NOT bcrypt/argon2, which this project uses
    nowhere but which would be the correct choice for a *password*. The
    difference is entropy, not paranoia: a password is short, human-chosen
    and guessable, so password hashing has to be deliberately SLOW to make
    brute-forcing expensive. An API key from generate_api_key() is 256
    bits of uniform randomness - there is no dictionary to try and no
    feasible brute-force regardless of how fast the hash is.

    A fast deterministic hash also buys something bcrypt can't: the same
    key always hashes to the same value, so authentication is a single
    indexed lookup (`WHERE api_key_hash = ...`) instead of fetching every
    advertiser and testing each one's salted hash in turn - which at 5,000+
    advertisers would be absurd on every authenticated request.
    """
    return hashlib.sha256(api_key.encode()).hexdigest()


def require_advertiser(
    x_api_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Advertiser:
    """FastAPI dependency: resolve the `X-API-Key` header to the advertiser
    it belongs to, or reject the request.

    Use via `advertiser: Advertiser = Depends(require_advertiser)` on any
    endpoint that acts on an advertiser's behalf. The returned Advertiser
    is the *authenticated* identity - endpoints derive ownership from it
    rather than trusting an id in the request body, which is the actual
    point of authentication here (see STUDY_NOTES.md §24.2).

    Raises:
        HTTPException: 401 if the header is missing or doesn't match any
            advertiser. Both cases return the same generic message on
            purpose - distinguishing "no key" from "wrong key" tells an
            attacker which half of their guess was right.
    """
    if x_api_key is None:
        raise HTTPException(status_code=401, detail="Missing or invalid API key")

    advertiser = (
        db.query(Advertiser)
        .filter(Advertiser.api_key_hash == hash_api_key(x_api_key))
        .first()
    )
    if advertiser is None:
        raise HTTPException(status_code=401, detail="Missing or invalid API key")

    return advertiser
