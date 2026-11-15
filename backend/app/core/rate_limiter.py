"""Persistent and distributed rate limiting for API keys and service endpoints."""
import time
import secrets
import logging
import threading
from typing import Dict, List, Optional, Tuple, Any
from fastapi import HTTPException, status
from backend.app.config import settings

logger = logging.getLogger("rate_limiter")

_LOCK = threading.Lock()
_KEY_REQUEST_WINDOWS: Dict[str, List[float]] = {}
_LAST_CLEANUP_TIME: float = time.time()
_REDIS_CLIENT = None
_REDIS_CHECKED = False


def _get_redis_client():
    """Lazily initialize Redis connection if configured in settings."""
    global _REDIS_CLIENT, _REDIS_CHECKED
    if _REDIS_CHECKED:
        return _REDIS_CLIENT

    if not settings.REDIS_URL:
        _REDIS_CHECKED = True
        return None

    try:
        import redis
        client = redis.from_url(settings.REDIS_URL, socket_timeout=1.5, socket_connect_timeout=1.5, decode_responses=True)
        client.ping()
        _REDIS_CLIENT = client
        logger.info(f"[RateLimiter] Connected to Redis at {settings.REDIS_URL}")
    except Exception as exc:
        logger.warning(f"[RateLimiter] Redis connection failed ({exc}); falling back to in-memory sliding window.")
        _REDIS_CLIENT = None
    finally:
        _REDIS_CHECKED = True

    return _REDIS_CLIENT


def check_api_key_rate_limit(key_id: str, limit_per_minute: int = 60) -> None:
    """Enforce per-minute sliding-window rate limit for a given API key ID.
    
    If the key exceeds limit_per_minute within the last 60 seconds, raises HTTP 429
    with a compliant 'Retry-After' header.
    
    Uses Redis atomic sorted-set sliding window when configured; falls back
    to an in-memory thread-safe sliding window with LRU memory eviction.
    """
    if limit_per_minute <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid rate limit configuration: limit_per_minute must be greater than 0.",
        )

    now = time.time()
    window_seconds = 60.0
    r_client = _get_redis_client()

    if r_client:
        try:
            r_key = f"ratelimit:apikey:{key_id}"
            pipe = r_client.pipeline()
            pipe.zremrangebyscore(r_key, "-inf", now - window_seconds)
            pipe.zcard(r_key)
            pipe.zadd(r_key, {f"{now}:{secrets.token_hex(3)}": now})
            pipe.expire(r_key, int(window_seconds) + 5)
            res = pipe.execute()
            count = res[1]

            if count >= limit_per_minute:
                # Key exceeded rate limit
                oldest_entries = r_client.zrange(r_key, 0, 0, withscores=True)
                if oldest_entries:
                    oldest_time = oldest_entries[0][1]
                    retry_after = max(1, int(window_seconds - (now - oldest_time)))
                else:
                    retry_after = int(window_seconds)

                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"API key rate limit exceeded. Maximum {limit_per_minute} requests per minute.",
                    headers={"Retry-After": str(retry_after)},
                )
            return
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning(f"[RateLimiter] Redis operation failed ({exc}); using in-memory fallback.")

    # In-memory sliding window fallback with active pruning
    global _LAST_CLEANUP_TIME
    with _LOCK:
        # Periodic eviction of stale keys every 120s to prevent memory leaks
        if now - _LAST_CLEANUP_TIME > 120.0:
            stale_keys = [
                k for k, entries in _KEY_REQUEST_WINDOWS.items()
                if not entries or (now - entries[-1]) > 300.0
            ]
            for k in stale_keys:
                del _KEY_REQUEST_WINDOWS[k]
            _LAST_CLEANUP_TIME = now

        history = _KEY_REQUEST_WINDOWS.get(key_id, [])
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


def get_rate_limiter_status() -> Dict[str, Any]:
    """Inspect current rate limiter backend and active tracking state."""
    r_client = _get_redis_client()
    return {
        "backend": "redis" if r_client is not None else "in_memory_fallback",
        "redis_configured": bool(settings.REDIS_URL),
        "in_memory_active_keys": len(_KEY_REQUEST_WINDOWS),
    }


def reset_api_key_rate_limits() -> None:
    """Clear rate limiting state (used for testing)."""
    global _REDIS_CLIENT, _REDIS_CHECKED
    with _LOCK:
        _KEY_REQUEST_WINDOWS.clear()
    r_client = _get_redis_client()
    if r_client:
        try:
            keys = r_client.keys("ratelimit:apikey:*")
            if keys:
                r_client.delete(*keys)
        except Exception:
            pass
