


#router.py
from fastapi import APIRouter
from app.api.v1.endpoints import auth, users, matchmaking, leaderboard

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(matchmaking.router)
api_router.include_router(leaderboard.router)

# Uncomment as steps are completed:
# api_router.include_router(matches.router)


