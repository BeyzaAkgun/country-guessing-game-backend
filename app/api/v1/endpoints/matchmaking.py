# from fastapi import APIRouter, Depends
# from sqlalchemy.ext.asyncio import AsyncSession
# from sqlalchemy import select
# import redis.asyncio as aioredis
# import time

# from app.db.base import get_db
# from app.db.redis import get_redis, RedisKeys
# from app.core.dependencies import get_current_user
# from app.core.exceptions import BadRequestError
# from app.models.user import User, Profile
# from app.models.match import Match, MatchPlayer, MatchMode, MatchStatus, QuestionMode
# from app.schemas.match import MatchResponse
# from app.services.question import generate_question_list
# from app.models.match import MatchQuestion

# router = APIRouter(prefix="/matchmaking", tags=["matchmaking"])

# MATCH_QUEUE_KEY = "matchmaking:queue"
# QUEUE_TTL = 300  # 5 minutes


# @router.post("/queue", response_model=dict)
# async def join_queue(
#     question_mode: QuestionMode = QuestionMode.CLASSIC,
#     current_user: User = Depends(get_current_user),
#     db: AsyncSession = Depends(get_db),
#     redis: aioredis.Redis = Depends(get_redis),
# ):
#     result = await db.execute(select(Profile).where(Profile.user_id == current_user.id))
#     profile = result.scalar_one_or_none()
#     if not profile:
#         raise BadRequestError("Profile not found")

#     user_id = str(current_user.id)

#     # ── Check if a match was already created for this player ─────────────────
#     # This happens when the opponent joined first and already ran _try_match
#     existing_match = await redis.get(f"queue:match_found:{user_id}")
#     if existing_match:
#         return {
#             "status": "match_found",
#             "match_id": existing_match,
#         }

#     # Check if already in queue — remove and re-add to refresh TTL
#     await redis.zrem(MATCH_QUEUE_KEY, user_id)

#     await redis.zadd(MATCH_QUEUE_KEY, {user_id: profile.rank_points})
#     await redis.setex(f"queue:mode:{user_id}", QUEUE_TTL, question_mode.value)
#     await redis.setex(f"queue:joined:{user_id}", QUEUE_TTL, str(time.time()))

#     match = await _try_match(user_id, profile.rank_points, question_mode, db, redis)

#     if match:
#         return {
#             "status": "match_found",
#             "match_id": str(match.id),
#         }

#     return {"status": "in_queue", "position": await redis.zcard(MATCH_QUEUE_KEY)}


# @router.delete("/queue", response_model=dict)
# async def leave_queue(
#     current_user: User = Depends(get_current_user),
#     redis: aioredis.Redis = Depends(get_redis),
# ):
#     user_id = str(current_user.id)
#     await redis.zrem(MATCH_QUEUE_KEY, user_id)
#     await redis.delete(f"queue:mode:{user_id}")
#     await redis.delete(f"queue:joined:{user_id}")
#     await redis.delete(f"queue:match_found:{user_id}")
#     return {"status": "left_queue"}


# @router.get("/queue/status", response_model=dict)
# async def queue_status(
#     current_user: User = Depends(get_current_user),
#     redis: aioredis.Redis = Depends(get_redis),
# ):
#     user_id = str(current_user.id)

#     match_id = await redis.get(f"queue:match_found:{user_id}")
#     if match_id:
#         await redis.delete(f"queue:match_found:{user_id}")
#         return {
#             "status": "match_found",
#             "match_id": match_id,
#         }

#     score = await redis.zscore(MATCH_QUEUE_KEY, user_id)
#     if score is None:
#         return {"status": "not_in_queue"}

#     position = await redis.zrank(MATCH_QUEUE_KEY, user_id)
#     return {
#         "status": "in_queue",
#         "position": (position or 0) + 1,
#         "queue_size": await redis.zcard(MATCH_QUEUE_KEY),
#     }


# async def _try_match(
#     user_id: str,
#     rank_points: int,
#     question_mode: QuestionMode,
#     db: AsyncSession,
#     redis: aioredis.Redis,
#     rank_range: int = 1000,
# ) -> Match | None:
#     min_score = max(0, rank_points - rank_range)
#     max_score = rank_points + rank_range

