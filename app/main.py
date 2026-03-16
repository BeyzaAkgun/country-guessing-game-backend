#main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.v1.router import api_router
from app.api.v1.endpoints.ws import router as ws_router
from app.db.base import engine, Base
from app.db.redis import get_redis
import app.models  # noqa


@asynccontextmanager
async def lifespan(app: FastAPI):
    redis = get_redis()
    await redis.ping()
    print("✅ Redis connected")

    if settings.debug:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        print("✅ Database tables ready")

    yield

    await engine.dispose()
    await redis.aclose()
    print("👋 Shutdown complete")


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# REST API routes
app.include_router(api_router)

# WebSocket routes — registered directly on app, not under /api/v1
app.include_router(ws_router)


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok", "env": settings.app_env}