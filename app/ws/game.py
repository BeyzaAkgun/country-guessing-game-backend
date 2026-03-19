from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import json
import logging
import asyncio
from datetime import datetime, timezone

from app.ws.manager import manager
from app.db.base import AsyncSessionLocal
from app.db.redis import get_redis, RedisKeys
from app.models.match import Match, MatchPlayer, MatchQuestion, MatchStatus
from app.models.user import Profile
from app.services.rank import (
    calculate_rank_tier, calculate_xp_gain, calculate_rank_points_delta
)

logger = logging.getLogger(__name__)

DRAW_RP_BONUS = 15
DRAW_XP_MULTIPLIER = 0.6


async def handle_game_connection(
    websocket: WebSocket,
    match_id: str,
    user_id: str,
    db: AsyncSession,
):
    redis = get_redis()
    await manager.connect(match_id, websocket, user_id)

    try:
        state = await redis.hgetall(RedisKeys.match_state(match_id))
        if not state:
            await manager.send_to(websocket, "error", {"message": "Match not found"})
            manager.disconnect(match_id, websocket)
            return

        await manager.broadcast(match_id, "player_connected", {"user_id": user_id})

        conn_count = manager.get_connection_count(match_id)
        fresh_state = await redis.hgetall(RedisKeys.match_state(match_id))
        match_status = fresh_state.get("status", "")

        logger.info(f"Player {user_id} connected to match {match_id} | status={match_status} | conn_count={conn_count}")

        if match_status == MatchStatus.FINISHED.value:
            await _send_resync(websocket, match_id, redis)

        elif match_status == MatchStatus.IN_PROGRESS.value:
            grace_key = f"match:grace:{match_id}:{user_id}"
            existing = await redis.get(grace_key)
            if existing == "waiting":
                await redis.set(grace_key, "cancelled", ex=60)
                logger.info(f"Forfeit grace cancelled for {user_id} in {match_id}")

            await manager.broadcast_except(match_id, websocket, "opponent_reconnected", {"user_id": user_id})
            await _send_resync(websocket, match_id, redis)

        else:
            if conn_count == 2:
                lock_key = f"match:start_lock:{match_id}"
                locked = await redis.set(lock_key, "1", nx=True, ex=30)
                if locked:
                    await _start_match(match_id, db, redis)

        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                await manager.send_to(websocket, "error", {"message": "Invalid JSON"})
                continue

            event = message.get("event")
            data = message.get("data", {})

            if event == "answer":
                await _handle_answer(websocket, match_id, user_id, data, redis)
            elif event == "ping":
                await manager.send_to(websocket, "pong", {})

    except WebSocketDisconnect:
        manager.disconnect(match_id, websocket)

        from uuid import UUID
        try:
            async with AsyncSessionLocal() as disc_db:
                result = await disc_db.execute(
                    select(MatchPlayer).where(
                        MatchPlayer.match_id == UUID(match_id),
                        MatchPlayer.user_id == UUID(user_id),
                    )
                )
                player = result.scalar_one_or_none()
                if player:
                    player.disconnected = True
                    await disc_db.commit()
        except Exception as e:
            logger.error(f"Error marking disconnected: {e}")

        state = await redis.hgetall(RedisKeys.match_state(match_id))
        match_still_active = state.get("status") == "in_progress"

        if match_still_active:
            await manager.broadcast(match_id, "player_disconnected", {
                "user_id": user_id,
                "grace_seconds": 15,
            })
            grace_key = f"match:grace:{match_id}:{user_id}"
            await redis.set(grace_key, "waiting", ex=20)
            asyncio.create_task(_forfeit_after_grace(match_id, user_id, 15, redis))
        else:
            await manager.broadcast(match_id, "player_disconnected", {
                "user_id": user_id,
                "grace_seconds": 0,
            })

    except Exception as e:
        logger.error(f"WS error {user_id}/{match_id}: {e}", exc_info=True)
        manager.disconnect(match_id, websocket)