#     candidates = await redis.zrangebyscore(MATCH_QUEUE_KEY, min_score, max_score)

#     print(f"DEBUG: user_id={user_id!r}, candidates={candidates!r}")

#     opponent_id = None
#     for candidate in candidates:
#         candidate_str = candidate.decode() if isinstance(candidate, bytes) else candidate
#         if candidate_str == user_id:
#             continue
#         candidate_mode = await redis.get(f"queue:mode:{candidate_str}")
#         if not candidate_mode:
#             candidate_mode_str = "classic"
#         else:
#             candidate_mode_str = candidate_mode.decode() if isinstance(candidate_mode, bytes) else candidate_mode
#         print(f"DEBUG: candidate={candidate_str!r} mode={candidate_mode_str!r} want={question_mode.value!r}")
#         if candidate_mode_str == question_mode.value:
#             opponent_id = candidate_str
#             break

#     if not opponent_id:
#         print(f"DEBUG: no opponent found for {user_id}")
#         return None

#     print(f"DEBUG: matched {user_id} vs {opponent_id}")

#     match_lock_key = f"queue:match_lock:{min(user_id, opponent_id)}:{max(user_id, opponent_id)}"
#     locked = await redis.set(match_lock_key, "1", nx=True, ex=10)
#     if not locked:
#         return None

#     pipe = redis.pipeline()
#     pipe.zrem(MATCH_QUEUE_KEY, user_id)
#     pipe.zrem(MATCH_QUEUE_KEY, opponent_id)
#     pipe.delete(f"queue:mode:{user_id}")
#     pipe.delete(f"queue:mode:{opponent_id}")
#     pipe.delete(f"queue:joined:{user_id}")
#     pipe.delete(f"queue:joined:{opponent_id}")
#     await pipe.execute()

#     from uuid import UUID
#     import json

#     match = Match(
#         mode=MatchMode.RANKED_1V1,
#         question_mode=question_mode,
#         status=MatchStatus.WAITING,
#         total_rounds=10,
#     )
#     db.add(match)
#     await db.flush()

#     for uid_str in [user_id, opponent_id]:
#         player = MatchPlayer(match_id=match.id, user_id=UUID(uid_str))
#         db.add(player)

#     questions = generate_question_list(match.total_rounds, question_mode)
#     for q in questions:
#         db.add(MatchQuestion(
#             match_id=match.id,
#             round_number=q["round_number"],
#             country_name=q["country_name"],
#             question_mode=question_mode,
#         ))

#     await redis.hset(RedisKeys.match_state(str(match.id)), mapping={
#         "status": MatchStatus.WAITING.value,
#         "question_mode": question_mode.value,
#         "current_round": "1",
#         "total_rounds": str(match.total_rounds),
#         "player1": user_id,
#         "player2": opponent_id,
#     })
#     await redis.set(
#         f"match:questions:{match.id}",
#         json.dumps(questions),
#         ex=3600,
#     )
#     await db.commit()

#     # Notify both players via status poll
#     await redis.setex(f"queue:match_found:{user_id}", 300, str(match.id))
#     await redis.setex(f"queue:match_found:{opponent_id}", 300, str(match.id))

#     return match


# @router.post("/match/{match_id}/forfeit", response_model=dict)
# async def forfeit_match(
#     match_id: str,
#     current_user: User = Depends(get_current_user),
#     db: AsyncSession = Depends(get_db),
#     redis: aioredis.Redis = Depends(get_redis),
# ):
#     from uuid import UUID
#     from datetime import datetime, timezone
#     from app.models.match import MatchStatus
#     from app.ws.game import _handle_win_loss
#     import json

#     user_id = str(current_user.id)

#     state = await redis.hgetall(f"match:state:{match_id}")
#     if not state or state.get("status") != "in_progress":
#         return {"status": "already_finished"}

#     await redis.set(f"match:grace:{match_id}:{user_id}", "cancelled", ex=60)

#     now = datetime.now(timezone.utc)

#     result = await db.execute(
#         select(MatchPlayer).where(MatchPlayer.match_id == UUID(match_id))
#     )
#     players = result.scalars().all()
#     if not players:
#         return {"status": "not_found"}

