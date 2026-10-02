import logging
import time
import uuid

from fastapi import Request

from app.core.logging import request_id_ctx

logger = logging.getLogger("app.request")


async def request_context_middleware(request: Request, call_next):
    request_id = (request.headers.get("X-Request-ID") or uuid.uuid4().hex)[:64]
    request.state.request_id = request_id
    token = request_id_ctx.set(request_id)
    started = time.perf_counter()
    try:
        response = await call_next(request)
        logger.info(
            "request_completed",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            },
        )
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        request_id_ctx.reset(token)
