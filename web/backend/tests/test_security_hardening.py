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
def client(tmp_path, monkeypatch):
    test_db = tmp_path / "test.db"
    import main
    monkeypatch.setattr(main, "DB_PATH", test_db)
    monkeypatch.setattr(core.config, "DB_PATH", test_db)
    from core.database import get_connection
    from auth_utils import hash_password, utc_now
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            full_name TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin', 'hr')) DEFAULT 'hr',
            password_hash TEXT NOT NULL,
            password_salt TEXT NOT NULL,
            password_algorithm TEXT NOT NULL DEFAULT 'pbkdf2_hmac_sha256',
            password_iterations INTEGER NOT NULL DEFAULT 600000,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS auth_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            revoked_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
    """)
    now = utc_now()
    pwd_hash, salt = hash_password("admin123")
    conn.execute("""
        INSERT INTO users (
            email, full_name, role, password_hash, password_salt, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, ("admin@hr.local", "Admin User", "admin", pwd_hash, salt, now, now))
    conn.commit()
    conn.close()
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


def test_flexible_username_login(client):
    """Verify that user can log in with full email or username prefix with admin123."""
    # 1. Login with username alias 'admin'
    res = client.post("/api/auth/signin", data={"email": "admin", "password": "admin123"})
    assert res.status_code == 200
    assert "token" in res.json()

    # 2. Login with full email 'admin@hr.local'
    res2 = client.post("/api/auth/signin", data={"email": "admin@hr.local", "password": "admin123"})
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
