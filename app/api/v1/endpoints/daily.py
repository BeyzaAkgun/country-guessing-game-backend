# app/api/v1/endpoints/daily.py
# New file — Daily Challenge API endpoints.

from datetime import date, datetime, timezone, timedelta
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.base import get_db
from app.core.dependencies import get_current_user
from app.core.exceptions import ConflictError, BadRequestError
from app.models.user import User, Profile
from app.models.daily import DailyResult

router = APIRouter(prefix="/daily", tags=["daily"])


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def _fmt_time(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    return f"{m:02d}:{s:02d}"


async def _build_leaderboard(
    db: AsyncSession,
    target_date: date,
    limit: int = 100,
) -> list[dict]:
    """
    Return leaderboard rows for a given date.
    Sorted: correct_count DESC, total_time_seconds ASC, completed_at ASC.
    Joins daily_results → users so we get usernames in one query.
    """
    stmt = (
        select(
            DailyResult.user_id,
            DailyResult.correct_count,
            DailyResult.total_time_seconds,
            DailyResult.completed_at,
            User.username,
        )
        .join(User, User.id == DailyResult.user_id)
        .where(DailyResult.date == target_date)
        .order_by(
            DailyResult.correct_count.desc(),
            DailyResult.total_time_seconds.asc(),
            DailyResult.completed_at.asc(),
        )
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()

    return [
        {
            "rank": i + 1,
            "username": row.username,
            "correct_count": row.correct_count,
            "total_time_seconds": row.total_time_seconds,
            "time_formatted": _fmt_time(row.total_time_seconds),
        }
        for i, row in enumerate(rows)
    ]


@router.post("/complete")
async def complete_daily(
    body: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Called when a logged-in user finishes today's Daily Challenge.
    - Rejects duplicate submissions for the same day (409).
    - Updates streak, best_daily_streak, perfect_daily_count on Profile.
    - Inserts a DailyResult row.
    - Returns updated streak info + today's leaderboard + user's rank.
    """
    # ── Validate input ────────────────────────────────────────────────────────
    correct_count = body.get("correct_count")
    total_time_seconds = body.get("total_time_seconds")

    if correct_count is None or total_time_seconds is None:
        raise BadRequestError("correct_count and total_time_seconds are required")
    if not (0 <= correct_count <= 10):
        raise BadRequestError("correct_count must be 0–10")
    if total_time_seconds < 0:
        raise BadRequestError("total_time_seconds must be non-negative")

    today = _today_utc()

    # ── Check for duplicate submission ────────────────────────────────────────
    existing = await db.execute(
        select(DailyResult).where(
            DailyResult.user_id == current_user.id,
            DailyResult.date == today,
        )
    )
    if existing.scalar_one_or_none():
        raise ConflictError("Already completed today's challenge")

    # ── Load profile ──────────────────────────────────────────────────────────
    profile_result = await db.execute(
        select(Profile).where(Profile.user_id == current_user.id)
    )
    profile = profile_result.scalar_one_or_none()
    if not profile:
        raise BadRequestError("Profile not found")

    # ── Compute new streak ────────────────────────────────────────────────────
    yesterday = today - timedelta(days=1)
    last = profile.last_daily_completion_date

    if last == yesterday:
        # Consecutive day — extend streak
        new_streak = profile.daily_streak + 1
    elif last == today:
        # Should never reach here (duplicate check above catches it),
        # but be safe
        new_streak = profile.daily_streak
    else:
        # Missed one or more days, or first ever completion
        new_streak = 1

    new_best = max(profile.best_daily_streak, new_streak)
    new_perfect = profile.perfect_daily_count + (1 if correct_count == 10 else 0)

    # ── Update profile ────────────────────────────────────────────────────────
    profile.daily_streak = new_streak
    profile.best_daily_streak = new_best
    profile.last_daily_completion_date = today
    profile.perfect_daily_count = new_perfect

    # ── Insert daily result ───────────────────────────────────────────────────
    now_utc = datetime.now(timezone.utc)
    daily_row = DailyResult(
        user_id=current_user.id,
        date=today,
        correct_count=correct_count,
        total_time_seconds=total_time_seconds,
        completed_at=now_utc,
    )
    db.add(daily_row)
    await db.commit()

    # ── Build leaderboard ─────────────────────────────────────────────────────
    leaderboard = await _build_leaderboard(db, today)

    # Find user's rank in leaderboard
    user_rank = next(
        (row["rank"] for row in leaderboard if row["username"] == current_user.username),
        None,
    )

    return {
        "streak": new_streak,
        "best_streak": new_best,
        "perfect_count": new_perfect,
        "user_rank": user_rank,
        "leaderboard": leaderboard,
    }


@router.get("/leaderboard")
async def get_daily_leaderboard(
    date_str: str | None = Query(default=None, alias="date"),
    limit: int = Query(default=50, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    GET /api/v1/daily/leaderboard?date=2025-06-03
    Returns top N players for the given date (defaults to today UTC).
    Also returns the calling user's rank if they have a result for that day.
    """
    if date_str:
        try:
            target_date = date.fromisoformat(date_str)
        except ValueError:
            raise BadRequestError("date must be YYYY-MM-DD format")
    else:
        target_date = _today_utc()

    leaderboard = await _build_leaderboard(db, target_date, limit)

    # Inject is_me flag so frontend can highlight the current user's row
    for row in leaderboard:
        row["is_me"] = row["username"] == current_user.username

    user_rank = next(
        (row["rank"] for row in leaderboard if row["is_me"]),
        None,
    )

    return {
        "date": target_date.isoformat(),
        "user_rank": user_rank,
        "leaderboard": leaderboard,
    }


@router.get("/status")
async def get_daily_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Quick check: has the current user already completed today's challenge?
    Returns streak info and today's result if it exists.
    Used by frontend on load to sync localStorage state with server.
    """
    today = _today_utc()

    result = await db.execute(
        select(DailyResult).where(
            DailyResult.user_id == current_user.id,
            DailyResult.date == today,
        )
    )
    today_result = result.scalar_one_or_none()

    profile_result = await db.execute(
        select(Profile).where(Profile.user_id == current_user.id)
    )
    profile = profile_result.scalar_one_or_none()

    return {
        "completed_today": today_result is not None,
        "streak": profile.daily_streak if profile else 0,
        "best_streak": profile.best_daily_streak if profile else 0,
        "perfect_count": profile.perfect_daily_count if profile else 0,
        "today_result": {
            "correct_count": today_result.correct_count,
            "total_time_seconds": today_result.total_time_seconds,
            "time_formatted": _fmt_time(today_result.total_time_seconds),
        } if today_result else None,
    }