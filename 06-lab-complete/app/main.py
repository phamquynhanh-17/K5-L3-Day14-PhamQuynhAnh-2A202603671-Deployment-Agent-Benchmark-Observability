"""
Production AI Agent — Part 6 Final Project.

Đáp ứng đầy đủ 12 tiêu chí Production Readiness:
  • GET /health (liveness) & GET /ready (readiness kiểm tra Redis)
  • Xác thực API Key (X-API-Key → 401)
  • Rate limiting lưu trong Redis (429 + Retry-After)
  • Cost guard lưu trong Redis (402)
  • Config đọc từ biến môi trường (12-Factor)
  • Structured JSON logging
  • Graceful shutdown qua lifespan (hoàn thành in-flight requests khi nhận SIGTERM)
"""
import asyncio
import json
import logging
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import redis_healthy
from utils.mock_llm import ask as llm_ask


class JsonFormatter(logging.Formatter):
    """Định dạng mọi dòng log của ứng dụng thành một JSON object hợp lệ trên 1 dòng."""

    _RESERVED = {
        "args", "asctime", "created", "exc_info", "exc_text", "filename",
        "funcName", "levelname", "levelno", "lineno", "module", "msecs",
        "message", "msg", "name", "pathname", "process", "processName",
        "relativeCreated", "stack_info", "thread", "threadName", "taskName",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "lvl": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, val in record.__dict__.items():
            if key not in self._RESERVED and not key.startswith("_"):
                payload[key] = val
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def _setup_logging() -> logging.Logger:
    app_logger = logging.getLogger("app")
    app_logger.setLevel(getattr(logging, settings.log_level, logging.INFO))
    app_logger.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    app_logger.addHandler(handler)
    app_logger.propagate = False
    return app_logger


logger = _setup_logging()

START_TIME = time.time()
_is_ready = False
_in_flight_requests = 0


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _is_ready
    _is_ready = True
    logger.info(
        "agent_startup",
        extra={
            "event": "startup",
            "environment": settings.environment,
            "port": settings.port,
        },
    )
    yield
    _is_ready = False
    logger.info(
        "agent_shutdown_initiated",
        extra={"event": "shutdown_start", "in_flight": _in_flight_requests},
    )
    deadline = time.time() + 15.0
    while _in_flight_requests > 0 and time.time() < deadline:
        await asyncio.sleep(0.05)
    logger.info("agent_shutdown_complete", extra={"event": "shutdown_complete"})


app = FastAPI(
    title="Production AI Agent",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.environment != "production" else None,
)


@app.middleware("http")
async def track_and_log_requests(request: Request, call_next):
    global _in_flight_requests
    request_id = request.headers.get("X-Request-ID", uuid.uuid4().hex[:12])
    started = time.perf_counter()
    _in_flight_requests += 1
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        _in_flight_requests -= 1
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.info(
            "http_request",
            extra={
                "event": "request",
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": status_code,
                "ms": elapsed_ms,
            },
        )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error(
        "unhandled_error",
        extra={"event": "error", "path": request.url.path, "error_type": type(exc).__name__},
    )
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = Field(default="anonymous", max_length=128)


@app.get("/health")
def health():
    """Liveness probe — luôn trả 200 khi process còn sống, không phụ thuộc Redis."""
    return {
        "status": "ok",
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "environment": settings.environment,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/ready")
def ready():
    """Readiness probe — trả 200 khi sẵn sàng, 503 khi đang tắt hoặc mất kết nối Redis."""
    if not _is_ready or not redis_healthy():
        raise HTTPException(status_code=503, detail="Service not ready: Redis unavailable")
    return {
        "status": "ready",
        "ready": True,
        "in_flight_requests": _in_flight_requests,
    }


@app.post("/ask")
async def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    check_rate_limit(api_key)
    check_budget()

    answer = await asyncio.to_thread(llm_ask, body.question)

    input_tokens = max(1, len(body.question) // 4)
    output_tokens = max(1, len(answer) // 4)
    cost_usd = record_cost(input_tokens, output_tokens)

    logger.info(
        "llm_call",
        extra={
            "event": "llm_call",
            "user_id": body.user_id,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": round(cost_usd, 8),
        },
    )

    return {
        "question": body.question,
        "answer": answer,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": round(cost_usd, 8),
        },
    }
