# leaderboard.py
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID

from app.db.base import get_db
from app.db.redis import get_redis
from app.models.user import User, Profile
from app.core.dependencies import get_current_user

router = APIRouter(prefix="/leaderboard", tags=["leaderboard"])


@router.get("/global", response_model=list[dict])
async def global_leaderboard(
    limit: int = Query(default=50, le=100),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    """Top players by rank points."""
    # Get top players from Redis sorted set (highest score first)
    entries = await redis.zrevrange("leaderboard:global", 0, limit - 1, withscores=True)

    if not entries:
        return []

    result = []
    for rank, (user_id_bytes, score) in enumerate(entries, start=1):
        user_id = user_id_bytes.decode() if isinstance(user_id_bytes, bytes) else user_id_bytes

        # Load user + profile from DB
        user_result = await db.execute(
            select(User).where(User.id == UUID(user_id))
        )
        user = user_result.scalar_one_or_none()
        if not user:
            continue

        profile_result = await db.execute(
            select(Profile).where(Profile.user_id == UUID(user_id))
        )
        profile = profile_result.scalar_one_or_none()
        if not profile:
            continue

        result.append({
            "rank": rank,
            "user_id": user_id,
            "username": user.username,
            "rank_tier": profile.rank_tier,
            "rank_points": int(score),
            "wins": profile.wins,
            "losses": profile.losses,
            "win_rate": profile.win_rate,
            "best_streak": profile.best_streak,
            "avatar_url": profile.avatar_url,
        })

    return result


@router.get("/me", response_model=dict)
async def my_rank(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    """Get the current user's rank position."""
    user_id = str(current_user.id)

    rank = await redis.zrevrank("leaderboard:global", user_id)
    score = await redis.zscore("leaderboard:global", user_id)

    if rank is None:
        return {
            "rank": None,
            "rank_points": 0,
            "message": "Play a match to appear on the leaderboard",
        }

    profile_result = await db.execute(
        select(Profile).where(Profile.user_id == current_user.id)
    )
    profile = profile_result.scalar_one_or_none()

    total_players = await redis.zcard("leaderboard:global")

    return {
        "rank": rank + 1,
        "total_players": total_players,
        "rank_points": int(score),
        "rank_tier": profile.rank_tier if profile else "Bronze Explorer",
        "wins": profile.wins if profile else 0,
        "losses": profile.losses if profile else 0,
        "win_rate": profile.win_rate if profile else 0.0,
    }


@router.get("/around-me", response_model=list[dict])
async def leaderboard_around_me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    """Get 5 players above and below the current user."""
    user_id = str(current_user.id)
    rank = await redis.zrevrank("leaderboard:global", user_id)

    if rank is None:
        return []

    start = max(0, rank - 5)
    end = rank + 5

    entries = await redis.zrevrange("leaderboard:global", start, end, withscores=True)

    result = []
    for i, (uid_bytes, score) in enumerate(entries):
        uid = uid_bytes.decode() if isinstance(uid_bytes, bytes) else uid_bytes
        actual_rank = start + i + 1

        user_result = await db.execute(select(User).where(User.id == UUID(uid)))
        user = user_result.scalar_one_or_none()
        if not user:
            continue

        result.append({
            "rank": actual_rank,
            "user_id": uid,
            "username": user.username,
            "rank_points": int(score),
            "is_me": uid == user_id,
        })

    return result