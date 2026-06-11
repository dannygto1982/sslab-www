"""Simple rate limiter — sliding window, in-memory, no external dependencies."""
import time
from collections import defaultdict
from fastapi import Request, HTTPException


class RateLimiter:
    """Token-bucket-inspired rate limiter with sliding window."""

    def __init__(self, max_requests: int = 60, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._clients: dict[str, list[float]] = defaultdict(list)

    def _clean(self, client_id: str, now: float) -> None:
        cutoff = now - self.window_seconds
        self._clients[client_id] = [
            t for t in self._clients[client_id] if t > cutoff
        ]

    def is_allowed(self, client_id: str) -> bool:
        now = time.time()
        self._clean(client_id, now)
        if len(self._clients[client_id]) >= self.max_requests:
            return False
        self._clients[client_id].append(now)
        return True

    async def __call__(self, request: Request):
        client_id = request.client.host if request.client else "unknown"
        if not self.is_allowed(client_id):
            raise HTTPException(status_code=429, detail="Too many requests")
        return True


# Pre‑built limiters
public_limiter = RateLimiter(max_requests=30, window_seconds=60)  # 30 req/min
auth_limiter = RateLimiter(max_requests=120, window_seconds=60)  # 120 req/min
admin_limiter = RateLimiter(max_requests=300, window_seconds=60)  # 300 req/min
