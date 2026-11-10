from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Header
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
    email: str = Form(...),
    password: str = Form(...),
):
    conn = get_connection()

    user = conn.execute("""
        SELECT *
        FROM users
        WHERE email = ?
    """, (email.lower().strip(),)).fetchone()

    if not user:
        conn.close()
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
        raise HTTPException(status_code=401, detail="Invalid email or password")

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