async def _forfeit_after_grace(match_id: str, disconnected_user_id: str, grace_seconds: int, redis):
    await asyncio.sleep(grace_seconds)

    grace_key = f"match:grace:{match_id}:{disconnected_user_id}"
    status = await redis.get(grace_key)

    if status == "cancelled":
        logger.info(f"Forfeit cancelled for {disconnected_user_id} in match {match_id}")
        return

    conn_count = manager.get_connection_count(match_id)
    if conn_count >= 2:
        logger.info(f"Forfeit aborted — {conn_count} players connected in match {match_id}")
        await redis.delete(grace_key)
        return

    state = await redis.hgetall(RedisKeys.match_state(match_id))
    if state.get("status") != "in_progress":
        return

    logger.info(f"Forfeit: {disconnected_user_id} did not reconnect to match {match_id}")

    from uuid import UUID
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(
                select(MatchPlayer).where(MatchPlayer.match_id == UUID(match_id))
            )
            players = result.scalars().all()
            if not players:
                return

            winner = next((p for p in players if str(p.user_id) != disconnected_user_id), None)
            loser  = next((p for p in players if str(p.user_id) == disconnected_user_id), None)

            if winner and loser:
                await _sync_wrong_answers(match_id, [winner, loser], redis)
                await _handle_win_loss(match_id, winner, loser, now, db, redis)
                stored = await redis.get(f"match:result:{match_id}")
                if stored:
                    payload = json.loads(stored)
                    payload["forfeit"] = True
                    await redis.set(f"match:result:{match_id}", json.dumps(payload), ex=300)
            await db.commit()
        except Exception as e:
            logger.error(f"Forfeit DB error for match {match_id}: {e}", exc_info=True)
            await db.rollback()

    await redis.delete(grace_key)


async def _send_resync(websocket, match_id: str, redis):
    state = await redis.hgetall(RedisKeys.match_state(match_id))
    match_status = state.get("status", "")

    if match_status == MatchStatus.FINISHED.value:
        stored = await redis.get(f"match:result:{match_id}")
        if stored:
            await manager.send_to(websocket, "match_end", json.loads(stored))
        else:
            await manager.send_to(websocket, "error", {"message": "This match has already ended."})
        return

    current_round = int(state.get("current_round", "1"))

    questions_raw = await redis.get(f"match:questions:{match_id}")
    if not questions_raw:
        await manager.send_to(websocket, "error", {"message": "Match data unavailable"})
        return
    questions = json.loads(questions_raw)
    current_q = next((q for q in questions if q["round_number"] == current_round), None)
    if not current_q:
        return

    await manager.send_to(websocket, "match_start", {
        "match_id": match_id,
        "total_rounds": len(questions),
        "question_mode": current_q.get("question_mode", "classic"),
        "reconnect": True,
    })

    asked_at = state.get(f"round_{current_round}_started_at") or state.get("started_at")
    await manager.send_to(websocket, "question", {
        "round": current_round,
        "country_name": current_q["country_name"],
        "mode": current_q.get("question_mode", "classic"),
        "started_at": asked_at,
    })


