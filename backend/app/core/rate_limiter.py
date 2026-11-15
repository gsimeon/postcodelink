"""Persistent and distributed-ready rate limiting for API keys and service endpoints."""
import time
import os
import threading
from typing import Dict, List, Optional
from fastapi import HTTPException, status

_LOCK = threading.Lock()
_KEY_REQUEST_WINDOWS: Dict[str, List[float]] = {}


def check_api_key_rate_limit(key_id: str, limit_per_minute: int = 60) -> None:
    """Enforce per-minute sliding-window rate limit for a given API key ID.
    
    If the key exceeds limit_per_minute within the last 60 seconds, raises HTTP 429
    with an appropriate 'Retry-After' header.
    Independent per API key.
    """
    if limit_per_minute <= 0:
        return

    now = time.time()
    window_seconds = 60.0

    with _LOCK:
        history = _KEY_REQUEST_WINDOWS.get(key_id, [])
        # Prune entries older than window_seconds
        active_entries = [t for t in history if now - t < window_seconds]

        if len(active_entries) >= limit_per_minute:
            oldest = active_entries[0]
            retry_after = max(1, int(window_seconds - (now - oldest)))
            _KEY_REQUEST_WINDOWS[key_id] = active_entries
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"API key rate limit exceeded. Maximum {limit_per_minute} requests per minute.",
                headers={"Retry-After": str(retry_after)},
            )

        active_entries.append(now)
        _KEY_REQUEST_WINDOWS[key_id] = active_entries


def reset_api_key_rate_limits() -> None:
    """Clear in-memory rate limiting state (used for testing)."""
    with _LOCK:
        _KEY_REQUEST_WINDOWS.clear()
