from typing import Optional
from fastapi import HTTPException, Depends, Header
from auth_utils import hash_token, utc_now
from core.database import get_connection

def public_user(row):
    """Serialize a database user row for safe public/frontend exposure."""
    return {
        "id": row["id"],
        "email": row["email"],
        "full_name": row["full_name"],
        "role": row["role"],
    }


def _get_current_user_from_raw_token(raw_token: str):
    token_hash_value = hash_token(raw_token)
    conn = get_connection()

    row = conn.execute("""
        SELECT
            u.id,
            u.email,
            u.full_name,
            u.role,
            u.is_active,
            t.expires_at,
            t.revoked_at
        FROM auth_tokens t
        JOIN users u ON u.id = t.user_id
        WHERE t.token_hash = ?
    """, (token_hash_value,)).fetchone()

    conn.close()

    if not row:
        raise HTTPException(status_code=401, detail="Invalid token")

    if row["revoked_at"] is not None:
        raise HTTPException(status_code=401, detail="Token revoked")

    if row["is_active"] != 1:
        raise HTTPException(status_code=403, detail="User is inactive")

    if row["expires_at"] < utc_now():
        raise HTTPException(status_code=401, detail="Token expired")

    return row


def get_current_user(authorization: Optional[str] = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")

    raw_token = authorization.replace("Bearer ", "").strip()
    return _get_current_user_from_raw_token(raw_token)


def require_admin(current_user=Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    return current_user


def _get_owned_campaign(conn, campaign_id, current_user):
    """Fetch a campaign, scoped to its owner unless the caller is an admin.

    Non-owners get a 404 (not 403) so hr accounts can't probe for the
    existence of other accounts' campaigns.
    """
    campaign = conn.execute(
        "SELECT id, campaign_code, created_by_user_id FROM campaigns WHERE id = ?",
        (campaign_id,),
    ).fetchone()

    if not campaign:
        return None

    if current_user["role"] != "admin" and campaign["created_by_user_id"] != current_user["id"]:
        return None

    return campaign
