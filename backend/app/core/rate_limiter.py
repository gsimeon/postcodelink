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
_LAST_CONNECT_ATTEMPT: float = 0.0
_CONNECT_BACKOFF_SECONDS: float = 15.0

# Redis Lua Script for atomic sliding-window rate limiting
# Guarantees atomic count-and-add: rejected requests are NEVER added to the sorted set
LUA_SLIDING_WINDOW_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member_suffix = ARGV[4]

-- 1. Remove expired entries older than (now - window)
local clear_before = now - window
redis.call('ZREMRANGEBYSCORE', key, '-inf', clear_before)

-- 2. Count active requests within current window
local current_count = redis.call('ZCARD', key)

-- 3. Evaluate allowance
if current_count < limit then
    -- Allowed: record timestamp and set TTL
    local member = tostring(now) .. ':' .. member_suffix
    redis.call('ZADD', key, now, member)
    redis.call('EXPIRE', key, math.ceil(window) + 5)
    return {1, limit - current_count - 1, 0}
else
    -- Rejected: DO NOT add to sorted set! (Prevents throttling cascade)
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    local retry_after = 1
    if oldest and #oldest >= 2 then
        local oldest_time = tonumber(oldest[2])
        retry_after = math.ceil(window - (now - oldest_time))
        if retry_after < 1 then retry_after = 1 end
    else
        retry_after = math.ceil(window)
    end
    return {0, 0, retry_after}
