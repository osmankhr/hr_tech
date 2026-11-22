import time
import logging
from collections import defaultdict
from pathlib import Path
from threading import Lock
from typing import Optional

from fastapi import HTTPException, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

# Dummy values for constant-time authentication timing attack defense
DUMMY_SALT = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
DUMMY_HASH = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Enforce industry-standard OWASP security headers on all HTTP responses."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response: Response = await call_next(request)

        # 1. Prevent MIME-sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # 2. Clickjacking protection (allow sameorigin for modals/iframes if needed)
        response.headers["X-Frame-Options"] = "SAMEORIGIN"

        # 3. Cross-Site Scripting (XSS) filter
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # 4. Referrer policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # 5. Restrict sensitive browser features
        response.headers["Permissions-Policy"] = (
            "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
            "magnetometer=(), microphone=(), payment=(), usb=()"
        )

        # 6. HTTP Strict Transport Security (HSTS) when on HTTPS
        forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        if forwarded_proto.lower() == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        # 7. Content-Security-Policy (CSP)
        # Allows self, embedded images (data/blob), fonts, Cloudflare analytics, and safe styling for Tailwind/Vite
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://static.cloudflareinsights.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com data:; "
            "img-src 'self' data: blob: https:; "
            "connect-src 'self' https: https://cloudflareinsights.com; "
            "frame-ancestors 'self'; "
            "object-src 'none'; "
            "base-uri 'self';"
        )

        return response


class InMemoryRateLimiter:
    """Thread-safe sliding-window rate limiter for brute-force and abuse protection."""

    def __init__(self):
        self._lock = Lock()
        self._attempts: dict[str, list[float]] = defaultdict(list)

    def record_attempt(self, key: str, window_seconds: int = 300) -> int:
        """Record an attempt timestamp and return count in the current sliding window."""
        now = time.time()
        with self._lock:
            cutoff = now - window_seconds
            self._attempts[key] = [t for t in self._attempts[key] if t > cutoff]
            self._attempts[key].append(now)
            return len(self._attempts[key])

    def is_rate_limited(self, key: str, max_attempts: int = 5, window_seconds: int = 300) -> bool:
        """Check whether the key exceeded max_attempts within window_seconds."""
        now = time.time()
        with self._lock:
            cutoff = now - window_seconds
            self._attempts[key] = [t for t in self._attempts[key] if t > cutoff]
            return len(self._attempts[key]) >= max_attempts

    def reset(self, key: str) -> None:
        """Reset attempts counter for a specific key upon successful action."""
        with self._lock:
            self._attempts.pop(key, None)

    def get_retry_after(self, key: str, window_seconds: int = 300) -> int:
        """Calculate seconds until the oldest attempt in window expires."""
        now = time.time()
        with self._lock:
            timestamps = self._attempts.get(key, [])
            if not timestamps:
                return 0
            oldest = min(timestamps)
            remaining = int(window_seconds - (now - oldest))
            return max(remaining, 1)


# Global rate limiters
login_rate_limiter = InMemoryRateLimiter()
api_rate_limiter = InMemoryRateLimiter()


def get_client_ip(request: Request) -> str:
    """Safely extract the origin client IP address."""
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip and cf_ip.strip():
        return cf_ip.strip()
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
        if client_ip:
            return client_ip
    real_ip = request.headers.get("x-real-ip")
    if real_ip and real_ip.strip():
        return real_ip.strip()
    if request.client:
        return request.client.host
    return "127.0.0.1"


def perform_dummy_verification(password: str, iterations: int = 600_000) -> None:
    """Perform constant-time dummy PBKDF2 hash computation to prevent user enumeration timing attacks."""
    import hashlib
    try:
        hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            DUMMY_SALT.encode("utf-8"),
            iterations,
        )
    except Exception:
        pass


def assert_safe_path(target_path: Path, base_dir: Path, error_msg: str = "Invalid path access") -> Path:
    """Validate that target_path strictly resolves within base_dir to block path traversal."""
    try:
        resolved_target = target_path.resolve()
        resolved_base = base_dir.resolve()
        if not resolved_target.is_relative_to(resolved_base):
            logger.warning(
                "Security violation: path %s attempts to escape base %s",
                resolved_target,
                resolved_base,
            )
            raise HTTPException(status_code=400, detail=error_msg)
        return resolved_target
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Path resolution error: %s", e)
        raise HTTPException(status_code=400, detail=error_msg)
