#!/usr/bin/env python3
"""
Migration script to add candidate_comments table to existing database.
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "hr_candidate_search_demo.db"

def run_migration():
    if not DB_PATH.exists():
        print(f"Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS candidate_comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                parent_id INTEGER,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (candidate_id) REFERENCES candidates(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (parent_id) REFERENCES candidate_comments(id) ON DELETE CASCADE
            )
        """)
        conn.commit()
        print("Successfully created candidate_comments table.")
    except Exception as e:
        print(f"Error during migration: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    run_migration()
