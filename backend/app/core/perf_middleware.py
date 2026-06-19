"""Request timing middleware — logs API performance and captures diagnostics."""
from __future__ import annotations

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.api_error_buffer import record_request
from app.core.query_profiler import begin_request, end_request

logger = logging.getLogger(__name__)

_SLOW_MS = 1000


class RequestTimingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.perf_counter()
        status_code = 500
        error_summary: str | None = None
        path = request.url.path
        method = request.method

        if path.startswith("/api/"):
            begin_request(method, path)

        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception as exc:
            error_summary = str(exc)[:500]
            raise
        finally:
            duration_ms = int((time.perf_counter() - start) * 1000)
            if path.startswith("/api/"):
                perf_line = (
                    f"[API PERF] method={method} path={path} "
                    f"status={status_code} duration_ms={duration_ms}"
                )
                logger.info(perf_line)

                if duration_ms > _SLOW_MS:
                    logger.warning(
                        "[API SLOW] method=%s path=%s status=%s duration_ms=%s",
                        method,
                        path,
                        status_code,
                        duration_ms,
                    )

                if status_code >= 500:
                    logger.error(
                        "[API ERROR] method=%s path=%s status=%s duration_ms=%s error=%s",
                        method,
                        path,
                        status_code,
                        duration_ms,
                        error_summary or "HTTP error",
                    )

                record_request(
                    method=method,
                    path=path,
                    status=status_code,
                    duration_ms=duration_ms,
                    error_summary=error_summary,
                )
                end_request(method, path, duration_ms)