#     loser  = next((p for p in players if str(p.user_id) == user_id), None)
#     winner = next((p for p in players if str(p.user_id) != user_id), None)

#     if not loser:
#         return {"status": "not_participant"}

#     if winner:
#         await _handle_win_loss(match_id, winner, loser, now, db, redis)
#         stored = await redis.get(f"match:result:{match_id}")
#         if stored:
#             payload = json.loads(stored)
#             payload["forfeit"] = True
#             await redis.set(f"match:result:{match_id}", json.dumps(payload), ex=300)
#     else:
#         match_res = (await db.execute(
#             select(Match).where(Match.id == UUID(match_id))
#         )).scalar_one_or_none()
#         if match_res:
#             match_res.status = MatchStatus.FINISHED
#             match_res.finished_at = now
#             await db.commit()
#         await redis.hset(f"match:state:{match_id}", "status", MatchStatus.FINISHED.value)

#     return {
#         "status": "forfeited",
#         "xp_earned": loser.xp_earned,
#         "rank_points_delta": loser.rank_points_delta,
#     }






#matchmaking.py
#matchmaking.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import redis.asyncio as aioredis
import time
from uuid import UUID
import json

from app.db.base import get_db
from app.db.redis import get_redis, RedisKeys
from app.core.dependencies import get_current_user
from app.core.exceptions import BadRequestError
from app.models.user import User, Profile
from app.models.match import Match, MatchPlayer, MatchMode, MatchStatus, QuestionMode, MatchQuestion
from app.services.question import generate_question_list

router = APIRouter(prefix="/matchmaking", tags=["matchmaking"])

MATCH_QUEUE_KEY = "matchmaking:queue"
QUEUE_TTL = 300
ACTIVE_MATCH_TTL = 60 * 60 * 2


def _decode(v):
    return v.decode() if isinstance(v, bytes) else v


def _active_match_key(user_id: str) -> str:
    return f"user:active_match:{user_id}"


def _match_found_key(user_id: str) -> str:
    return f"queue:match_found:{user_id}"


def _is_finished(status) -> bool:
    return (
        status == MatchStatus.FINISHED
        or status == MatchStatus.CANCELLED
        or str(status) == MatchStatus.FINISHED.value
        or str(status) == MatchStatus.CANCELLED.value
    )


async def _clear_queue_state(redis: aioredis.Redis, user_id: str) -> None:
    await redis.zrem(MATCH_QUEUE_KEY, user_id)
    await redis.delete(f"queue:mode:{user_id}")
    await redis.delete(f"queue:joined:{user_id}")


async def _clear_active_match_keys(redis: aioredis.Redis, user_ids: list[str]) -> None:
    pipe = redis.pipeline()
    for uid in user_ids:
        pipe.delete(_active_match_key(uid))
    await pipe.execute()


async def _get_live_active_match_id(user_id: str, db: AsyncSession, redis: aioredis.Redis) -> str | None:
    """
    Returns the active match ID only if the match exists AND is not finished.
    Always cleans up stale Redis keys when a finished/missing match is found.
    """
    raw = await redis.get(_active_match_key(user_id))
    if not raw:
        return None

    match_id = _decode(raw)
    try:
        match_uuid = UUID(match_id)
    except Exception:
        await redis.delete(_active_match_key(user_id))
        return None

    result = await db.execute(select(Match.status).where(Match.id == match_uuid))
    status = result.scalar_one_or_none()

    if status is None or _is_finished(status):
        await redis.delete(_active_match_key(user_id))
        return None

    return match_id


