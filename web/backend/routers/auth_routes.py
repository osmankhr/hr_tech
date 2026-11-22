from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Header, Request
from auth_utils import (
    hash_password,
    verify_password,
    create_raw_token,
    hash_token,
    token_expiry,
    utc_now,
    PASSWORD_ITERATIONS,
)
from core.database import get_connection
from core.auth import public_user, get_current_user, require_admin
from core.security import (
    login_rate_limiter,
    get_client_ip,
    perform_dummy_verification,
)

router = APIRouter(tags=["auth"])


@router.post("/api/users")
def create_user(
    email: str = Form(...),
    full_name: str = Form(...),
    password: str = Form(...),
    role: str = Form("hr"),
    current_user=Depends(require_admin),
):
    if role not in ("admin", "hr"):
        raise HTTPException(status_code=400, detail="role must be 'admin' or 'hr'")

    conn = get_connection()
    now = utc_now()

    existing_user = conn.execute(
        "SELECT id FROM users WHERE email = ?",
        (email.lower().strip(),),
    ).fetchone()

    if existing_user:
        conn.close()
        raise HTTPException(status_code=400, detail="Email already registered")

    password_hash, salt = hash_password(password)

    conn.execute("""
        INSERT INTO users (
            email,
            full_name,
            role,
            password_hash,
            password_salt,
            password_algorithm,
            password_iterations,
            is_active,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, 'pbkdf2_hmac_sha256', ?, 1, ?, ?)
    """, (
        email.lower().strip(),
        full_name.strip(),
        role,
        password_hash,
        salt,
        PASSWORD_ITERATIONS,
        now,
        now,
    ))

    conn.commit()
    conn.close()

    return {"success": True, "message": "User created successfully"}


@router.post("/api/auth/signin")
def signin(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):
    client_ip = get_client_ip(request)
    normalized_email = email.lower().strip()
    ip_key = f"ip:{client_ip}"
    account_key = f"account:{normalized_email}"

    # Brute-force protection: Max 5 failed attempts per 5 minutes per IP or account
    if login_rate_limiter.is_rate_limited(ip_key, max_attempts=5, window_seconds=300) or \
       login_rate_limiter.is_rate_limited(account_key, max_attempts=5, window_seconds=300):
        retry_after = max(
            login_rate_limiter.get_retry_after(ip_key, window_seconds=300),
            login_rate_limiter.get_retry_after(account_key, window_seconds=300),
        )
        raise HTTPException(
            status_code=429,
            detail=f"Çok fazla hatalı giriş denemesi yapıldı. Güvenliğiniz için lütfen {retry_after} saniye sonra tekrar deneyin.",
            headers={"Retry-After": str(retry_after)},
        )

    conn = get_connection()

    user = conn.execute("""
        SELECT *
        FROM users
        WHERE email = ?
    """, (normalized_email,)).fetchone()

    if not user:
        conn.close()
        # Record failed attempt and perform constant-time dummy verification
        login_rate_limiter.record_attempt(ip_key, window_seconds=300)
        login_rate_limiter.record_attempt(account_key, window_seconds=300)
        perform_dummy_verification(password)
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if user["is_active"] != 1:
        conn.close()
        raise HTTPException(status_code=403, detail="User is inactive")

    password_ok = verify_password(
        password=password,
        stored_hash=user["password_hash"],
        salt=user["password_salt"],
        iterations=user["password_iterations"],
    )

    if not password_ok:
        conn.close()
        login_rate_limiter.record_attempt(ip_key, window_seconds=300)
        login_rate_limiter.record_attempt(account_key, window_seconds=300)
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # Reset failed attempts counters on successful login
    login_rate_limiter.reset(ip_key)
    login_rate_limiter.reset(account_key)

    raw_token = create_raw_token()
    token_hash_value = hash_token(raw_token)

    conn.execute("""
        INSERT INTO auth_tokens (
            user_id,
            token_hash,
            created_at,
            expires_at
        )
        VALUES (?, ?, ?, ?)
    """, (
        user["id"],
        token_hash_value,
        utc_now(),
        token_expiry(),
    ))

    conn.commit()
    conn.close()

    return {
        "token": raw_token,
        "user": public_user(user),
    }


@router.post("/api/auth/signout")
def signout(
    authorization: Optional[str] = Header(default=None),
):
    if not authorization or not authorization.startswith("Bearer "):
        return {"success": True}

    raw_token = authorization.replace("Bearer ", "").strip()
    token_hash_value = hash_token(raw_token)

    conn = get_connection()
    conn.execute("""
        UPDATE auth_tokens
        SET revoked_at = ?
        WHERE token_hash = ?
    """, (utc_now(), token_hash_value))
    conn.commit()
    conn.close()

    return {"success": True}


@router.get("/api/auth/me")
def me(current_user=Depends(get_current_user)):
    return public_user(current_user)


@router.get("/api/users")
def list_users(current_user=Depends(require_admin)):
    conn = get_connection()

    rows = conn.execute("""
        SELECT
            id,
            email,
            full_name,
            role,
            is_active,
            created_at
        FROM users
        ORDER BY created_at DESC
    """).fetchall()

    conn.close()
    return [dict(row) for row in rows]