async def _start_match(match_id: str, db: AsyncSession, redis):
    from uuid import UUID
    now = datetime.now(timezone.utc)

    result = await db.execute(select(Match).where(Match.id == UUID(match_id)))
    match = result.scalar_one_or_none()
    if not match:
        return

    match.status = MatchStatus.IN_PROGRESS
    match.started_at = now
    await db.commit()

    await redis.hset(RedisKeys.match_state(match_id), mapping={
        "status": MatchStatus.IN_PROGRESS.value,
        "started_at": now.isoformat(),
        "current_round": "1",
    })

    questions_raw = await redis.get(f"match:questions:{match_id}")
    if not questions_raw:
        return
    questions = json.loads(questions_raw)
    first_q = questions[0]

    result = await db.execute(
        select(MatchQuestion).where(
            MatchQuestion.match_id == UUID(match_id),
            MatchQuestion.round_number == 1,
        )
    )
    mq = result.scalar_one_or_none()
    if mq:
        mq.asked_at = now
        await db.commit()

    await redis.hset(RedisKeys.match_state(match_id), "round_1_started_at", now.isoformat())
    await manager.broadcast(match_id, "match_start", {
        "match_id": match_id,
        "total_rounds": match.total_rounds,
        "question_mode": match.question_mode.value,
    })
    await manager.broadcast(match_id, "question", {
        "round": first_q["round_number"],
        "country_name": first_q["country_name"],
        "mode": first_q["question_mode"],
        "started_at": now.isoformat(),
    })

    # Start auto-advance timer for round 1
    asyncio.create_task(_auto_advance(match_id, 1, now.isoformat(), redis))


async def _handle_answer(
    websocket: WebSocket,
    match_id: str,
    user_id: str,
    data: dict,
    redis,
):
    """
    Handle a player's answer. Uses its own fresh DB session for each call
    to avoid session corruption from multiple rapid wrong-answer submissions.
    """
    from uuid import UUID

    raw_answer = data.get("answer", "").strip()
    hints_used = int(data.get("hints_used", 0))

    state = await redis.hgetall(RedisKeys.match_state(match_id))
    current_round = int(state.get("current_round", "1"))
    total_rounds = int(state.get("total_rounds", "10"))

    # Block if player already answered correctly this round
    correct_key = f"match:player_correct:{match_id}:{current_round}:{user_id}"
    already_correct = await redis.exists(correct_key)
    if already_correct:
        return

    questions_raw = await redis.get(f"match:questions:{match_id}")
    if not questions_raw:
        return
    questions = json.loads(questions_raw)
    current_q = next((q for q in questions if q["round_number"] == current_round), None)
    if not current_q:
        return

    correct = bool(raw_answer) and raw_answer.lower() == current_q["country_name"].lower()

    streak = 0
    points = 0

    if correct:
        # Mark correct immediately in Redis to prevent duplicate correct submissions
        await redis.setex(correct_key, 300, "1")

        # Fresh DB session for correct answer — isolated, won't be dirtied by wrong answers
        async with AsyncSessionLocal() as db:
            try:
                result = await db.execute(
                    select(MatchPlayer).where(
                        MatchPlayer.match_id == UUID(match_id),
                        MatchPlayer.user_id == UUID(user_id),
                    )
                )
                player = result.scalar_one_or_none()
                if player:
                    player.correct_answers += 1
                    streak_key = f"match:streak:{match_id}:{user_id}"
                    streak = int(await redis.get(streak_key) or "0") + 1
                    await redis.setex(streak_key, 3600, str(streak))
                    multiplier = 2.0 if streak >= 5 else 1.5 if streak >= 3 else 1.0
                    hint_penalty = max(0, hints_used - 1) * 0.15
                    points = int(100 * multiplier * max(0.25, 1.0 - hint_penalty))
                    player.score += points
                    player.best_streak = max(player.best_streak, streak)
                    await db.commit()
            except Exception as e:
                logger.error(f"DB error on correct answer {match_id}/{user_id}: {e}", exc_info=True)
                await db.rollback()
    else:
        # Wrong answer — Redis only, no DB write
        await redis.incr(f"match:wrong:{match_id}:{user_id}")
        await redis.expire(f"match:wrong:{match_id}:{user_id}", 3600)
        await redis.delete(f"match:streak:{match_id}:{user_id}")

    # Send result to this player
    await manager.send_to(websocket, "answer_result", {
        "correct": correct,
        "points_earned": points,
        "streak": streak,
        "correct_answer": current_q["country_name"] if not correct else None,
        "round": current_round,
    })

    # Broadcast to both players
    await manager.broadcast(match_id, "player_answered", {
        "user_id": user_id,
        "correct": correct,
        "points_earned": points,
        "round": current_round,
    })

    # Advance round on correct answer
    if correct:
        asyncio.create_task(_advance_round(match_id, current_round, total_rounds, redis))


