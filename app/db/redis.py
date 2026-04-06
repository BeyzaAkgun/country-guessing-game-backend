#redis.py
import redis.asyncio as aioredis
from app.core.config import settings

# Build connection kwargs — ssl_cert_reqs only needed for TLS (Upstash/production)
_pool_kwargs: dict = {
    "encoding": "utf-8",
    "decode_responses": True,
    "max_connections": 20,
}

# Only add ssl_cert_reqs when connecting via rediss:// (TLS)
if settings.redis_url.startswith("rediss://"):
    _pool_kwargs["ssl_cert_reqs"] = None

redis_pool = aioredis.ConnectionPool.from_url(
    settings.redis_url,
    **_pool_kwargs,
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