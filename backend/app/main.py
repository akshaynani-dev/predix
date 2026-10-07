"""PREDIX FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging_config import configure_logging
from app.api.health import router as health_router
from app.api.video import router as video_router
from app.api.analysis import router as analysis_router
from app.api.zones import router as zones_router
from app.api.history import router as history_router
from app.database.instance import repository

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize persistent storage and required file directories."""
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.analysis_dir.mkdir(parents=True, exist_ok=True)
    repository.initialize()
    yield


app = FastAPI(
    title=f"{settings.SERVICE_NAME} API",
    description="Real-Time Predictive Intelligence — Backend Service",
    version=settings.SERVICE_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS — allow frontend dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

# Routers
app.include_router(health_router, prefix="/api")
app.include_router(video_router, prefix="/api")
app.include_router(analysis_router, prefix="/api")
app.include_router(zones_router, prefix="/api")
app.include_router(history_router, prefix="/api")


@app.get("/", tags=["Root"])
async def root() -> dict:
    return {"message": f"{settings.SERVICE_NAME} backend is running."}
