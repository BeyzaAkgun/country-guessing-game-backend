#redis.py
import redis.asyncio as aioredis
from app.core.config import settings

redis_pool = aioredis.ConnectionPool.from_url(
    settings.redis_url,
    encoding="utf-8",
    decode_responses=True,
    max_connections=20,
)


def get_redis() -> aioredis.Redis:
    return aioredis.Redis(connection_pool=redis_pool)


class RedisKeys:
    LEADERBOARD  = "leaderboard:global"
    MATCH_QUEUE  = "matchmaking:queue"

    @staticmethod
    def match_state(match_id: str) -> str:
        return f"match:state:{match_id}"

    @staticmethod
    def room_state(room_code: str) -> str:
        return f"room:state:{room_code}"

    @staticmethod
    def room_players(room_code: str) -> str:
        return f"room:players:{room_code}"