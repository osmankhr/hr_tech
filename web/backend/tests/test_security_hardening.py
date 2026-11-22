import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from main import app
from core.security import (
    login_rate_limiter,
    assert_safe_path,
    get_client_ip,
)
import core.config


@pytest.fixture(autouse=True)
def reset_rate_limiters():
    login_rate_limiter._attempts.clear()
    yield
    login_rate_limiter._attempts.clear()


@pytest.fixture
def client():
    return TestClient(app)


def test_security_headers_enforced(client):
    """Verify that OWASP security headers are present on HTTP responses."""
    res = client.get("/api/auth/me")
    headers = res.headers

    assert headers.get("x-content-type-options") == "nosniff"
    assert headers.get("x-frame-options") == "SAMEORIGIN"
    assert headers.get("x-xss-protection") == "1; mode=block"
    assert headers.get("referrer-policy") == "strict-origin-when-cross-origin"
    assert "camera=()" in headers.get("permissions-policy", "")
    assert "default-src 'self'" in headers.get("content-security-policy", "")


def test_brute_force_rate_limiting(client):
    """Verify that failed attempts trigger HTTP 429 Too Many Requests after threshold."""
    email = "test_target_brute_force@example.com"
    pwd = "wrong_password_attempt"

    for i in range(15):
        res = client.post("/api/auth/signin", data={"email": email, "password": pwd})
        assert res.status_code == 401, f"Attempt {i+1} should return 401"

    # 16th attempt should be blocked with 429
    blocked_res = client.post("/api/auth/signin", data={"email": email, "password": pwd})
    assert blocked_res.status_code == 429
    assert "Çok fazla hatalı giriş denemesi" in blocked_res.json()["detail"]
    assert "retry-after" in blocked_res.headers


def test_flexible_username_and_dual_admin_passwords(client):
    """Verify that admin can log in with email or username prefix, and both admin123 and rust-zebra-willow-68."""
    # 1. Login with username alias 'admin' and password 'admin123'
    res = client.post("/api/auth/signin", data={"email": "admin", "password": "admin123"})
    assert res.status_code == 200
    assert "token" in res.json()

    # 2. Login with master server password 'rust-zebra-willow-68'
    res2 = client.post("/api/auth/signin", data={"email": "admin", "password": "rust-zebra-willow-68"})
    assert res2.status_code == 200
    assert "token" in res2.json()


def test_path_traversal_guard(tmp_path):
    """Verify that path traversal attempts escaping the base dir are blocked with HTTP 400."""
    safe_base = tmp_path / "safe_dir"
    safe_base.mkdir()
    child_file = safe_base / "valid.txt"
    child_file.write_text("ok")

    # Allowed child
    assert assert_safe_path(child_file, safe_base) == child_file.resolve()

    # Traversal escape attempt
    traversal_file = safe_base / ".." / "escaped.txt"
    with pytest.raises(HTTPException) as exc_info:
        assert_safe_path(traversal_file, safe_base)
    assert exc_info.value.status_code == 400


def test_cors_origins_includes_production():
    """Verify that production origin is properly allowlisted."""
    assert "https://stagetwoforge.com" in core.config.CORS_ORIGINS
