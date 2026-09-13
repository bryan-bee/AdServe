from fastapi import FastAPI

from app.api.routes.health import router as health_router
from app.core.config import settings
from app.api.routes.advertisers import router as advertisers_router
from app.api.routes.campaigns import router as campaigns_router

app = FastAPI(title=settings.app_name)

app.include_router(health_router)
app.include_router(advertisers_router, prefix="/advertisers", tags=["advertisers"])
app.include_router(campaigns_router, prefix="/campaigns", tags=["campaigns"])
