"""
Rate limiting (tiêu chí 7).

• Mỗi API key tối đa RATE_LIMIT_PER_MINUTE request trong 60 giây (sliding window)
• Vượt giới hạn → HTTP 429 kèm header Retry-After
• State lưu trong Redis bằng Sorted Set (ZREMRANGEBYSCORE → ZCARD → ZADD → EXPIRE)
  để mọi worker/instance dùng chung và giữ nguyên state sau khi restart agent.
"""
import hashlib
import logging
import time
import uuid
from collections import defaultdict, deque

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

logger = logging.getLogger("app.rate_limiter")
WINDOW_SECONDS = 60
_fallback_windows: dict[str, deque[float]] = defaultdict(deque)


def _key_hash(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]


def check_rate_limit(key: str) -> None:
    limit = settings.rate_limit_per_minute
    now = time.time()
    window_start = now - WINDOW_SECONDS
    redis_key = f"ratelimit:{_key_hash(key)}"

    try:
        r.zremrangebyscore(redis_key, "-inf", window_start)
        current_count = r.zcard(redis_key)

        if current_count >= limit:
            oldest_entries = r.zrange(redis_key, 0, 0, withscores=True)
            oldest_ts = float(oldest_entries[0][1]) if oldest_entries else now
            retry_after = max(1, int(oldest_ts + WINDOW_SECONDS - now) + 1)
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded ({limit} requests per {WINDOW_SECONDS}s)",
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                },
            )

        member = f"{now:.6f}:{uuid.uuid4().hex[:8]}"
        r.zadd(redis_key, {member: now})
        r.expire(redis_key, WINDOW_SECONDS + 5)
    except redis.RedisError as exc:
        logger.warning("Redis unavailable in rate_limiter, using local fallback", extra={"error": str(exc)})
        dq = _fallback_windows[redis_key]
        while dq and dq[0] <= window_start:
            dq.popleft()
        if len(dq) >= limit:
            retry_after = max(1, int(dq[0] + WINDOW_SECONDS - now) + 1)
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded ({limit} requests per {WINDOW_SECONDS}s)",
                headers={"Retry-After": str(retry_after)},
            )
        dq.append(now)
