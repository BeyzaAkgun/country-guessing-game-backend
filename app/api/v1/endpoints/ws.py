#ws.py
# from fastapi import APIRouter, WebSocket, Query
# from sqlalchemy.ext.asyncio import AsyncSession
# from sqlalchemy import select
# from jose import JWTError
# from uuid import UUID

# from app.db.base import AsyncSessionLocal
# from app.core.security import decode_token
# from app.models.match import Match, MatchPlayer
# from app.ws.game import handle_game_connection

# router = APIRouter(tags=["websocket"])


# @router.websocket("/ws/match/{match_id}")
# async def match_websocket(
#     match_id: str,
#     websocket: WebSocket,
#     token: str = Query(...),
# ):
#     async with AsyncSessionLocal() as db:
#         # Authenticate
#         try:
#             payload = decode_token(token)
#             if payload.get("type") != "access":
#                 print(f"DEBUG WS: wrong token type: {payload.get('type')}")
#                 await websocket.close(code=4001)
#                 return
#             user_id = payload.get("sub")
#             if not user_id:
#                 print("DEBUG WS: no user_id in token")
#                 await websocket.close(code=4001)
#                 return
#         except JWTError as e:
#             print(f"DEBUG WS: JWTError: {e}")
#             await websocket.close(code=4001)
#             return

#         print(f"DEBUG WS: auth ok, user_id={user_id}, match_id={match_id}")

#         # Verify this user is a player in this match
#         try:
#             match_uuid = UUID(match_id)
#             user_uuid = UUID(user_id)
#         except ValueError as e:
#             print(f"DEBUG WS: UUID parse error: {e}")
#             await websocket.close(code=4001)
#             return

#         result = await db.execute(
#             select(MatchPlayer).where(
#                 MatchPlayer.match_id == match_uuid,
#                 MatchPlayer.user_id == user_uuid,
#             )
#         )
#         player = result.scalar_one_or_none()
#         print(f"DEBUG WS: player lookup result: {player}")

#         if not player:
#             print(f"DEBUG WS: player not found for user={user_id} match={match_id}")
#             await websocket.accept()
#             await websocket.close(code=4403)
#             return

#         print(f"DEBUG WS: player found, proceeding to game handler")
#         await handle_game_connection(websocket, match_id, user_id, db)




# #ws.py
# from fastapi import APIRouter, WebSocket, Query
# from sqlalchemy.ext.asyncio import AsyncSession
# from sqlalchemy import select
# from jose import JWTError
# from uuid import UUID

# from app.db.base import AsyncSessionLocal
# from app.core.security import decode_token
# from app.models.match import Match, MatchPlayer
# from app.ws.game import handle_game_connection

# router = APIRouter(tags=["websocket"])


# @router.websocket("/ws/match/{match_id}")
# async def match_websocket(
#     match_id: str,
#     websocket: WebSocket,
#     token: str = Query(...),
# ):
#     async with AsyncSessionLocal() as db:
#         try:
#             payload = decode_token(token)
#             if payload.get("type") != "access":
#                 print(f"DEBUG WS: wrong token type: {payload.get('type')}")
#                 await websocket.close(code=4001)
#                 return
#             user_id = payload.get("sub")
#             if not user_id:
#                 print("DEBUG WS: no user_id in token")
#                 await websocket.close(code=4001)
#                 return
#         except JWTError as e:
#             print(f"DEBUG WS: JWTError: {e}")
#             await websocket.close(code=4001)
#             return

#         print(f"DEBUG WS: auth ok, user_id={user_id}, match_id={match_id}")

#         try:
#             match_uuid = UUID(match_id)
#             user_uuid = UUID(user_id)
#         except ValueError as e:
#             print(f"DEBUG WS: UUID parse error: {e}")
#             await websocket.close(code=4001)
#             return

#         result = await db.execute(
#             select(MatchPlayer).where(
#                 MatchPlayer.match_id == match_uuid,
#                 MatchPlayer.user_id == user_uuid,
#             )
#         )
#         player = result.scalar_one_or_none()
#         print(f"DEBUG WS: player lookup result: {player}")

#         if not player:
#             print(f"DEBUG WS: player not found for user={user_id} match={match_id}")
#             await websocket.accept()
#             await websocket.close(code=4403)
#             return

#         print(f"DEBUG WS: player found, proceeding to game handler")
#         await handle_game_connection(websocket, match_id, user_id, db)




# ws.py
from fastapi import APIRouter, WebSocket, Query
from sqlalchemy import select
from jose import JWTError
from uuid import UUID

from app.db.base import AsyncSessionLocal
from app.core.security import decode_token
from app.models.match import MatchPlayer
from app.ws.game import handle_game_connection

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/match/{match_id}")
async def match_websocket(
    match_id: str,
    websocket: WebSocket,
    token: str = Query(...),
):
    # ── Auth — no DB needed here
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            print(f"DEBUG WS: wrong token type: {payload.get('type')}")
            await websocket.close(code=4001)
            return
        user_id = payload.get("sub")
        if not user_id:
            print("DEBUG WS: no user_id in token")
            await websocket.close(code=4001)
            return
    except JWTError as e:
        print(f"DEBUG WS: JWTError: {e}")
        await websocket.close(code=4001)
        return

    print(f"DEBUG WS: auth ok, user_id={user_id}, match_id={match_id}")

    try:
        match_uuid = UUID(match_id)
        user_uuid = UUID(user_id)
    except ValueError as e:
        print(f"DEBUG WS: UUID parse error: {e}")
        await websocket.close(code=4001)
        return

    # ── Validate player in a short-lived session, then close it immediately.
    # This is the critical fix: the session must NOT be held open across the
    # WebSocket lifetime, because pgbouncer (transaction/statement pool mode)
    # invalidates prepared statement IDs when it recycles connections between
    # transactions. Keeping a session open for minutes causes the
    # "prepared statement does not exist" crash on the second match.
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(MatchPlayer).where(
                MatchPlayer.match_id == match_uuid,
                MatchPlayer.user_id == user_uuid,
            )
        )
        player = result.scalar_one_or_none()
        print(f"DEBUG WS: player lookup result: {player}")
    # Session closed here — pgbouncer can recycle the connection freely.

    if not player:
        print(f"DEBUG WS: player not found for user={user_id} match={match_id}")
        await websocket.accept()
        await websocket.close(code=4403)
        return

    print(f"DEBUG WS: player found, proceeding to game handler")

    # handle_game_connection no longer receives a db session.
    # It opens its own short-lived sessions per operation.
    await handle_game_connection(websocket, match_id, user_id)