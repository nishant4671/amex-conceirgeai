import logging
from typing import Optional
import redis.asyncio as aioredis
from langgraph.checkpoint.redis import AsyncRedisSaver
from app.core.config import settings

logger = logging.getLogger("redis_client")

# Global variables for redis client and checkpointer
redis_pool: Optional[aioredis.ConnectionPool] = None
redis_client: Optional[aioredis.Redis] = None
redis_checkpointer: Optional[AsyncRedisSaver] = None


async def init_redis() -> None:
    """Initialize Redis connection pool, client, and checkpointer."""
    global redis_pool, redis_client, redis_checkpointer
    try:
        redis_pool = aioredis.ConnectionPool.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            max_connections=20,
        )
        redis_client = aioredis.Redis(connection_pool=redis_pool)
        
        # AsyncRedisSaver checkpointer for LangGraph state persistence
        redis_checkpointer = AsyncRedisSaver(redis_client)
        
        # Verify connection
        await redis_client.ping()
        logger.info("Redis connection verified successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize Redis: {e}")
        raise e


async def close_redis() -> None:
    """Close Redis connection pool."""
    global redis_pool, redis_client
    if redis_pool:
        await redis_pool.disconnect()
        logger.info("Redis connection pool closed.")


async def verify_redis_connection() -> bool:
    """Verify connection to Redis on startup/healthcheck."""
    global redis_client
    if not redis_client:
        return False
    try:
        await redis_client.ping()
        return True
    except Exception as e:
        logger.error(f"Redis connection verification failed: {e}")
        return False
