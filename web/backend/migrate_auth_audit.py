import sqlite3
import hashlib
import os
import secrets
from datetime import datetime
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "hr_candidate_search_demo.db"

# Admin bootstrap credentials. Set HR_ADMIN_EMAIL / HR_ADMIN_PASSWORD in the
# environment before running this script. If HR_ADMIN_PASSWORD is unset, a
# random password is generated and printed once — save it immediately, it is
# not stored anywhere else.
ADMIN_EMAIL = os.environ.get("HR_ADMIN_EMAIL", "admin@hr.local")
ADMIN_PASSWORD = os.environ.get("HR_ADMIN_PASSWORD") or secrets.token_urlsafe(16)
ADMIN_FULL_NAME = "System Admin"

PASSWORD_ITERATIONS = 600_000


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


def column_exists(conn, table_name, column_name):
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(row[1] == column_name for row in rows)


def add_column_if_missing(conn, table_name, column_definition):
    column_name = column_definition.split()[0]

    if not column_exists(conn, table_name, column_name):
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_definition}")


def main():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    conn.execute("""
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
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS auth_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            revoked_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    add_column_if_missing(conn, "campaigns", "created_by_user_id INTEGER")
    add_column_if_missing(conn, "campaigns", "updated_by_user_id INTEGER")

    add_column_if_missing(conn, "candidates", "created_by_user_id INTEGER")
    add_column_if_missing(conn, "candidates", "updated_by_user_id INTEGER")
    add_column_if_missing(conn, "candidates", "first_contacted_by_user_id INTEGER")
    add_column_if_missing(conn, "candidates", "first_contacted_at TEXT")

    now = datetime.utcnow().isoformat(timespec="seconds")

    existing_admin = conn.execute(
        "SELECT id FROM users WHERE email = ?",
        (ADMIN_EMAIL,),
    ).fetchone()

    if not existing_admin:
        password_hash, salt = hash_password(ADMIN_PASSWORD)

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
            VALUES (?, ?, 'admin', ?, ?, 'pbkdf2_hmac_sha256', ?, 1, ?, ?)
        """, (
            ADMIN_EMAIL,
            ADMIN_FULL_NAME,
            password_hash,
            salt,
            PASSWORD_ITERATIONS,
            now,
            now,
        ))

        print("Admin user created.")
        print(f"Email: {ADMIN_EMAIL}")
        print(f"Password: {ADMIN_PASSWORD}")
        print("IMPORTANT: Change this password after first login.")
    else:
        print("Admin user already exists.")

    admin_id = conn.execute(
        "SELECT id FROM users WHERE email = ?",
        (ADMIN_EMAIL,),
    ).fetchone()["id"]

    conn.execute("""
        UPDATE campaigns
        SET created_by_user_id = COALESCE(created_by_user_id, ?),
            updated_by_user_id = COALESCE(updated_by_user_id, ?)
    """, (admin_id, admin_id))

    conn.execute("""
        UPDATE candidates
        SET created_by_user_id = COALESCE(created_by_user_id, ?),
            updated_by_user_id = COALESCE(updated_by_user_id, ?)
    """, (admin_id, admin_id))

    conn.commit()
    conn.close()

    print("Auth and audit migration completed.")


if __name__ == "__main__":
    main()