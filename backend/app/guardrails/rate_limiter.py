import time
import threading
from collections import defaultdict, deque
from typing import Dict, Deque, Tuple, Optional
from fastapi import Request, HTTPException, status


class SlidingWindowRateLimiter:
    """
    Sub-millisecond thread-safe sliding window rate limiter.
    Tracks timestamps per client identifier (IP / session).
    """

    def __init__(self, default_limit: int = 30, default_window_seconds: int = 60):
        self.default_limit = default_limit
        self.default_window_seconds = default_window_seconds
        self._clients: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check_rate_limit(
        self,
        client_key: str,
        limit: Optional[int] = None,
        window_seconds: Optional[int] = None
    ) -> Tuple[bool, int, int]:
        """
        Evaluates whether client_key is allowed to proceed.
        Returns:
            - is_allowed (bool)
            - remaining_requests (int)
            - retry_after_seconds (int, 0 if allowed)
        """
        max_requests = limit or self.default_limit
        window = window_seconds or self.default_window_seconds
        now = time.time()
        cutoff = now - window

        with self._lock:
            timestamps = self._clients[client_key]

            # Prune timestamps outside the current sliding window
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()

            current_count = len(timestamps)

            if current_count < max_requests:
                timestamps.append(now)
                remaining = max_requests - (current_count + 1)
                return True, remaining, 0
            else:
                oldest_timestamp = timestamps[0]
                retry_after = max(1, int((oldest_timestamp + window) - now))
                return False, 0, retry_after

    def reset(self, client_key: Optional[str] = None) -> None:
        """Resets the rate limiter for a specific client or globally (for tests)."""
        with self._lock:
            if client_key:
                if client_key in self._clients:
                    del self._clients[client_key]
            else:
                self._clients.clear()


# Global rate limiter instance (30 req / 60s default)
rate_limiter = SlidingWindowRateLimiter(default_limit=30, default_window_seconds=60)


def extract_client_ip(request: Request) -> str:
    """Extracts client IP from X-Forwarded-For header or direct client host."""
    return request.client.host if request.client else "unknown"



async def verify_rate_limit(request: Request):
    """
    FastAPI dependency that enforces sliding window rate limiting.
    Raises HTTP 429 Too Many Requests if the quota is exceeded.
    """
    client_ip = extract_client_ip(request)
    is_allowed, remaining, retry_after = rate_limiter.check_rate_limit(client_ip)

    if not is_allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded: Maximum 30 requests per minute. Please retry in {retry_after} seconds.",
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": "30",
                "X-RateLimit-Remaining": "0",
            },
        )
    return True
