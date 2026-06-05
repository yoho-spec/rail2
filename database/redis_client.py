"""
database/redis_client.py
Redis (Upstash) connection — used for:
  - Job queues
  - Rate limiting
  - Subscription check cache (don't hit Telegram API every message)
  - Temporary state (OTP flows, pending jobs)
"""
import logging
import json
import os
from redis.asyncio import Redis
from config.settings import settings

logger = logging.getLogger(__name__)

redis: Redis = None  # Import this everywhere: from database.redis_client import redis


async def init_redis():
    global redis
    # Debug: print the actual REDIS_URL value
    redis_url = settings.REDIS_URL
    logger.info(f"DEBUG: REDIS_URL = {redis_url}")
    logger.info(f"DEBUG: REDIS_URL type = {type(redis_url)}")
    logger.info(f"DEBUG: REDIS_URL length = {len(redis_url) if redis_url else 0}")
    
    redis = Redis.from_url(
        redis_url,
        decode_responses=True,
        socket_timeout=5,
        socket_connect_timeout=5,
    )
    await redis.ping()
    logger.info("✅ Redis connected")


async def close_redis():
    if redis:
        await redis.close()


# ── Rate limiting ──

async def check_rate_limit(user_id: int, action: str, limit: int, window_seconds: int) -> bool:
    """
    Returns True if user is within limit, False if exceeded.
    Uses sliding window counter in Redis.
    """
    key = f"ratelimit:{user_id}:{action}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, window_seconds)
    return count <= limit


# ── Subscription check cache ──

SUBSCRIPTION_CACHE_TTL = 300  # 5 minutes


async def cache_subscription_status(user_id: int, channel_id: str, is_member: bool):
    key = f"sub:{user_id}:{channel_id}"
    await redis.setex(key, SUBSCRIPTION_CACHE_TTL, "1" if is_member else "0")


async def get_cached_subscription(user_id: int, channel_id: str) -> bool | None:
    key = f"sub:{user_id}:{channel_id}"
    val = await redis.get(key)
    if val is None:
        return None
    return val == "1"


# ── Temporary state (login flows, etc.) ──

async def set_temp_state(user_id: int, key: str, value: dict, ttl: int = 600):
    """Store temporary state for a user (expires in ttl seconds)."""
    redis_key = f"state:{user_id}:{key}"
    await redis.setex(redis_key, ttl, json.dumps(value))


async def get_temp_state(user_id: int, key: str) -> dict | None:
    redis_key = f"state:{user_id}:{key}"
    val = await redis.get(redis_key)
    return json.loads(val) if val else None


async def delete_temp_state(user_id: int, key: str):
    redis_key = f"state:{user_id}:{key}"
    await redis.delete(redis_key)


# ── Job queue (simple list-based queue) ──

async def enqueue_job(queue_name: str, job_data: dict):
    await redis.rpush(f"queue:{queue_name}", json.dumps(job_data))


async def dequeue_job(queue_name: str) -> dict | None:
    val = await redis.lpop(f"queue:{queue_name}")
    return json.loads(val) if val else None


async def get_queue_length(queue_name: str) -> int:
    return await redis.llen(f"queue:{queue_name}")