async def _validate_match_found_key(user_id: str, db: AsyncSession, redis: aioredis.Redis) -> str | None:
    """
    Returns the match_found key's match ID only if the match is still active (not finished/missing).
    Always deletes the key when the match is stale — this is the critical fix.
    """
    raw = await redis.get(_match_found_key(user_id))
    if not raw:
        return None

    match_id = _decode(raw)

    try:
        match_uuid = UUID(match_id)
        result = await db.execute(select(Match.status).where(Match.id == match_uuid))
        status = result.scalar_one_or_none()

        # If match doesn't exist OR is finished → always clean up and return None
        if status is None or _is_finished(status):
            await redis.delete(_match_found_key(user_id))
            return None

        # Match is alive — return it
        return match_id

    except Exception:
        # Any error (bad UUID etc.) → clean up
        await redis.delete(_match_found_key(user_id))
        return None


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

    # Check for an existing live active match first
    live_match = await _get_live_active_match_id(user_id, db, redis)
    if live_match:
        return {
            "status": "already_in_match",
            "match_id": live_match,
        }

    # Check for a pending match_found notification — validate it before trusting it
    pending_match = await _validate_match_found_key(user_id, db, redis)
    if pending_match:
        # Re-delete to consume the notification (client will connect via WS)
        await redis.delete(_match_found_key(user_id))
        return {
            "status": "match_found",
            "match_id": pending_match,
        }

    # Clean up any stale queue entries and re-enter the queue fresh
    await _clear_queue_state(redis, user_id)

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
    await redis.delete(_match_found_key(user_id))
    return {"status": "left_queue"}


@router.get("/queue/status", response_model=dict)
async def queue_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    user_id = str(current_user.id)

    # Check for an existing live active match first
    live_match = await _get_live_active_match_id(user_id, db, redis)
    if live_match:
        return {
            "status": "already_in_match",
            "match_id": live_match,
        }

    # Validate the match_found key — delete it if the match is stale
    pending_match = await _validate_match_found_key(user_id, db, redis)
    if pending_match:
        # Re-delete to consume the notification
        await redis.delete(_match_found_key(user_id))
        return {
            "status": "match_found",
            "match_id": pending_match,
        }

    # Not in any match — check queue membership
    score = await redis.zscore(MATCH_QUEUE_KEY, user_id)
    if score is None:
        return {"status": "not_in_queue"}

    position = await redis.zrank(MATCH_QUEUE_KEY, user_id)
    return {
        "status": "in_queue",
        "position": (position or 0) + 1,
        "queue_size": await redis.zcard(MATCH_QUEUE_KEY),
    }