async def _advance_round(match_id, current_round, total_rounds, redis):
    """
    Advance to next round. Always uses a fresh DB session.
    Called as a background task to avoid blocking the WebSocket handler.
    """
    lock_key = f"match:round_lock:{match_id}:{current_round}"
    locked = await redis.set(lock_key, "1", nx=True, ex=10)
    if not locked:
        return

    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as db:
        try:
            from uuid import UUID

            result = await db.execute(
                select(MatchQuestion).where(
                    MatchQuestion.match_id == UUID(match_id),
                    MatchQuestion.round_number == current_round,
                )
            )
            mq = result.scalar_one_or_none()
            if mq and not mq.answered_at:
                mq.answered_at = now
                await db.commit()

            next_round = current_round + 1
            if next_round > total_rounds:
                await _finish_match(match_id, db, redis)
                return

            await redis.hset(RedisKeys.match_state(match_id), "current_round", str(next_round))
            await redis.hset(RedisKeys.match_state(match_id), f"round_{next_round}_started_at", now.isoformat())

            questions_raw = await redis.get(f"match:questions:{match_id}")
            questions = json.loads(questions_raw)
            next_q = next((q for q in questions if q["round_number"] == next_round), None)
            if not next_q:
                return

            result = await db.execute(
                select(MatchQuestion).where(
                    MatchQuestion.match_id == UUID(match_id),
                    MatchQuestion.round_number == next_round,
                )
            )
            mq = result.scalar_one_or_none()
            if mq and not mq.asked_at:
                mq.asked_at = now
                await db.commit()

            await manager.broadcast(match_id, "question", {
                "round": next_q["round_number"],
                "country_name": next_q["country_name"],
                "mode": next_q["question_mode"],
                "started_at": now.isoformat(),
            })

            # Start auto-advance timer for next round
            asyncio.create_task(_auto_advance(match_id, next_round, now.isoformat(), redis))

        except Exception as e:
            logger.error(f"_advance_round error match={match_id} round={current_round}: {e}", exc_info=True)
            await db.rollback()




async def _auto_advance(match_id: str, round_num: int, started_at: str, redis):
    """Auto-advance the round after ROUND_SECONDS if nobody answered correctly."""
    ROUND_SECONDS = 30
    try:
        elapsed = (datetime.now(timezone.utc).timestamp() -
                   datetime.fromisoformat(started_at.replace("Z", "+00:00")).timestamp())
        wait = max(0, ROUND_SECONDS - elapsed)
        await asyncio.sleep(wait + 0.5)  # small buffer

        # Check if round already advanced
        state = await redis.hgetall(RedisKeys.match_state(match_id))
        if not state:
            return
        if int(state.get("current_round", 0)) != round_num:
            return  # already advanced by a correct answer
        if state.get("status") != "in_progress":
            return

        total_rounds = int(state.get("total_rounds", "10"))
        logger.info(f"Auto-advancing match {match_id} round {round_num} (timer expired)")
        await _advance_round(match_id, round_num, total_rounds, redis)
    except Exception as e:
        logger.error(f"_auto_advance error match={match_id} round={round_num}: {e}", exc_info=True)

