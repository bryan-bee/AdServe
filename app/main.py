from fastapi import FastAPI

from app.api.routes.health import router as health_router
from app.core.config import settings
from app.api.routes.advertisers import router as advertisers_router


app = FastAPI(title=settings.app_name)

app.include_router(health_router)
app.include_router(advertisers_router, prefix="/advertisers", tags=["advertisers"])
