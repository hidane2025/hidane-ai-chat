"""Thread-safe in-memory rate limiter for Hidane AI chat system."""

import threading
import time
from functools import wraps

from flask import request, jsonify


class RateLimiter:
    """Thread-safe in-memory rate limiter with auto-cleanup."""

    def __init__(self):
        self._lock = threading.Lock()
        self._requests = {}  # key -> list of timestamps

    def is_allowed(self, key, max_requests, window_seconds):
        """Check if request is allowed. Returns (allowed: bool, remaining: int)."""
        now = time.time()
        cutoff = now - window_seconds

        with self._lock:
            timestamps = self._requests.get(key, [])
            # Immutable: create filtered list instead of mutating
            valid = [ts for ts in timestamps if ts > cutoff]

            if len(valid) >= max_requests:
                return False, 0

            updated = [*valid, now]
            # Immutable: create new dict instead of mutating
            self._requests = {**self._requests, key: updated}
            return True, max_requests - len(updated)

    def cleanup(self, max_age_seconds=300):
        """Remove all entries older than max_age_seconds."""
        now = time.time()
        cutoff = now - max_age_seconds

        with self._lock:
            cleaned = {}
            for key, timestamps in self._requests.items():
                valid = [ts for ts in timestamps if ts > cutoff]
                if valid:
                    cleaned[key] = valid
            self._requests = cleaned


# Global instance
_limiter = RateLimiter()


def rate_limit(max_requests=30, window_seconds=60):
    """Flask decorator for rate limiting.

    Defaults: 30 requests per 60 seconds.
    Use max_requests=5 for auth endpoints.
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            key = f"{request.remote_addr}:{f.__name__}"
            allowed, remaining = _limiter.is_allowed(key, max_requests, window_seconds)

            if not allowed:
                # Auto-cleanup on rejection to free memory
                _limiter.cleanup()
                return jsonify({
                    "error": "Rate limit exceeded",
                    "retry_after_seconds": window_seconds,
                }), 429

            response = f(*args, **kwargs)
            return response
        return decorated
    return decorator