async def _finish_match(match_id, db, redis):
    import asyncio
    from uuid import UUID

    lock_key = f"match:finish_lock:{match_id}"
    locked = await redis.set(lock_key, "1", nx=True, ex=30)
    if not locked:
        await asyncio.sleep(0.5)
        return

    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(MatchPlayer).where(MatchPlayer.match_id == UUID(match_id))
    )
    players = result.scalars().all()
    if not players:
        await manager.broadcast(match_id, "match_end", {
            "winner_id": None, "is_draw": True, "players": []
        })
        return

    if len(players) < 2:
        solo = players[0]
        await manager.broadcast(match_id, "match_end", {
            "winner_id": str(solo.user_id),
            "is_draw": False,
            "players": [{
                "user_id": str(solo.user_id),
                "score": solo.score,
                "correct_answers": solo.correct_answers,
                "wrong_answers": solo.wrong_answers,
                "best_streak": solo.best_streak,
                "xp_earned": 0,
                "rank_points_delta": 0,
            }],
        })
        return

    # Sync wrong_answers from Redis before computing results
    await _sync_wrong_answers(match_id, players, redis)

    p0, p1 = players[0], players[1]
    is_draw = p0.correct_answers == p1.correct_answers

    if is_draw:
        await _handle_draw(match_id, p0, p1, now, db, redis)
    else:
        sorted_players = sorted(
            players,
            key=lambda p: (p.correct_answers, p.score),
            reverse=True,
        )
        await _handle_win_loss(match_id, sorted_players[0], sorted_players[-1], now, db, redis)


async def _sync_wrong_answers(match_id: str, players, redis):
    """Sync wrong_answers count from Redis into MatchPlayer objects before DB write."""
    for player in players:
        uid = str(player.user_id)
        wrong_raw = await redis.get(f"match:wrong:{match_id}:{uid}")
        if wrong_raw:
            player.wrong_answers = int(wrong_raw)


async def _handle_draw(match_id, p0, p1, now, db, redis):
    from uuid import UUID

    wp0 = (await db.execute(select(Profile).where(Profile.user_id == p0.user_id))).scalar_one_or_none()
    wp1 = (await db.execute(select(Profile).where(Profile.user_id == p1.user_id))).scalar_one_or_none()

    if wp0 and wp1:
        for player, profile in [(p0, wp0), (p1, wp1)]:
            base_xp = calculate_xp_gain(True, player.correct_answers, player.best_streak)
            draw_xp = max(1, int(base_xp * DRAW_XP_MULTIPLIER))
            profile.xp += draw_xp
            profile.total_matches += 1
            profile.total_correct += player.correct_answers
            profile.total_questions += player.correct_answers + player.wrong_answers
            profile.best_streak = max(profile.best_streak, player.best_streak)
            profile.rank_points = max(0, profile.rank_points + DRAW_RP_BONUS)
            profile.rank_tier = calculate_rank_tier(profile.rank_points)
            player.xp_earned = draw_xp
            player.rank_points_delta = DRAW_RP_BONUS

    match_res = (await db.execute(select(Match).where(Match.id == UUID(match_id)))).scalar_one_or_none()
    if match_res:
        match_res.status = MatchStatus.FINISHED
        match_res.finished_at = now
        match_res.winner_id = None

    await db.commit()

    if wp0:
        await redis.zadd("leaderboard:global", {str(p0.user_id): wp0.rank_points})
    if wp1:
        await redis.zadd("leaderboard:global", {str(p1.user_id): wp1.rank_points})

    result = await db.execute(select(MatchPlayer).where(MatchPlayer.match_id == UUID(match_id)))
    players = result.scalars().all()

    await manager.broadcast(match_id, "match_end", {
        "winner_id": None,
        "is_draw": True,
        "players": [
            {
                "user_id": str(p.user_id),
                "score": p.score,
                "correct_answers": p.correct_answers,
                "wrong_answers": p.wrong_answers,
                "best_streak": p.best_streak,
                "xp_earned": p.xp_earned,
                "rank_points_delta": p.rank_points_delta,
            }
            for p in players
        ],
    })

    await redis.hset(RedisKeys.match_state(match_id), "status", MatchStatus.FINISHED.value)
    await redis.expire(RedisKeys.match_state(match_id), 300)
    await redis.expire(f"match:questions:{match_id}", 300)


