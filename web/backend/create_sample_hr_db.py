#!/usr/bin/env python3
"""Create an empty SQLite database schema for the HR Candidate Search application.

This script creates the database schema without any test data.
To use the application, you'll need to:
1. Run this script to create the database: python create_sample_hr_db.py
2. Create an admin user manually or through the API
3. Start adding your own campaigns and candidates

Schema includes:
- Auth users and tokens
- PBKDF2-HMAC-SHA256 password hashing
- Campaigns and candidates
- Campaign/candidate relationships
- Skills and skill mappings
- Search runs and refresh logs
- Audit events
"""

import os
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "hr_candidate_search_demo.db"

# This script intentionally recreates the demo database.
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)


schema_sql = """
PRAGMA foreign_keys = ON;

CREATE TABLE users (
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

CREATE TABLE auth_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_code TEXT NOT NULL UNIQUE,
    campaign_name TEXT NOT NULL,
    location TEXT NOT NULL,
    position_name TEXT NOT NULL,
    experience TEXT NOT NULL,
    sample_cv_filename TEXT,
    target_profiles TEXT,
    status TEXT NOT NULL CHECK(status IN ('Draft', 'Active', 'Past')) DEFAULT 'Draft',
    owner TEXT NOT NULL,
    created_by_user_id INTEGER,
    updated_by_user_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (updated_by_user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_code TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL,
    email TEXT,
    current_title TEXT,
    location TEXT,
    source TEXT,
    profile_url TEXT,
    score REAL,
    status TEXT NOT NULL CHECK(status IN ('New', 'Reviewed', 'Shortlisted', 'Contacted', 'Rejected')) DEFAULT 'New',
    years_experience REAL,
    last_updated TEXT,
    notes TEXT,
    created_by_user_id INTEGER,
    updated_by_user_id INTEGER,
    first_contacted_by_user_id INTEGER,
    first_contacted_at TEXT,
    FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (updated_by_user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (first_contacted_by_user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE skills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE campaign_skills (
    campaign_id INTEGER NOT NULL,
    skill_id INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, skill_id),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
    FOREIGN KEY (skill_id) REFERENCES skills(id) ON DELETE CASCADE
);

CREATE TABLE candidate_skills (
    candidate_id INTEGER NOT NULL,
    skill_id INTEGER NOT NULL,
    PRIMARY KEY (candidate_id, skill_id),
    FOREIGN KEY (candidate_id) REFERENCES candidates(id) ON DELETE CASCADE,
    FOREIGN KEY (skill_id) REFERENCES skills(id) ON DELETE CASCADE
);

CREATE TABLE campaign_candidates (
    campaign_id INTEGER NOT NULL,
    candidate_id INTEGER NOT NULL,
    match_score REAL,
    pipeline_stage TEXT NOT NULL CHECK(pipeline_stage IN ('Found', 'Reviewed', 'Shortlisted', 'Contacted', 'Rejected')) DEFAULT 'Found',
    added_by_user_id INTEGER,
    added_at TEXT,
    contacted_by_user_id INTEGER,
    contacted_at TEXT,
    PRIMARY KEY (campaign_id, candidate_id),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
    FOREIGN KEY (candidate_id) REFERENCES candidates(id) ON DELETE CASCADE,
    FOREIGN KEY (added_by_user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (contacted_by_user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE search_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    search_query TEXT,
    total_results INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('Running', 'Completed', 'Failed')) DEFAULT 'Running',
    created_by_user_id INTEGER,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
    FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE refresh_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id INTEGER,
    refresh_type TEXT NOT NULL DEFAULT 'profile_refresh',
    status TEXT NOT NULL CHECK(status IN ('Success', 'Failed', 'Skipped')) DEFAULT 'Success',
    message TEXT,
    created_by_user_id INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY (candidate_id) REFERENCES candidates(id) ON DELETE SET NULL,
    FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL CHECK(entity_type IN ('campaign', 'candidate', 'search_run', 'refresh_log', 'auth', 'campaign_candidate')),
    entity_id INTEGER,
    action TEXT NOT NULL,
    description TEXT,
    user_id INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE candidate_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    parent_id INTEGER,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (candidate_id) REFERENCES candidates(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (parent_id) REFERENCES candidate_comments(id) ON DELETE CASCADE
);

CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_role ON users(role);
CREATE INDEX idx_auth_tokens_token_hash ON auth_tokens(token_hash);
CREATE INDEX idx_auth_tokens_user_id ON auth_tokens(user_id);

CREATE INDEX idx_campaigns_status ON campaigns(status);
CREATE INDEX idx_campaigns_created_by ON campaigns(created_by_user_id);
CREATE INDEX idx_campaigns_updated_by ON campaigns(updated_by_user_id);

CREATE INDEX idx_candidates_status ON candidates(status);
CREATE INDEX idx_candidates_score ON candidates(score DESC);
CREATE INDEX idx_candidates_created_by ON candidates(created_by_user_id);
CREATE INDEX idx_candidates_updated_by ON candidates(updated_by_user_id);
CREATE INDEX idx_candidates_first_contacted_by ON candidates(first_contacted_by_user_id);

CREATE INDEX idx_campaign_candidates_stage ON campaign_candidates(pipeline_stage);
CREATE INDEX idx_campaign_candidates_added_by ON campaign_candidates(added_by_user_id);
CREATE INDEX idx_campaign_candidates_contacted_by ON campaign_candidates(contacted_by_user_id);

CREATE INDEX idx_search_runs_campaign_id ON search_runs(campaign_id);
CREATE INDEX idx_refresh_logs_candidate_id ON refresh_logs(candidate_id);
CREATE INDEX idx_audit_events_entity ON audit_events(entity_type, entity_id);

CREATE VIEW campaign_summary AS
SELECT
    c.id,
    c.campaign_code,
    c.campaign_name,
    c.location,
    c.position_name,
    c.experience,
    c.sample_cv_filename,
    c.target_profiles,
    c.status,
    c.owner,
    c.created_by_user_id,
    c.created_at,
    c.updated_at,
    cu.full_name AS created_by_name,
    uu.full_name AS updated_by_name,
    COUNT(DISTINCT cc.candidate_id) AS candidate_count,
    COUNT(DISTINCT CASE WHEN cc.pipeline_stage = 'Shortlisted' THEN cc.candidate_id END) AS shortlisted_count,
    GROUP_CONCAT(DISTINCT s.name) AS desired_skills
FROM campaigns c
LEFT JOIN users cu ON cu.id = c.created_by_user_id
LEFT JOIN users uu ON uu.id = c.updated_by_user_id
LEFT JOIN campaign_candidates cc ON cc.campaign_id = c.id
LEFT JOIN campaign_skills cs ON cs.campaign_id = c.id
LEFT JOIN skills s ON s.id = cs.skill_id
GROUP BY c.id;

CREATE VIEW candidate_profile_summary AS
SELECT
    cand.id,
    cand.candidate_code,
    cand.full_name,
    cand.email,
    cand.current_title,
    cand.location,
    cand.source,
    cand.profile_url,
    cand.score,
    cand.status,
    cand.years_experience,
    cand.last_updated,
    cand.notes,
    cand.first_contacted_at,
    cu.full_name AS created_by_name,
    uu.full_name AS updated_by_name,
    fu.full_name AS first_contacted_by_name,
    GROUP_CONCAT(DISTINCT s.name) AS skills
FROM candidates cand
LEFT JOIN users cu ON cu.id = cand.created_by_user_id
LEFT JOIN users uu ON uu.id = cand.updated_by_user_id
LEFT JOIN users fu ON fu.id = cand.first_contacted_by_user_id
LEFT JOIN candidate_skills cs ON cs.candidate_id = cand.id
LEFT JOIN skills s ON s.id = cs.skill_id
GROUP BY cand.id;
"""


conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA foreign_keys = ON")
cur = conn.cursor()

cur.executescript(schema_sql)

conn.commit()

# Count tables
tables_to_count = [
    "users",
    "auth_tokens",
    "campaigns",
    "candidates",
    "skills",
    "campaign_skills",
    "candidate_skills",
    "campaign_candidates",
    "search_runs",
    "refresh_logs",
    "audit_events",
    "candidate_comments",
]

print(f"[SUCCESS] Created {DB_PATH}")
print()
print("Database schema created successfully!")
print()
print("Table counts:")

for table in tables_to_count:
    count = conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"]
    print(f"  - {table}: {count}")

conn.close()

print()
print("=" * 60)
print("NEXT STEPS:")
print("=" * 60)
print("1. Create an admin user through the API or add one manually")
print("2. Start the backend server: cd backend && uvicorn main:app --reload")
print("3. Start the frontend: cd frontend && npm run dev")
print("4. Login and begin adding campaigns and candidates")
print()
print("NOTE: This database contains NO test data for privacy reasons.")
print("      You must create your own users and data.")
print("=" * 60)