end
"""


def _get_redis_client():
    """Get active Redis client with bounded backoff retry on failure."""
    global _REDIS_CLIENT, _LAST_CONNECT_ATTEMPT

    if not settings.REDIS_URL:
        return None

    now = time.time()
    with _LOCK:
        if _REDIS_CLIENT is not None:
            return _REDIS_CLIENT

        if now - _LAST_CONNECT_ATTEMPT < _CONNECT_BACKOFF_SECONDS:
            return None

        _LAST_CONNECT_ATTEMPT = now
        try:
            import redis
            client = redis.from_url(
                settings.REDIS_URL,
                socket_timeout=1.5,
                socket_connect_timeout=1.5,
                decode_responses=True,
            )
            client.ping()
            _REDIS_CLIENT = client
            logger.info(f"[RateLimiter] Successfully connected to Redis at {settings.REDIS_URL}")
            return _REDIS_CLIENT
        except Exception as exc:
            logger.warning(
                f"[RateLimiter ALERT] Redis connection attempt failed ({exc}). "
                f"Retrying after {_CONNECT_BACKOFF_SECONDS}s backoff."
            )
            _REDIS_CLIENT = None
            return None


def _handle_redis_failure():
    """Handle runtime Redis failure by clearing active client for backoff retry."""
    global _REDIS_CLIENT, _LAST_CONNECT_ATTEMPT
    with _LOCK:
        _REDIS_CLIENT = None
        _LAST_CONNECT_ATTEMPT = time.time()


def check_api_key_rate_limit(key_id: str, limit_per_minute: int = 60) -> None:
    """Enforce per-minute sliding-window rate limit for a given API key ID.
    
    If the key exceeds limit_per_minute within the last 60 seconds, raises HTTP 429
    with a compliant 'Retry-After' header.
    
    Uses Redis atomic Lua sliding window when available; conditionally adds entries
    only when permitted. Enforces fail-closed or in-memory fallback policy when Redis is unavailable.
    """
    if limit_per_minute <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid rate limit configuration: limit_per_minute must be greater than 0.",
        )

    now = time.time()
    window_seconds = 60.0
    r_client = _get_redis_client()

    if r_client is not None:
        try:
            r_key = f"ratelimit:apikey:{key_id}"
            suffix = secrets.token_hex(4)
            # Run atomic Lua script
            res = r_client.eval(
                LUA_SLIDING_WINDOW_SCRIPT,
                1,
                r_key,
                str(now),
                str(window_seconds),
                str(limit_per_minute),
                suffix,
            )
            allowed = int(res[0])
            retry_after = int(res[2])

            if allowed == 0:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"API key rate limit exceeded. Maximum {limit_per_minute} requests per minute.",
                    headers={"Retry-After": str(retry_after)},
                )
            return
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning(f"[RateLimiter ALERT] Redis Lua operation failed: {exc}")
            _handle_redis_failure()

    # Fail-closed policy enforcement in production
    # In multi-instance production: strictly fail closed with HTTP 503 unless explicit single-instance opt-out is enabled
    allow_in_memory = getattr(settings, "ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION", False)
    fail_closed = getattr(settings, "RATE_LIMIT_REDIS_FAIL_CLOSED", True)
    if settings.ENVIRONMENT == "production" and fail_closed and not allow_in_memory:
        logger.error("[RateLimiter CRITICAL] Redis is unavailable and RATE_LIMIT_REDIS_FAIL_CLOSED is enabled. Failing closed.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Distributed rate limiter service is temporarily unavailable. Fail-closed policy in effect.",
        )

    # In-memory sliding window fallback with active memory eviction
    if settings.ENVIRONMENT == "production":
        logger.warning("[RateLimiter ALERT] Production API is operating on process-local in-memory rate limiter fallback.")

    global _LAST_CLEANUP_TIME
    with _LOCK:
        # Periodic eviction of stale keys every 120s to prevent memory accumulation
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
            # Reject request without adding to active entries (prevents penalty cascade)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"API key rate limit exceeded. Maximum {limit_per_minute} requests per minute.",
                headers={"Retry-After": str(retry_after)},
            )

        active_entries.append(now)
        _KEY_REQUEST_WINDOWS[key_id] = active_entries


def check_client_ip_rate_limit(client_ip: str, limit_per_minute: int = 15) -> None:
    """Enforce per-minute sliding-window rate limit for unauthenticated public demonstration requests by IP.
    
    If the IP exceeds limit_per_minute within the last 60 seconds, raises HTTP 429
    with a compliant 'Retry-After' header and message prompting to provide an x-api-key.
    """
    if limit_per_minute <= 0:
        return

    now = time.time()
    window_seconds = 60.0
    r_client = _get_redis_client()

    if r_client is not None:
        try:
            r_key = f"ratelimit:public_ip:{client_ip}"
            suffix = secrets.token_hex(4)
            res = r_client.eval(
                LUA_SLIDING_WINDOW_SCRIPT,
                1,
                r_key,
                str(now),
                str(window_seconds),
                str(limit_per_minute),
                suffix,
            )
            allowed = int(res[0])
            retry_after = int(res[2])

            if allowed == 0:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Public demo rate limit exceeded. Maximum {limit_per_minute} requests per minute for unauthenticated callers. Pass a valid 'x-api-key' header for commercial quota.",
                    headers={"Retry-After": str(retry_after)},
                )
            return
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning(f"[RateLimiter ALERT] Redis Lua IP rate limit operation failed: {exc}")
            _handle_redis_failure()

    # Fail-closed policy enforcement in production
    # In multi-instance production: strictly fail closed with HTTP 503 unless explicit single-instance opt-out is enabled
    allow_in_memory = getattr(settings, "ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION", False)
    fail_closed = getattr(settings, "RATE_LIMIT_REDIS_FAIL_CLOSED", True)
    if settings.ENVIRONMENT == "production" and fail_closed and not allow_in_memory:
        logger.error("[RateLimiter CRITICAL] Redis is unavailable for IP rate limiting and RATE_LIMIT_REDIS_FAIL_CLOSED is enabled. Failing closed.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Distributed rate limiter service is temporarily unavailable. Fail-closed policy in effect.",
        )

    # In-memory sliding window fallback
    if settings.ENVIRONMENT == "production":
        logger.warning("[RateLimiter ALERT] Production API is operating on process-local in-memory rate limiter fallback for IP limiting.")
    global _LAST_CLEANUP_TIME
    with _LOCK:
        ip_key = f"ip_{client_ip}"
        history = _KEY_REQUEST_WINDOWS.get(ip_key, [])
        active_entries = [t for t in history if now - t < window_seconds]

        if len(active_entries) >= limit_per_minute:
            oldest = active_entries[0]
            retry_after = max(1, int(window_seconds - (now - oldest)))
            _KEY_REQUEST_WINDOWS[ip_key] = active_entries
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Public demo rate limit exceeded. Maximum {limit_per_minute} requests per minute for unauthenticated callers. Pass a valid 'x-api-key' header for commercial quota.",
                headers={"Retry-After": str(retry_after)},
            )

        active_entries.append(now)
        _KEY_REQUEST_WINDOWS[ip_key] = active_entries


def get_rate_limiter_status() -> Dict[str, Any]:
    """Inspect current rate limiter backend, operational connection state, and alerts."""
    r_client = _get_redis_client()
    backend_name = "redis" if r_client is not None else "in_memory_fallback"
    return {
        "backend": backend_name,
        "redis_configured": bool(settings.REDIS_URL),
        "redis_connected": r_client is not None,
        "fail_closed_policy": getattr(settings, "RATE_LIMIT_REDIS_FAIL_CLOSED", False),
        "in_memory_active_keys": len(_KEY_REQUEST_WINDOWS),
        "alert_in_memory_fallback": (settings.ENVIRONMENT == "production" and backend_name != "redis"),
    }


def reset_api_key_rate_limits() -> None:
    """Clear rate limiting state (used for testing)."""
    global _REDIS_CLIENT
    with _LOCK:
        _KEY_REQUEST_WINDOWS.clear()
    r_client = _get_redis_client()
    if r_client:
        try:
            keys = r_client.keys("ratelimit:*")
            if keys:
                r_client.delete(*keys)
        except Exception:
            pass