async def _handle_win_loss(match_id, winner, loser, now, db, redis):
    from uuid import UUID

    db.expire_all()
    wp = (await db.execute(select(Profile).where(Profile.user_id == winner.user_id))).scalar_one_or_none()
    lp = (await db.execute(select(Profile).where(Profile.user_id == loser.user_id))).scalar_one_or_none()

    w_xp, l_xp, w_rp, l_rp = 0, 0, 0, 0

    if wp and lp:
        w_xp = calculate_xp_gain(True, winner.correct_answers, winner.best_streak)
        l_xp = calculate_xp_gain(False, loser.correct_answers, loser.best_streak)
        w_rp = calculate_rank_points_delta(True, lp.rank_points, wp.rank_points)
        l_rp = calculate_rank_points_delta(False, wp.rank_points, lp.rank_points)

        wp.xp += w_xp; wp.wins += 1; wp.total_matches += 1
        wp.total_correct += winner.correct_answers
        wp.total_questions += winner.correct_answers + winner.wrong_answers
        wp.best_streak = max(wp.best_streak, winner.best_streak)
        wp.rank_points = max(0, wp.rank_points + w_rp)
        wp.rank_tier = calculate_rank_tier(wp.rank_points)

        lp.xp += l_xp; lp.losses += 1; lp.total_matches += 1
        lp.total_correct += loser.correct_answers
        lp.total_questions += loser.correct_answers + loser.wrong_answers
        lp.best_streak = max(lp.best_streak, loser.best_streak)
        lp.rank_points = max(0, lp.rank_points + l_rp)
        lp.rank_tier = calculate_rank_tier(lp.rank_points)

        winner.xp_earned = w_xp; winner.rank_points_delta = w_rp
        loser.xp_earned = l_xp; loser.rank_points_delta = l_rp

        logger.info(
            f"Match {match_id} result — "
            f"winner {winner.user_id}: +{w_xp}xp +{w_rp}rp | "
            f"loser {loser.user_id}: +{l_xp}xp {l_rp}rp"
        )
    else:
        logger.warning(f"Match {match_id}: profiles not found — wp={wp} lp={lp}")

    match_res = (await db.execute(select(Match).where(Match.id == UUID(match_id)))).scalar_one_or_none()
    if match_res:
        match_res.status = MatchStatus.FINISHED
        match_res.finished_at = now
        match_res.winner_id = winner.user_id

    try:
        await db.commit()
        logger.info(f"Match {match_id}: DB commit successful")
    except Exception as e:
        logger.error(f"Match {match_id}: DB commit FAILED — {e}", exc_info=True)
        await db.rollback()
        raise

    if wp:
        await redis.zadd("leaderboard:global", {str(winner.user_id): wp.rank_points})
    if lp:
        await redis.zadd("leaderboard:global", {str(loser.user_id): lp.rank_points})

    match_end_payload = {
        "winner_id": str(winner.user_id),
        "is_draw": False,
        "forfeit": False,
        "players": [
            {
                "user_id": str(winner.user_id),
                "score": winner.score,
                "correct_answers": winner.correct_answers,
                "wrong_answers": winner.wrong_answers,
                "best_streak": winner.best_streak,
                "xp_earned": w_xp,
                "rank_points_delta": w_rp,
            },
            {
                "user_id": str(loser.user_id),
                "score": loser.score,
                "correct_answers": loser.correct_answers,
                "wrong_answers": loser.wrong_answers,
                "best_streak": loser.best_streak,
                "xp_earned": l_xp,
                "rank_points_delta": l_rp,
            },
        ],
    }
    await redis.set(f"match:result:{match_id}", json.dumps(match_end_payload), ex=300)
    await manager.broadcast(match_id, "match_end", match_end_payload)

    await redis.hset(RedisKeys.match_state(match_id), "status", MatchStatus.FINISHED.value)
    await redis.expire(RedisKeys.match_state(match_id), 300)
    await redis.expire(f"match:questions:{match_id}", 300)