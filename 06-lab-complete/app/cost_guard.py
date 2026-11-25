"""
Cost guard (tiêu chí 8).

• Cộng dồn chi phí LLM (tính theo token) vào Redis
• Tổng chi phí vượt DAILY_BUDGET_USD hoặc MONTHLY_BUDGET_USD → HTTP 402
"""
import logging
from datetime import datetime, timezone

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

logger = logging.getLogger("app.cost_guard")

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006

_fallback_spend: dict[str, float] = {}


def _budget_keys() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    return f"cost:daily:{now.strftime('%Y-%m-%d')}", f"cost:monthly:{now.strftime('%Y-%m')}"


def check_budget() -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → raise HTTPException(status_code=402)."""
    daily_key, monthly_key = _budget_keys()
    try:
        daily_raw, monthly_raw = r.mget(daily_key, monthly_key)
        daily_spent = float(daily_raw or 0.0)
        monthly_spent = float(monthly_raw or 0.0)
    except redis.RedisError as exc:
        logger.warning("Redis unavailable in check_budget, using local fallback", extra={"error": str(exc)})
        daily_spent = _fallback_spend.get(daily_key, 0.0)
        monthly_spent = _fallback_spend.get(monthly_key, 0.0)

    if daily_spent >= settings.daily_budget_usd:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "Daily budget exceeded",
                "daily_spent_usd": round(daily_spent, 8),
                "daily_budget_usd": settings.daily_budget_usd,
            },
        )
    if monthly_spent >= settings.monthly_budget_usd:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "Monthly budget exceeded",
                "monthly_spent_usd": round(monthly_spent, 8),
                "monthly_budget_usd": settings.monthly_budget_usd,
            },
        )


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí của request vào tổng, trả về chi phí request."""
    cost = (input_tokens / 1000.0) * PRICE_INPUT_PER_1K + (output_tokens / 1000.0) * PRICE_OUTPUT_PER_1K
    daily_key, monthly_key = _budget_keys()
    try:
        r.incrbyfloat(daily_key, cost)
        r.expire(daily_key, 2 * 24 * 3600)
        r.incrbyfloat(monthly_key, cost)
        r.expire(monthly_key, 35 * 24 * 3600)
    except redis.RedisError as exc:
        logger.warning("Redis unavailable in record_cost, using local fallback", extra={"error": str(exc)})
        _fallback_spend[daily_key] = _fallback_spend.get(daily_key, 0.0) + cost
        _fallback_spend[monthly_key] = _fallback_spend.get(monthly_key, 0.0) + cost
    return cost
