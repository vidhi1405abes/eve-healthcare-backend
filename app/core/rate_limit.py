import threading
import time
from collections import defaultdict, deque

from fastapi import Request

from app.core.config import settings
from app.core.exceptions import RateLimitError


class RateLimiter:
    def __init__(self, limit: int, window_seconds: int = 60, enabled: bool = True):
        self.limit = limit
        self.window_seconds = window_seconds
        self.enabled = enabled
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        if not self.enabled:
            return
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self.window_seconds:
                hits.popleft()
            if len(hits) >= self.limit:
                retry_after = max(1, int(self.window_seconds - (now - hits[0])))
                raise RateLimitError(
                    "Too many requests, please try again later.", headers={"Retry-After": str(retry_after)}
                )
            hits.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


auth_limiter = RateLimiter(settings.rate_limit_auth_per_minute, enabled=settings.rate_limit_enabled)


def limit_auth_requests(request: Request) -> None:
    auth_limiter.check(request.client.host if request.client else "unknown")
