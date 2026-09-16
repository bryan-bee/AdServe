from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

engine = create_engine(settings.database_url, pool_size=20, max_overflow=30)

SessionLocal = sessionmaker(engine)

def get_db():
    """FastAPI dependency (use via `Depends(get_db)`) that opens a session
    per request and always closes it afterward, success or failure.
    Standalone scripts (seed.py etc.) don't use this - they call
    SessionLocal() directly, since there's no per-request lifecycle to
    manage."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()