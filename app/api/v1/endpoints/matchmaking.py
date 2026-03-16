from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import redis.asyncio as aioredis
import time

from app.db.base import get_db
from app.db.redis import get_redis, RedisKeys
from app.core.dependencies import get_current_user
from app.core.exceptions import BadRequestError
from app.models.user import User, Profile
from app.models.match import Match, MatchPlayer, MatchMode, MatchStatus, QuestionMode
from app.schemas.match import MatchResponse
from app.services.question import generate_question_list
from app.models.match import MatchQuestion

router = APIRouter(prefix="/matchmaking", tags=["matchmaking"])

MATCH_QUEUE_KEY = "matchmaking:queue"
QUEUE_TTL = 300  # 5 minutes — long enough for slow matchmaking


@router.post("/queue", response_model=dict)
async def join_queue(
    question_mode: QuestionMode = QuestionMode.CLASSIC,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    result = await db.execute(select(Profile).where(Profile.user_id == current_user.id))
    profile = result.scalar_one_or_none()
    if not profile:
        raise BadRequestError("Profile not found")

    user_id = str(current_user.id)

    # Clear any stale match_found key from a previous session
    await redis.delete(f"queue:match_found:{user_id}")

    # Check if already in queue — remove and re-add to refresh TTL
    await redis.zrem(MATCH_QUEUE_KEY, user_id)

    await redis.zadd(MATCH_QUEUE_KEY, {user_id: profile.rank_points})
    await redis.setex(f"queue:mode:{user_id}", QUEUE_TTL, question_mode.value)
    await redis.setex(f"queue:joined:{user_id}", QUEUE_TTL, str(time.time()))

    match = await _try_match(user_id, profile.rank_points, question_mode, db, redis)

    if match:
        return {
            "status": "match_found",
            "match_id": str(match.id),
        }

    return {"status": "in_queue", "position": await redis.zcard(MATCH_QUEUE_KEY)}


@router.delete("/queue", response_model=dict)
async def leave_queue(
    current_user: User = Depends(get_current_user),
    redis: aioredis.Redis = Depends(get_redis),
):
    user_id = str(current_user.id)
    await redis.zrem(MATCH_QUEUE_KEY, user_id)
    await redis.delete(f"queue:mode:{user_id}")
    await redis.delete(f"queue:joined:{user_id}")
    await redis.delete(f"queue:match_found:{user_id}")  # clear stale match_found
    return {"status": "left_queue"}


@router.get("/queue/status", response_model=dict)
async def queue_status(
    current_user: User = Depends(get_current_user),
    redis: aioredis.Redis = Depends(get_redis),
):
    user_id = str(current_user.id)

    # Check if a match was found
    match_id = await redis.get(f"queue:match_found:{user_id}")
    if match_id:
        await redis.delete(f"queue:match_found:{user_id}")
        return {
            "status": "match_found",
            "match_id": match_id,
        }

    score = await redis.zscore(MATCH_QUEUE_KEY, user_id)
    if score is None:
        return {"status": "not_in_queue"}

    position = await redis.zrank(MATCH_QUEUE_KEY, user_id)
    return {
        "status": "in_queue",
        "position": (position or 0) + 1,
        "queue_size": await redis.zcard(MATCH_QUEUE_KEY),
    }


async def _try_match(
    user_id: str,
    rank_points: int,
    question_mode: QuestionMode,
    db: AsyncSession,
    redis: aioredis.Redis,
    rank_range: int = 1000,  # wide range ensures players always find each other
) -> Match | None:
    min_score = max(0, rank_points - rank_range)
    max_score = rank_points + rank_range

    candidates = await redis.zrangebyscore(MATCH_QUEUE_KEY, min_score, max_score)

    print(f"DEBUG: user_id={user_id!r}, candidates={candidates!r}")

    opponent_id = None
    for candidate in candidates:
        candidate_str = candidate.decode() if isinstance(candidate, bytes) else candidate
        if candidate_str == user_id:
            continue
        candidate_mode = await redis.get(f"queue:mode:{candidate_str}")
        if not candidate_mode:
            # Key expired but player still in sorted set — treat as classic rather than skip
            candidate_mode_str = "classic"
        else:
            candidate_mode_str = candidate_mode.decode() if isinstance(candidate_mode, bytes) else candidate_mode
        print(f"DEBUG: candidate={candidate_str!r} mode={candidate_mode_str!r} want={question_mode.value!r}")
        if candidate_mode_str == question_mode.value:
            opponent_id = candidate_str
            break

    if not opponent_id:
        print(f"DEBUG: no opponent found for {user_id}")
        return None

    print(f"DEBUG: matched {user_id} vs {opponent_id}")

    # Atomic lock: only one of the two simultaneous _try_match calls creates the match
    match_lock_key = f"queue:match_lock:{min(user_id, opponent_id)}:{max(user_id, opponent_id)}"
    locked = await redis.set(match_lock_key, "1", nx=True, ex=10)
    if not locked:
        return None  # other side already creating this match

    pipe = redis.pipeline()
    pipe.zrem(MATCH_QUEUE_KEY, user_id)
    pipe.zrem(MATCH_QUEUE_KEY, opponent_id)
    pipe.delete(f"queue:mode:{user_id}")
    pipe.delete(f"queue:mode:{opponent_id}")
    pipe.delete(f"queue:joined:{user_id}")
    pipe.delete(f"queue:joined:{opponent_id}")
    await pipe.execute()

    from uuid import UUID
    import json

    match = Match(
        mode=MatchMode.RANKED_1V1,
        question_mode=question_mode,
        status=MatchStatus.WAITING,
        total_rounds=10,
    )
    db.add(match)
    await db.flush()

    for uid_str in [user_id, opponent_id]:
        player = MatchPlayer(match_id=match.id, user_id=UUID(uid_str))
        db.add(player)

    questions = generate_question_list(match.total_rounds, question_mode)
    for q in questions:
        db.add(MatchQuestion(
            match_id=match.id,
            round_number=q["round_number"],
            country_name=q["country_name"],
            question_mode=question_mode,
        ))

    await redis.hset(RedisKeys.match_state(str(match.id)), mapping={
        "status": MatchStatus.WAITING.value,
        "question_mode": question_mode.value,
        "current_round": "1",
        "total_rounds": str(match.total_rounds),
        "player1": user_id,
        "player2": opponent_id,
    })
    await redis.set(
        f"match:questions:{match.id}",
        json.dumps(questions),
        ex=3600,
    )
    await db.commit()

    # Notify both players via status poll
    await redis.setex(f"queue:match_found:{user_id}", 300, str(match.id))
    await redis.setex(f"queue:match_found:{opponent_id}", 300, str(match.id))

    return match


@router.post("/match/{match_id}/forfeit", response_model=dict)
async def forfeit_match(
    match_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """Explicit forfeit — called when player clicks 'Abandon match' on reconnect screen."""
    from uuid import UUID
    from datetime import datetime, timezone
    from app.models.match import MatchStatus
    from app.ws.game import _handle_win_loss
    import json

    user_id = str(current_user.id)

    # Guard: match must still be active
    state = await redis.hgetall(f"match:state:{match_id}")
    if not state or state.get("status") != "in_progress":
        return {"status": "already_finished"}

    # Cancel any pending grace-period forfeit for this player
    await redis.set(f"match:grace:{match_id}:{user_id}", "cancelled", ex=60)

    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(MatchPlayer).where(MatchPlayer.match_id == UUID(match_id))
    )
    players = result.scalars().all()
    if not players:
        return {"status": "not_found"}

    loser  = next((p for p in players if str(p.user_id) == user_id), None)
    winner = next((p for p in players if str(p.user_id) != user_id), None)

    if not loser:
        return {"status": "not_participant"}

    if winner:
        await _handle_win_loss(match_id, winner, loser, now, db, redis)
        # Mark as forfeit in the stored result
        stored = await redis.get(f"match:result:{match_id}")
        if stored:
            payload = json.loads(stored)
            payload["forfeit"] = True
            await redis.set(f"match:result:{match_id}", json.dumps(payload), ex=300)
    else:
        # No opponent found — just close the match cleanly
        match_res = (await db.execute(
            select(Match).where(Match.id == UUID(match_id))
        )).scalar_one_or_none()
        if match_res:
            match_res.status = MatchStatus.FINISHED
            match_res.finished_at = now
            await db.commit()
        await redis.hset(f"match:state:{match_id}", "status", MatchStatus.FINISHED.value)

    # Return the actual XP/RP values so the frontend can sync localStorage
    return {
        "status": "forfeited",
        "xp_earned": loser.xp_earned,
        "rank_points_delta": loser.rank_points_delta,
    }