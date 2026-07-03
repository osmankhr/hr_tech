import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from typing import Optional

PASSWORD_ITERATIONS = 600_000
TOKEN_EXPIRE_HOURS = 12


def utc_now():
    return datetime.utcnow().isoformat(timespec="seconds")


def hash_password(password: str, salt: Optional[str] = None):
    if salt is None:
        salt = secrets.token_hex(32)

    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PASSWORD_ITERATIONS,
    ).hex()

    return password_hash, salt


def verify_password(password: str, stored_hash: str, salt: str, iterations: int):
    calculated_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    ).hex()

    return hmac.compare_digest(calculated_hash, stored_hash)


def create_raw_token():
    return secrets.token_urlsafe(48)


def hash_token(raw_token: str):
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def token_expiry():
    return (datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS)).isoformat(
        timespec="seconds"
    )