@router.get("/match/{match_id}/status", response_model=dict)
async def get_match_status(
    match_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    try:
        match_uuid = UUID(match_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid_match_id")

    match_result = await db.execute(select(Match).where(Match.id == match_uuid))
    match = match_result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="match_not_found")

    player_result = await db.execute(
        select(MatchPlayer).where(
            MatchPlayer.match_id == match_uuid,
            MatchPlayer.user_id == current_user.id,
        )
    )
    player = player_result.scalar_one_or_none()
    if not player:
        raise HTTPException(status_code=403, detail="not_a_participant")

    if _is_finished(match.status):
        stored = await redis.get(f"match:result:{match_id}")
        result_payload = json.loads(_decode(stored)) if stored else None

        players_result = await db.execute(
            select(MatchPlayer).where(MatchPlayer.match_id == match_uuid)
        )
        players = players_result.scalars().all()
        await _clear_active_match_keys(redis, [str(p.user_id) for p in players if p.user_id])

        return {
            "status": "finished",
            "match_id": match_id,
            "result": result_payload,
        }

    state = await redis.hgetall(RedisKeys.match_state(match_id))
    status = _decode(state.get("status")) if state else match.status.value

    return {
        "status": status,
        "match_id": match_id,
        "started_at": _decode(state.get("started_at")) if state else None,
        "current_round": int(_decode(state.get("current_round"))) if state and state.get("current_round") else None,
        "total_rounds": int(_decode(state.get("total_rounds"))) if state and state.get("total_rounds") else match.total_rounds,
    }


async def _try_match(
    user_id: str,
    rank_points: int,
    question_mode: QuestionMode,
    db: AsyncSession,
    redis: aioredis.Redis,
    rank_range: int = 1000,
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

        candidate_active = await redis.get(_active_match_key(candidate_str))
        if candidate_active:
            continue

        candidate_mode = await redis.get(f"queue:mode:{candidate_str}")
        if not candidate_mode:
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

    match_lock_key = f"queue:match_lock:{min(user_id, opponent_id)}:{max(user_id, opponent_id)}"
    locked = await redis.set(match_lock_key, "1", nx=True, ex=10)
    if not locked:
        return None

    pipe = redis.pipeline()
    pipe.zscore(MATCH_QUEUE_KEY, user_id)
    pipe.zscore(MATCH_QUEUE_KEY, opponent_id)
    pipe.get(_active_match_key(user_id))
    pipe.get(_active_match_key(opponent_id))
    pipe.get(f"queue:mode:{user_id}")
    pipe.get(f"queue:mode:{opponent_id}")
    user_score, opponent_score, user_active, opponent_active, user_mode_raw, opponent_mode_raw = await pipe.execute()

    if user_score is None or opponent_score is None:
        return None
    if user_active or opponent_active:
        return None

    user_mode = user_mode_raw.decode() if isinstance(user_mode_raw, bytes) else (user_mode_raw or "classic")
    opponent_mode = opponent_mode_raw.decode() if isinstance(opponent_mode_raw, bytes) else (opponent_mode_raw or "classic")

    if user_mode != question_mode.value or opponent_mode != question_mode.value:
        return None

    pipe = redis.pipeline()
    pipe.zrem(MATCH_QUEUE_KEY, user_id)
    pipe.zrem(MATCH_QUEUE_KEY, opponent_id)
    pipe.delete(f"queue:mode:{user_id}")
    pipe.delete(f"queue:mode:{opponent_id}")
    pipe.delete(f"queue:joined:{user_id}")
    pipe.delete(f"queue:joined:{opponent_id}")
    await pipe.execute()

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

    await redis.set(_active_match_key(user_id), str(match.id), ex=ACTIVE_MATCH_TTL)
    await redis.set(_active_match_key(opponent_id), str(match.id), ex=ACTIVE_MATCH_TTL)

    await redis.setex(_match_found_key(user_id), 300, str(match.id))
    await redis.setex(_match_found_key(opponent_id), 300, str(match.id))

    return match


@router.post("/match/{match_id}/forfeit", response_model=dict)
async def forfeit_match(
    match_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    from datetime import datetime, timezone
    from app.ws.game import _handle_win_loss

    user_id = str(current_user.id)

    try:
        match_uuid = UUID(match_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid_match_id")

    match_result = await db.execute(select(Match).where(Match.id == match_uuid))
    match = match_result.scalar_one_or_none()
    if not match:
        raise HTTPException(status_code=404, detail="match_not_found")

    # Check DB status first — the authoritative source
    if _is_finished(match.status):
        players_result = await db.execute(
            select(MatchPlayer).where(MatchPlayer.match_id == match_uuid)
        )
        players = players_result.scalars().all()
        await _clear_active_match_keys(redis, [str(p.user_id) for p in players if p.user_id])
        raise HTTPException(status_code=409, detail="match_already_ended")

    # Also check Redis state (faster for in-flight transitions)
    state = await redis.hgetall(RedisKeys.match_state(match_id))
    if state and _decode(state.get("status", "")) == MatchStatus.FINISHED.value:
        players_result = await db.execute(
            select(MatchPlayer).where(MatchPlayer.match_id == match_uuid)
        )
        players = players_result.scalars().all()
        await _clear_active_match_keys(redis, [str(p.user_id) for p in players if p.user_id])
        raise HTTPException(status_code=409, detail="match_already_ended")

    await redis.set(f"match:grace:{match_id}:{user_id}", "cancelled", ex=60)

    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(MatchPlayer).where(MatchPlayer.match_id == match_uuid)
    )
    players = result.scalars().all()
    if not players:
        raise HTTPException(status_code=404, detail="match_not_found")

    loser = next((p for p in players if str(p.user_id) == user_id), None)
    winner = next((p for p in players if str(p.user_id) != user_id), None)

    if not loser:
        raise HTTPException(status_code=403, detail="not_participant")

    if winner:
        await _handle_win_loss(match_id, winner, loser, now, db, redis)
        stored = await redis.get(f"match:result:{match_id}")
        if stored:
            payload = json.loads(_decode(stored))
            payload["forfeit"] = True
            await redis.set(f"match:result:{match_id}", json.dumps(payload), ex=300)
    else:
        match.status = MatchStatus.FINISHED
        match.finished_at = now
        await db.commit()
        await redis.hset(RedisKeys.match_state(match_id), "status", MatchStatus.FINISHED.value)

    return {
        "status": "forfeited",
        "xp_earned": loser.xp_earned,
        "rank_points_delta": loser.rank_points_delta,
    }