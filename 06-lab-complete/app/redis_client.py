"""
Kết nối Redis dùng chung cho rate limiter và cost guard.

• Đọc REDIS_URL từ config
• Không ping Redis lúc import để app vẫn khởi động được khi chưa có Redis
• redis_healthy() dùng cho GET /ready: mất kết nối Redis → False
"""
import redis

from app.config import settings

r = redis.from_url(
    settings.redis_url or "redis://localhost:6379/0",
    decode_responses=True,
    socket_connect_timeout=1.5,
    socket_timeout=1.5,
)


def redis_healthy() -> bool:
    """Kiểm tra kết nối tới Redis cho readiness probe (/ready)."""
    if not settings.redis_url:
        return False
    try:
        return bool(r.ping())
    except (redis.RedisError, OSError, ValueError):
        return False
