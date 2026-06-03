# #country-guessing-game-backend/app/main.py
# from contextlib import asynccontextmanager
# from fastapi import FastAPI
# from fastapi.middleware.cors import CORSMiddleware

# from app.core.config import settings
# from app.api.v1.router import api_router
# from app.api.v1.endpoints.ws import router as ws_router
# from app.db.base import engine, Base
# from app.db.redis import get_redis
# import app.models  # noqa


# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     # Redis
#     redis = get_redis()
#     await redis.ping()
#     print("✅ Redis connected")

#     # Database — always create tables if they don't exist
#     async with engine.begin() as conn:
#         await conn.run_sync(Base.metadata.create_all)
#     print("✅ Database tables ready")

#     yield

#     await engine.dispose()
#     await redis.aclose()
#     print("👋 Shutdown complete")


# app = FastAPI(
#     title=settings.app_name,
#     version="0.1.0",
#     docs_url="/docs" if not settings.is_production else None,
#     redoc_url="/redoc" if not settings.is_production else None,
#     lifespan=lifespan,
# )

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=settings.allowed_origins_list,
#     allow_origin_regex=r"https?://.*",
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )
# # If you want later, set ALLOWED_ORIGINS 
# # to your actual frontend origin(s) and remove the regex fallback for stricter security.

# # REST API routes
# app.include_router(api_router)

# # WebSocket routes
# app.include_router(ws_router)


# @app.get("/health", tags=["health"])
# async def health():
#     return {"status": "ok", "env": settings.app_env}


#country-guessing-game-backend/app/main.py
#Below  works good.
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.v1.router import api_router
from app.api.v1.endpoints.ws import router as ws_router
from app.db.base import engine, Base
from app.db.redis import get_redis
import app.models  # noqa


async def _cleanup_orphaned_redis_keys(redis):
    """
    On startup, remove all matchmaking queue entries and active-match keys.
    These are ephemeral — they're meaningless after a restart because all
    WebSocket connections are gone and no matches are in progress.
    Match results are in PostgreSQL; only queue state lives purely in Redis.
    """
    # Clear the matchmaking queue
    await redis.delete("matchmaking:queue")

    # Clear all user active-match keys
    async for key in redis.scan_iter("user:active_match:*"):
        await redis.delete(key)

    # Clear all queue metadata
    async for key in redis.scan_iter("queue:mode:*"):
        await redis.delete(key)
    async for key in redis.scan_iter("queue:joined:*"):
        await redis.delete(key)
    async for key in redis.scan_iter("queue:match_found:*"):
        await redis.delete(key)

    print("✅ Orphaned Redis queue/match keys cleared")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Redis
    redis = get_redis()
    await redis.ping()
    print("✅ Redis connected")

    # Clean up stale keys on every startup
    await _cleanup_orphaned_redis_keys(redis)

    # Database — always create tables if they don't exist
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
    allow_origins=settings.allowed_origins_list,
    allow_origin_regex=r"https?://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# If you want later, set ALLOWED_ORIGINS 
# to your actual frontend origin(s) and remove the regex fallback for stricter security.

# REST API routes
app.include_router(api_router)

# WebSocket routes
app.include_router(ws_router)


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok", "env": settings.app_env}