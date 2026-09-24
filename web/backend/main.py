from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends, Header, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from typing import Optional
import sqlite3
import shutil
import os
import json
import csv
import io
import re
import logging
import subprocess
import threading
import time
import yaml
from datetime import datetime, timedelta, timezone
from pathlib import Path
from auth_utils import (
    hash_password,
    verify_password,
    create_raw_token,
    hash_token,
    token_expiry,
    utc_now,
    PASSWORD_ITERATIONS,
)

BACKEND_DIR = Path(__file__).resolve().parent
DB_PATH = BACKEND_DIR / "hr_candidate_search_demo.db"
CANDIDATE_POOL_ROOT = BACKEND_DIR.parent.parent / "candidate_pool"
CANDIDATE_POOL_CAMPAIGNS_DIR = CANDIDATE_POOL_ROOT / "campaigns"
UPLOAD_DIR = BACKEND_DIR / "uploaded_cvs"
FRONTEND_DIST = BACKEND_DIR.parent / "frontend" / "dist"
MAX_WORKERS_CAP = 20
STALE_RUN_TIMEOUT_MINUTES = 180

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger(__name__)

app = FastAPI(title="HR Candidate Search API")

_cors_origins = [
    origin.strip()
    for origin in os.environ.get(
        "HR_CORS_ORIGINS", "http://localhost:5173"
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def public_user(row):
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

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL lets readers proceed while a write is in progress instead of locking
    # the whole file (the default rollback-journal mode), which is what was
    # causing "database is locked" 500s under concurrent multi-user access.
    # This is a one-time, persistent, file-level setting; re-issuing it on
    # every connection is a cheap no-op once already in WAL mode.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


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


def ensure_pipeline_tables():
    conn = get_connection()
    core_tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if "campaigns" not in core_tables or "candidates" not in core_tables:
        conn.close()
        raise RuntimeError(
            f"Core schema missing in {DB_PATH}. Run "
            "`python create_sample_hr_db.py` then `python migrate_auth_audit.py` "
            "before starting the server."
        )

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS pipeline_campaign_configs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER NOT NULL UNIQUE,
            pipeline_dir TEXT NOT NULL,
            campaign_yaml_path TEXT NOT NULL,
            job_description_path TEXT NOT NULL,
            filter_criteria_path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS pipeline_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER NOT NULL,
            run_type TEXT NOT NULL CHECK(run_type IN ('full', 'queries', 'search', 'filter', 'rank', 'report', 'import')),
            status TEXT NOT NULL CHECK(status IN ('Queued', 'Running', 'Completed', 'Failed')),
            command TEXT,
            campaign_dir TEXT,
            artifact_path TEXT,
            error_message TEXT,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            created_by_user_id INTEGER,
            FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
            FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS candidate_rankings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER NOT NULL,
            candidate_id INTEGER NOT NULL,
            manual_score REAL,
            category TEXT,
            rank INTEGER,
            feature_contributions_json TEXT,
            gate_penalty REAL,
            ai_adjustment REAL,
            raw_agent_json TEXT,
            raw_manual_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (campaign_id, candidate_id),
            FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
            FOREIGN KEY (candidate_id) REFERENCES candidates(id) ON DELETE CASCADE
        );

        -- Full history of pipeline_campaign_configs snapshots. pipeline_campaign_configs itself
        -- stays a single current-pointer row per campaign (unchanged since its original design);
        -- this table only ever gets new rows appended, so no existing row/constraint has to
        -- change to add version history. The current version is always the one with the
        -- highest version_number for a campaign_id.
        CREATE TABLE IF NOT EXISTS pipeline_config_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER NOT NULL,
            version_number INTEGER NOT NULL,
            pipeline_dir TEXT NOT NULL,
            campaign_yaml_path TEXT NOT NULL,
            job_description_path TEXT NOT NULL,
            filter_criteria_path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE (campaign_id, version_number),
            FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS pipeline_campaign_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            template_name TEXT NOT NULL,
            pipeline_description TEXT,
            locations_json TEXT NOT NULL,
            job_description TEXT NOT NULL,
            filter_criteria TEXT NOT NULL,
            source_campaign_id INTEGER,
            created_by_user_id INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (source_campaign_id) REFERENCES campaigns(id) ON DELETE SET NULL,
            FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE SET NULL
        );

        -- One row per edit of a campaign's pipeline config. Unlike
        -- pipeline_campaign_configs (which holds only paths, one row per campaign, and now acts
        -- as the "which version is current" pointer), this keeps the config *content* so the
        -- editor can round-trip it without re-parsing campaign.yaml, and so each version keeps
        -- its own pipeline_dir -- which is what lets every run's candidate list survive an edit.
        CREATE TABLE IF NOT EXISTS pipeline_config_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER NOT NULL,
            version_number INTEGER NOT NULL,
            is_current INTEGER NOT NULL DEFAULT 1,
            pipeline_name TEXT NOT NULL,
            pipeline_description TEXT,
            locations_json TEXT NOT NULL,
            job_description TEXT NOT NULL,
            filter_criteria TEXT NOT NULL,
            pipeline_dir TEXT NOT NULL,
            campaign_yaml_path TEXT NOT NULL,
            job_description_path TEXT NOT NULL,
            filter_criteria_path TEXT NOT NULL,
            created_by_user_id INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (campaign_id, version_number),
            FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
            FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS idx_pipeline_runs_campaign ON pipeline_runs(campaign_id, started_at DESC);
        CREATE INDEX IF NOT EXISTS idx_candidate_rankings_campaign ON candidate_rankings(campaign_id, rank ASC);
        CREATE INDEX IF NOT EXISTS idx_pipeline_campaign_templates_owner ON pipeline_campaign_templates(created_by_user_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_pipeline_config_versions_campaign ON pipeline_config_versions(campaign_id, version_number DESC);
<<<<<<< HEAD
=======
    """)

    # One-time backfill: every campaign configured before pipeline_config_versions existed gets
    # its current pipeline_campaign_configs row recorded as version 1. Safe to run on every
    # startup -- WHERE NOT IN skips campaigns that already have history.
    conn.execute("""
        INSERT INTO pipeline_config_versions (
            campaign_id, version_number, pipeline_dir,
            campaign_yaml_path, job_description_path, filter_criteria_path, created_at
        )
        SELECT campaign_id, 1, pipeline_dir, campaign_yaml_path, job_description_path,
               filter_criteria_path, created_at
        FROM pipeline_campaign_configs
        WHERE campaign_id NOT IN (SELECT campaign_id FROM pipeline_config_versions)
>>>>>>> main
    """)

    # Backward-compatible columns for run summary metrics.
    for alter_sql in [
        "ALTER TABLE pipeline_runs ADD COLUMN accepted_candidates INTEGER",
        "ALTER TABLE pipeline_runs ADD COLUMN ranked_candidates INTEGER",
        "ALTER TABLE candidates ADD COLUMN english_confidence TEXT",
        "ALTER TABLE candidates ADD COLUMN english_confidence_reason TEXT",
        # 0 = "belongs to no known config version" (pre-versioning rows). Not NULL, because
        # SQLite treats NULLs as distinct in UNIQUE constraints, which would let the same
        # candidate be inserted repeatedly for the same campaign.
        "ALTER TABLE pipeline_runs ADD COLUMN config_version_id INTEGER NOT NULL DEFAULT 0",
    ]:
        try:
            conn.execute(alter_sql)
        except sqlite3.OperationalError:
            pass

    _migrate_candidate_rankings_to_versioned(conn)

    # candidate_profile_summary is a VIEW with a fixed column list baked in at CREATE time —
    # unlike a table, it doesn't pick up new candidates columns automatically, so it has to be
    # dropped and recreated whenever a column is added to candidates that the view should expose.
    conn.executescript("""
        DROP VIEW IF EXISTS candidate_profile_summary;

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
            cand.english_confidence,
            cand.english_confidence_reason,
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
    """)

    conn.commit()

    _backfill_config_versions(conn)

    conn.commit()
    conn.close()


def _migrate_candidate_rankings_to_versioned(conn):
    """Re-key candidate_rankings from (campaign_id, candidate_id) to include config_version_id.

    The original UNIQUE(campaign_id, candidate_id) meant a second run of the same campaign
    overwrote the first run's scores, so only the newest config's results ever existed.
    SQLite can't alter a table-level UNIQUE constraint in place, hence the rebuild. Guarded by
    a column check so it runs exactly once.
    """
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(candidate_rankings)")}
    if not columns or "config_version_id" in columns:
        return

    logger.info("Migrating candidate_rankings to be config-version scoped")

    # executescript() commits any open transaction first, so the DDL below runs outside one.
    conn.executescript("""
        CREATE TABLE candidate_rankings_versioned (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER NOT NULL,
            config_version_id INTEGER NOT NULL DEFAULT 0,
            candidate_id INTEGER NOT NULL,
            manual_score REAL,
            category TEXT,
            rank INTEGER,
            feature_contributions_json TEXT,
            gate_penalty REAL,
            ai_adjustment REAL,
            raw_agent_json TEXT,
            raw_manual_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (campaign_id, config_version_id, candidate_id),
            FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
            FOREIGN KEY (candidate_id) REFERENCES candidates(id) ON DELETE CASCADE
        );

        INSERT INTO candidate_rankings_versioned (
            campaign_id, config_version_id, candidate_id, manual_score, category, rank,
            feature_contributions_json, gate_penalty, ai_adjustment, raw_agent_json,
            raw_manual_json, created_at, updated_at
        )
        SELECT
            campaign_id, 0, candidate_id, manual_score, category, rank,
            feature_contributions_json, gate_penalty, ai_adjustment, raw_agent_json,
            raw_manual_json, created_at, updated_at
        FROM candidate_rankings;

        DROP TABLE candidate_rankings;
        ALTER TABLE candidate_rankings_versioned RENAME TO candidate_rankings;

        CREATE INDEX IF NOT EXISTS idx_candidate_rankings_campaign
            ON candidate_rankings(campaign_id, rank ASC);
        CREATE INDEX IF NOT EXISTS idx_candidate_rankings_version
            ON candidate_rankings(campaign_id, config_version_id, rank ASC);
    """)


def _backfill_config_versions(conn):
    """Give every pre-versioning campaign a version 1 row, and attach its existing runs/results.

    Config content wasn't stored in the DB before, so it's recovered from the files the pipeline
    actually runs against (campaign.yaml + input/*.md). A campaign whose folder is gone still
    gets a row, just with empty content, so the editor has something to open.
    """
    rows = conn.execute("""
        SELECT c.campaign_id, c.pipeline_dir, c.campaign_yaml_path,
               c.job_description_path, c.filter_criteria_path, c.created_at
        FROM pipeline_campaign_configs c
        LEFT JOIN pipeline_config_versions v ON v.campaign_id = c.campaign_id
        WHERE v.id IS NULL
    """).fetchall()

    for row in rows:
        recovered = _read_config_from_disk(Path(row["pipeline_dir"]))
        campaign = conn.execute(
            "SELECT campaign_name, created_by_user_id FROM campaigns WHERE id = ?",
            (row["campaign_id"],),
        ).fetchone()

        version_id = conn.execute("""
            INSERT INTO pipeline_config_versions (
                campaign_id, version_number, is_current, pipeline_name, pipeline_description,
                locations_json, job_description, filter_criteria, pipeline_dir,
                campaign_yaml_path, job_description_path, filter_criteria_path,
                created_by_user_id, created_at, updated_at
            )
            VALUES (?, 1, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            row["campaign_id"],
            recovered["pipeline_name"] or (campaign["campaign_name"] if campaign else "Campaign"),
            recovered["pipeline_description"],
            json.dumps(recovered["locations"], ensure_ascii=False),
            recovered["job_description"],
            recovered["filter_criteria"],
            row["pipeline_dir"],
            row["campaign_yaml_path"],
            row["job_description_path"],
            row["filter_criteria_path"],
            campaign["created_by_user_id"] if campaign else None,
            row["created_at"],
            utc_now(),
        )).lastrowid

        conn.execute(
            "UPDATE pipeline_runs SET config_version_id = ? WHERE campaign_id = ? AND config_version_id = 0",
            (version_id, row["campaign_id"]),
        )
        conn.execute(
            "UPDATE candidate_rankings SET config_version_id = ? WHERE campaign_id = ? AND config_version_id = 0",
            (version_id, row["campaign_id"]),
        )


@app.on_event("startup")
def on_startup():
    ensure_pipeline_tables()


def _slugify(value: str):
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "campaign"


LOCATION_CLAUSE_HEADING = "## Location Requirement (hard filter)"
LOCATION_CLAUSE_TAIL = "pending for manual review rather than accepting."


def _build_location_filter_clause(locations):
    names = [str(loc.get("name", "")).strip() for loc in locations if str(loc.get("name", "")).strip()]
    if not names:
        return ""

    hint_lines = [
        f"- {loc['name']}: {loc['hint']}"
        for loc in locations
        if str(loc.get("name", "")).strip() and str(loc.get("hint", "")).strip()
    ]

    lines = [
        "## Location Requirement (hard filter)",
        "",
        f"The candidate must be currently based in one of: {', '.join(names)}.",
    ]
    if hint_lines:
        lines.append("")
        lines.extend(hint_lines)
    lines.extend([
        "",
        "Determine the candidate's real current location strictly from their profile text — "
        "do not trust any location label attached to the search query itself. If it clearly "
        "does not match, reject. If it cannot be determined from the profile text, mark as "
        "pending for manual review rather than accepting.",
        "",
    ])
    return "\n".join(lines)


def _build_campaign_yaml(name: str, description: str, locations, max_candidates: int = 40):
    lines = [
        f"name: {json.dumps(name, ensure_ascii=False)}",
        f"description: {json.dumps(description, ensure_ascii=False)}",
        "",
        "locations:",
    ]

    for loc in locations:
        loc_name = str(loc.get("name", "")).strip()
        hint = str(loc.get("hint", "")).strip()
        lines.append(f"  - name: {json.dumps(loc_name, ensure_ascii=False)}")
        lines.append(f"    hint: {json.dumps(hint, ensure_ascii=False)}")

    lines.extend([
        "",
        "search:",
        "  num_queries_per_location: 6",
        "  num_results_per_query: 30",
        "  provider: exa",
        "  category: people",
        "  contents:",
        "    text: true",
        "    highlights:",
        "      num_sentences: 10",
        "      highlights_per_url: 3",
        "",
        "query_generation:",
        "  model: claude-sonnet-5",
        "",
        "filter:",
        f"  max_candidates: {int(max_candidates)}",
        "  model: claude-sonnet-5",
        "",
        "ranking:",
        "  enabled: true",
        "  model: claude-sonnet-5",
        "  input_path: data/filtered_results.json",
        "  output_path: data/ranked_results.json",
        "  summary_path: data/ranking_summary.json",
        "  feature_schema_path: data/ranking_feature_schema.json",
        "  scoring_policy_path: data/ranking_scoring_policy.json",
        "  max_features: 10",
        "  max_candidates: 200",
        "  candidate_text_chars: 5000",
        "  only_accepted: true",
        "  force_redesign: false",
        "",
        "output:",
        "  formats: [excel, csv, json]",
        "  keep_rejected: true",
        "",
    ])

    return "\n".join(lines)



def _read_config_from_disk(pipeline_dir: Path) -> dict:
    """Recover editable config content from a pipeline folder.

    Used to backfill campaigns created before config content was persisted in the DB. Every
    field degrades to empty rather than raising — a half-readable folder still needs to open
    in the editor.
    """
    recovered = {
        "pipeline_name": "",
        "pipeline_description": "",
        "locations": [],
        "job_description": "",
        "filter_criteria": "",
    }

    if not pipeline_dir or not pipeline_dir.exists():
        return recovered

    try:
        parsed = yaml.safe_load((pipeline_dir / "campaign.yaml").read_text(encoding="utf-8")) or {}
        if isinstance(parsed, dict):
            recovered["pipeline_name"] = str(parsed.get("name") or "")
            recovered["pipeline_description"] = str(parsed.get("description") or "")
            locations = parsed.get("locations")
            if isinstance(locations, list):
                recovered["locations"] = [
                    {
                        "name": str(loc.get("name") or "").strip(),
                        "hint": str(loc.get("hint") or "").strip(),
                    }
                    for loc in locations
                    if isinstance(loc, dict) and str(loc.get("name") or "").strip()
                ]
    except Exception:
        logger.warning("Could not recover campaign.yaml from %s", pipeline_dir)

    try:
        recovered["job_description"] = (
            pipeline_dir / "input" / "job_description.md"
        ).read_text(encoding="utf-8")
    except Exception:
        pass

    try:
        recovered["filter_criteria"] = _strip_location_clause(
            (pipeline_dir / "input" / "filter_criteria.md").read_text(encoding="utf-8")
        )
    except Exception:
        pass

    return recovered


def _write_pipeline_config_files(
    *,
    campaign_dir: Path,
    pipeline_name: str,
    pipeline_description: str,
    locations,
    job_description: str,
    filter_criteria: str,
    max_candidates: int,
):
    """Create/refresh the candidate_pool folder layout and config files for one config version.

    Returns the three paths that pipeline_campaign_configs / pipeline_config_versions record.
    """
    input_dir = campaign_dir / "input"
    campaign_dir.mkdir(parents=True, exist_ok=True)
    input_dir.mkdir(parents=True, exist_ok=True)
    (campaign_dir / "data").mkdir(parents=True, exist_ok=True)
    (campaign_dir / "output").mkdir(parents=True, exist_ok=True)
    (campaign_dir / "logs").mkdir(parents=True, exist_ok=True)

    campaign_yaml_path = campaign_dir / "campaign.yaml"
    job_description_path = input_dir / "job_description.md"
    filter_criteria_path = input_dir / "filter_criteria.md"

    campaign_yaml_path.write_text(
        _build_campaign_yaml(
            pipeline_name, pipeline_description, locations, max_candidates=max_candidates
        ),
        encoding="utf-8",
    )
    job_description_path.write_text(job_description, encoding="utf-8")

    location_clause = _build_location_filter_clause(locations)
    filter_criteria_path.write_text(
        f"{location_clause}\n{filter_criteria}" if location_clause else filter_criteria,
        encoding="utf-8",
    )

    return campaign_yaml_path, job_description_path, filter_criteria_path


# Artifacts the pipeline caches to avoid repeat LLM cost. They're derived from the job
# description / filter criteria / locations, so an in-place config edit makes them stale and a
# rerun would silently reuse queries and scoring features built from the *old* config.
STALE_ON_CONFIG_EDIT = (
    "generated_queries.yaml",
    "ranking_feature_schema.json",
    "ranking_scoring_policy.json",
)


def _clear_config_derived_cache(pipeline_dir: Path):
    for filename in STALE_ON_CONFIG_EDIT:
        try:
            (pipeline_dir / "data" / filename).unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not clear cached %s in %s", filename, pipeline_dir)


def _mark_stale_running_runs(conn):
    """Fail runs whose worker thread is gone.

    Runs execute in a daemon thread, so a server restart (or a systemd reload) leaves the row
    stuck at 'Running' forever — which permanently blocks both starting a new run and editing
    the config, since both refuse to proceed while one is in progress.
    """
    cutoff = (
        datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=STALE_RUN_TIMEOUT_MINUTES)
    ).isoformat(timespec="seconds")

    conn.execute("""
        UPDATE pipeline_runs
        SET status = 'Failed',
            completed_at = ?,
            error_message = COALESCE(error_message, 'Run abandoned — no result recorded before timeout')
        WHERE status = 'Running' AND started_at < ?
    """, (utc_now(), cutoff))
    conn.commit()


def _parse_locations_payload(locations_json: str) -> list:
    try:
        parsed = json.loads(locations_json)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="locations_json must be valid JSON")

    if not isinstance(parsed, list) or len(parsed) == 0:
        raise HTTPException(status_code=400, detail="locations_json must be a non-empty JSON array")

    cleaned = []
    for item in parsed:
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail="Each location must be an object with name and hint")
        name = str(item.get("name", "")).strip()
        hint = str(item.get("hint", "")).strip()
        if not name:
            raise HTTPException(status_code=400, detail="Each location must include a non-empty name")
        cleaned.append({"name": name, "hint": hint})
    return cleaned


def _new_version_dir(pipeline_name: str, version_number: int) -> Path:
    """Each config version gets its own candidate_pool folder.

    That separation is what preserves earlier runs: the pipeline writes every artifact
    (raw_results/filtered_results/ranked_results) relative to its campaign dir, so pointing a
    new version at a new folder leaves the previous version's results untouched instead of
    overwriting them in place.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return CANDIDATE_POOL_CAMPAIGNS_DIR / f"{_slugify(pipeline_name)}_v{version_number}_{stamp}"


def _point_current_config_at(conn, campaign_id: int, version_row, now: str):
    """Repoint pipeline_campaign_configs at a version's folder.

    pipeline_campaign_configs stays the single "current version" pointer that every existing
    route (run, exports, scoring-explainer, usage-summary) already reads, so switching versions
    doesn't require touching any of them.
    """
    conn.execute("""
        UPDATE pipeline_campaign_configs
        SET pipeline_dir = ?,
            campaign_yaml_path = ?,
            job_description_path = ?,
            filter_criteria_path = ?,
            updated_at = ?
        WHERE campaign_id = ?
    """, (
        version_row["pipeline_dir"],
        version_row["campaign_yaml_path"],
        version_row["job_description_path"],
        version_row["filter_criteria_path"],
        now,
        campaign_id,
    ))


def _replace_current_version_paths(
    conn,
    *,
    campaign_id: int,
    pipeline_name: str,
    pipeline_description: str,
    locations,
    job_description: str,
    filter_criteria: str,
    campaign_dir: Path,
    campaign_yaml_path: Path,
    job_description_path: Path,
    filter_criteria_path: Path,
    now: str,
):
    """Overwrite the current version's content and folder (used when setup re-runs)."""
    current = conn.execute("""
        SELECT id, version_number
        FROM pipeline_config_versions
        WHERE campaign_id = ?
        ORDER BY is_current DESC, version_number DESC
        LIMIT 1
    """, (campaign_id,)).fetchone()

    conn.execute("""
        UPDATE pipeline_config_versions
        SET pipeline_name = ?, pipeline_description = ?, locations_json = ?,
            job_description = ?, filter_criteria = ?, pipeline_dir = ?,
            campaign_yaml_path = ?, job_description_path = ?, filter_criteria_path = ?,
            updated_at = ?
        WHERE id = ?
    """, (
        pipeline_name,
        pipeline_description,
        json.dumps(locations, ensure_ascii=False),
        job_description,
        filter_criteria,
        str(campaign_dir),
        str(campaign_yaml_path),
        str(job_description_path),
        str(filter_criteria_path),
        now,
        current["id"],
    ))

    return current["id"], current["version_number"]


def _get_config_version(conn, campaign_id: int, version_id: Optional[int] = None):
    """Fetch one config version row — a specific one by id, or the campaign's current one."""
    if version_id is not None:
        return conn.execute(
            "SELECT * FROM pipeline_config_versions WHERE id = ? AND campaign_id = ?",
            (version_id, campaign_id),
        ).fetchone()

    return conn.execute("""
        SELECT *
        FROM pipeline_config_versions
        WHERE campaign_id = ?
        ORDER BY is_current DESC, version_number DESC
        LIMIT 1
    """, (campaign_id,)).fetchone()


def _config_version_has_results(conn, version_row) -> bool:
    """Whether a version has produced candidate results worth preserving.

    Drives the edit-in-place vs. new-version decision: overwriting a config that nobody has run
    yet loses nothing, but overwriting one with results would strand the candidate list the
    recruiter is looking at.
    """
    imported = conn.execute(
        "SELECT 1 FROM candidate_rankings WHERE campaign_id = ? AND config_version_id = ? LIMIT 1",
        (version_row["campaign_id"], version_row["id"]),
    ).fetchone()
    if imported:
        return True

    # Ranked output on disk counts too — the pipeline may have finished without the UI having
    # imported it yet (auto-import is driven by an SSE event the browser can miss).
    return (Path(version_row["pipeline_dir"]) / "data" / "ranked_results.json").exists()
_LOCATION_CLAUSE_MARKER = "## Location Requirement (hard filter)"
_LOCATION_CLAUSE_END_MARKER = "pending for manual review rather than accepting."


def _strip_location_clause(text: str) -> str:
    """Undo _build_location_filter_clause() so the edit-config UI shows only what the user typed.

    Configs created before filter_criteria_raw.md existed (see setup_pipeline_campaign) only have
    the combined file on disk, with the auto-generated location clause glued onto the front.
    Stripping it here (rather than backfilling raw files for old campaigns) means an old config's
    first re-save re-derives the clause itself instead of keeping two stale copies in sync.
    """
    if not text.startswith(_LOCATION_CLAUSE_MARKER):
        return text
    end_idx = text.find(_LOCATION_CLAUSE_END_MARKER)
    if end_idx == -1:
        return text
    return text[end_idx + len(_LOCATION_CLAUSE_END_MARKER):].lstrip("\n")


def _read_pipeline_config_files(pipeline_dir: Path) -> dict:
    """Read a pipeline version's editable fields back off disk for the config-versions UI."""
    campaign_yaml_path = pipeline_dir / "campaign.yaml"
    job_description_path = pipeline_dir / "input" / "job_description.md"
    filter_criteria_raw_path = pipeline_dir / "input" / "filter_criteria_raw.md"
    filter_criteria_path = pipeline_dir / "input" / "filter_criteria.md"

    name, description, locations = "", "", []
    if campaign_yaml_path.exists():
        try:
            parsed = yaml.safe_load(campaign_yaml_path.read_text(encoding="utf-8")) or {}
            name = parsed.get("name") or ""
            description = parsed.get("description") or ""
            locations = parsed.get("locations") or []
        except Exception:
            logger.exception("Failed to read campaign.yaml at %s", campaign_yaml_path)

    job_description = (
        job_description_path.read_text(encoding="utf-8") if job_description_path.exists() else ""
    )

    if filter_criteria_raw_path.exists():
        filter_criteria = filter_criteria_raw_path.read_text(encoding="utf-8")
    elif filter_criteria_path.exists():
        filter_criteria = _strip_location_clause(filter_criteria_path.read_text(encoding="utf-8"))
    else:
        filter_criteria = ""

    return {
        "pipeline_name": name,
        "pipeline_description": description,
        "locations": locations,
        "job_description": job_description,
        "filter_criteria": filter_criteria,
    }


def _pipeline_results_summary(pipeline_dir: Path) -> dict:
    """Whether a pipeline version has been run, and how far -- drives has_results/counts in the
    config-versions UI and whether editing a config updates it in place or starts a new version.
    """
    shortlist_path = pipeline_dir / "output" / "shortlist.json"
    has_results = shortlist_path.exists()
    accepted_candidates = None
    if has_results:
        try:
            candidates = json.loads(shortlist_path.read_text(encoding="utf-8"))
            accepted_candidates = sum(
                1 for c in candidates if (c.get("ai_review") or {}).get("recommendation") == "ACCEPT"
            )
        except Exception:
            logger.exception("Failed to read shortlist.json at %s", shortlist_path)

    ranked_candidates = None
    ranked_path = pipeline_dir / "data" / "ranked_results.json"
    if ranked_path.exists():
        try:
            ranked_candidates = len(json.loads(ranked_path.read_text(encoding="utf-8")))
        except Exception:
            logger.exception("Failed to read ranked_results.json at %s", ranked_path)

    return {
        "has_results": has_results,
        "accepted_candidates": accepted_candidates,
        "ranked_candidates": ranked_candidates,
    }
>>>>>>> main


def _extract_years_experience(text: str):
    if not text:
        return None

    match = re.search(r"Total Experience:\s*([0-9]+)(?:\s+years?)?(?:\s+and\s+([0-9]+)\s+months?)?", text, re.IGNORECASE)
    if not match:
        return None

    years = float(match.group(1))
    months = float(match.group(2) or 0)
    return round(years + months / 12.0, 2)


def _next_candidate_code(conn):
    row = conn.execute("""
        SELECT candidate_code
        FROM candidates
        WHERE candidate_code LIKE 'CAN-%'
        ORDER BY CAST(SUBSTR(candidate_code, 5) AS INTEGER) DESC
        LIMIT 1
    """).fetchone()

    if not row:
        return "CAN-1001"

    try:
        next_value = int(row["candidate_code"].split("-")[1]) + 1
    except (IndexError, ValueError):
        next_value = 1001

    return f"CAN-{next_value:04d}"


def _candidate_status_from_review(recommendation: str):
    if recommendation == "ACCEPT":
        return "Shortlisted"
    if recommendation == "REJECT":
        return "Rejected"
    return "Reviewed"


def _pipeline_stage_from_status(status: str):
    if status == "Shortlisted":
        return "Shortlisted"
    if status == "Rejected":
        return "Rejected"
    return "Reviewed"


def _flatten_for_csv(prefix: str, value, out: dict):
    if isinstance(value, dict):
        for key, nested in value.items():
            next_prefix = f"{prefix}.{key}" if prefix else str(key)
            _flatten_for_csv(next_prefix, nested, out)
        return

    if isinstance(value, list):
        out[prefix] = json.dumps(value, ensure_ascii=False)
        return

    out[prefix] = value


SEARCH_CSV_EXCLUDED_FIELDS = {
    "score",
    "text",
    "highlights",
    "highlight_scores",
    "source",
}

RANKED_CSV_EXCLUDED_FIELDS = SEARCH_CSV_EXCLUDED_FIELDS | {
    "ai_review.main_concern",
    "ranking",
}


def _normalize_csv_cell(value):
    if value is None:
        return ""

    if isinstance(value, (dict, list)):
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    else:
        raw = str(value)

    return re.sub(r"\s+", " ", raw).strip()


def _should_exclude_csv_field(key: str, excluded_fields: set[str], rank_summary_only: bool):
    if key in excluded_fields:
        return True

    if rank_summary_only and key.startswith("ranking.") and not key.endswith("summary"):
        return True

    return False


def _build_csv_rows(rows: list[dict], excluded_fields: set[str], rank_summary_only: bool = False):
    flattened_rows = []
    fieldnames = set()

    for row in rows:
        if not isinstance(row, dict):
            continue

        flat = {}
        _flatten_for_csv("", row, flat)

        normalized = {}
        for key, value in flat.items():
            if _should_exclude_csv_field(key, excluded_fields, rank_summary_only):
                continue
            normalized[key] = _normalize_csv_cell(value)

        flattened_rows.append(normalized)
        fieldnames.update(normalized.keys())

    return flattened_rows, sorted(fieldnames)


def _remove_pipeline_campaign_dir(pipeline_dir: Optional[str]):
    if not pipeline_dir:
        return

    target = Path(pipeline_dir).expanduser().resolve()
    campaigns_root = CANDIDATE_POOL_CAMPAIGNS_DIR.resolve()

    try:
        target.relative_to(campaigns_root)
    except ValueError as exc:
        raise ValueError(
            f"Refusing to delete folder outside campaign root: {target}"
        ) from exc

    if target.exists():
        shutil.rmtree(target)


def _run_pipeline_in_background(run_id: int, command, cwd: Path):
    conn = get_connection()
    try:
        run_row = conn.execute(
            "SELECT campaign_dir FROM pipeline_runs WHERE id = ?",
            (run_id,),
        ).fetchone()

        result = subprocess.run(
            command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode == 0:
            accepted_candidates = None
            ranked_candidates = None

            if run_row and run_row["campaign_dir"]:
                campaign_dir = Path(run_row["campaign_dir"])
                filtered_path = campaign_dir / "data" / "filtered_results.json"
                ranked_path = campaign_dir / "data" / "ranked_results.json"

                if filtered_path.exists():
                    try:
                        filtered_rows = json.loads(filtered_path.read_text(encoding="utf-8"))
                        accepted_candidates = sum(
                            1
                            for row in filtered_rows
                            if isinstance(row, dict)
                            and str((row.get("ai_review") or {}).get("recommendation") or "").upper() == "ACCEPT"
                        )
                    except Exception:
                        accepted_candidates = None

                if ranked_path.exists():
                    try:
                        ranked_rows = json.loads(ranked_path.read_text(encoding="utf-8"))
                        ranked_candidates = len(ranked_rows) if isinstance(ranked_rows, list) else None
                    except Exception:
                        ranked_candidates = None

            conn.execute(
                """
                UPDATE pipeline_runs
                SET
                    status = 'Completed',
                    completed_at = ?,
                    error_message = NULL,
                    accepted_candidates = ?,
                    ranked_candidates = ?
                WHERE id = ?
                """,
                (utc_now(), accepted_candidates, ranked_candidates, run_id),
            )
        else:
            error_message = (result.stderr or result.stdout or "Pipeline run failed").strip()
            conn.execute(
                """
                UPDATE pipeline_runs
                SET
                    status = 'Failed',
                    completed_at = ?,
                    error_message = ?
                WHERE id = ?
                """,
                (utc_now(), error_message[:4000], run_id),
            )
    except Exception as exc:
        conn.execute(
            """
            UPDATE pipeline_runs
            SET
                status = 'Failed',
                completed_at = ?,
                error_message = ?
            WHERE id = ?
            """,
            (utc_now(), str(exc)[:4000], run_id),
        )
    finally:
        conn.commit()
        conn.close()


@app.get("/api/campaigns")
def list_campaigns(current_user=Depends(get_current_user)):
    conn = get_connection()
    if current_user["role"] == "admin":
        rows = conn.execute("""
            SELECT *
            FROM campaign_summary
            ORDER BY created_at DESC
        """).fetchall()
    else:
        rows = conn.execute("""
            SELECT *
            FROM campaign_summary
            WHERE created_by_user_id = ?
            ORDER BY created_at DESC
        """, (current_user["id"],)).fetchall()
    conn.close()

    return [dict(row) for row in rows]


@app.post("/api/campaigns/{campaign_id}/pipeline/setup")
def setup_pipeline_campaign(
    campaign_id: int,
    pipeline_name: str = Form(...),
    pipeline_description: str = Form(...),
    locations_json: str = Form(...),
    job_description: str = Form(...),
    filter_criteria: str = Form(...),
    current_user=Depends(get_current_user),
):
    conn = get_connection()

    campaign = _get_owned_campaign(conn, campaign_id, current_user)

    if not campaign:
        conn.close()
        raise HTTPException(status_code=404, detail="Campaign not found")

    campaign_extra = conn.execute(
        "SELECT target_profiles, sample_cv_filename FROM campaigns WHERE id = ?",
        (campaign_id,),
    ).fetchone()
    target_profiles = (campaign_extra["target_profiles"] if campaign_extra else None) or 40
    sample_cv_filename = campaign_extra["sample_cv_filename"] if campaign_extra else None

    try:
        cleaned_locations = _parse_locations_payload(locations_json)
    except HTTPException:
        conn.close()
        raise

    campaign_dir = _new_version_dir(pipeline_name, 1)

    if campaign_dir.exists():
        conn.close()
        raise HTTPException(status_code=409, detail="Pipeline campaign directory already exists")

    campaign_yaml_path, job_description_path, filter_criteria_path = _write_pipeline_config_files(
        campaign_dir=campaign_dir,
        pipeline_name=pipeline_name,
        pipeline_description=pipeline_description,
        locations=cleaned_locations,
        job_description=job_description,
        filter_criteria=filter_criteria,
        max_candidates=target_profiles,
    )

    job_description_path.write_text(job_description, encoding="utf-8")

    location_clause = _build_location_filter_clause(cleaned_locations)
    full_filter_criteria = (
        f"{location_clause}\n{filter_criteria}" if location_clause else filter_criteria
    )
    filter_criteria_path.write_text(full_filter_criteria, encoding="utf-8")
    # Kept alongside the combined file (which is what the pipeline actually reads) so the
    # edit-config UI can show back exactly what the user typed, without the auto-generated
    # location clause re-prepending itself on every subsequent edit.
    (input_dir / "filter_criteria_raw.md").write_text(filter_criteria, encoding="utf-8")

    # Sample CV (if uploaded on the campaign) never reached the search pipeline before —
    # generate_queries.py only reads PDFs from input/seed_cvs/, but the upload endpoint only
    # ever saved the file to a generic uploads folder and stored its filename on the campaign
    # row. Copy it into this pipeline's seed_cvs folder so query generation actually uses it.
    if sample_cv_filename:
        source_cv_path = UPLOAD_DIR / sample_cv_filename
        if source_cv_path.exists():
            seed_cv_dir = campaign_dir / "input" / "seed_cvs"
            seed_cv_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_cv_path, seed_cv_dir / source_cv_path.name)

    now = utc_now()
    conn.execute("""
        INSERT INTO pipeline_campaign_configs (
            campaign_id,
            pipeline_dir,
            campaign_yaml_path,
            job_description_path,
            filter_criteria_path,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(campaign_id)
        DO UPDATE SET
            pipeline_dir = excluded.pipeline_dir,
            campaign_yaml_path = excluded.campaign_yaml_path,
            job_description_path = excluded.job_description_path,
            filter_criteria_path = excluded.filter_criteria_path,
            updated_at = excluded.updated_at
    """, (
        campaign_id,
        str(campaign_dir),
        str(campaign_yaml_path),
        str(job_description_path),
        str(filter_criteria_path),
        now,
        now,
    ))
    conn.execute("""
        INSERT INTO pipeline_config_versions (
            campaign_id, version_number, pipeline_dir,
            campaign_yaml_path, job_description_path, filter_criteria_path, created_at
        )
        VALUES (?, 1, ?, ?, ?, ?, ?)
        ON CONFLICT(campaign_id, version_number) DO NOTHING
    """, (
        campaign_id,
        str(campaign_dir),
        str(campaign_yaml_path),
        str(job_description_path),
        str(filter_criteria_path),
        now,
    ))

    # Re-running setup for a campaign that already has versions would orphan them, so the
    # first version is only seeded when there isn't one yet.
    existing_version = conn.execute(
        "SELECT id FROM pipeline_config_versions WHERE campaign_id = ? LIMIT 1",
        (campaign_id,),
    ).fetchone()

    if existing_version:
        version_id, version_number = _replace_current_version_paths(
            conn,
            campaign_id=campaign_id,
            pipeline_name=pipeline_name,
            pipeline_description=pipeline_description,
            locations=cleaned_locations,
            job_description=job_description,
            filter_criteria=filter_criteria,
            campaign_dir=campaign_dir,
            campaign_yaml_path=campaign_yaml_path,
            job_description_path=job_description_path,
            filter_criteria_path=filter_criteria_path,
            now=now,
        )
    else:
        version_id = conn.execute("""
            INSERT INTO pipeline_config_versions (
                campaign_id, version_number, is_current, pipeline_name, pipeline_description,
                locations_json, job_description, filter_criteria, pipeline_dir,
                campaign_yaml_path, job_description_path, filter_criteria_path,
                created_by_user_id, created_at, updated_at
            )
            VALUES (?, 1, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            campaign_id,
            pipeline_name,
            pipeline_description,
            json.dumps(cleaned_locations, ensure_ascii=False),
            job_description,
            filter_criteria,
            str(campaign_dir),
            str(campaign_yaml_path),
            str(job_description_path),
            str(filter_criteria_path),
            current_user["id"],
            now,
            now,
        )).lastrowid
        version_number = 1

    conn.commit()
    conn.close()

    return {
        "success": True,
        "campaign_id": campaign_id,
        "pipeline_dir": str(campaign_dir),
        "campaign_yaml_path": str(campaign_yaml_path),
        "job_description_path": str(job_description_path),
        "filter_criteria_path": str(filter_criteria_path),
        "config_version_id": version_id,
        "version_number": version_number,
    }


@app.get("/api/campaigns/{campaign_id}/pipeline/config-versions")
def get_pipeline_config_versions(campaign_id: int, current_user=Depends(get_current_user)):
    conn = get_connection()

    if not _get_owned_campaign(conn, campaign_id, current_user):
        conn.close()
        raise HTTPException(status_code=404, detail="Campaign not found")

    rows = conn.execute("""
        SELECT id, version_number, pipeline_dir, created_at
        FROM pipeline_config_versions
        WHERE campaign_id = ?
        ORDER BY version_number DESC
    """, (campaign_id,)).fetchall()
    conn.close()

    # No is_current column: versions only ever get appended (never edited/deleted), so the
    # highest version_number is always the current one -- i.e. the first row, since we sorted
    # DESC above.
    current_version_number = rows[0]["version_number"] if rows else None

    versions = []
    for row in rows:
        pipeline_dir = Path(row["pipeline_dir"])
        versions.append({
            "id": row["id"],
            "version_number": row["version_number"],
            "is_current": row["version_number"] == current_version_number,
            "pipeline_dir": str(pipeline_dir),
            "created_at": row["created_at"],
            **_read_pipeline_config_files(pipeline_dir),
            **_pipeline_results_summary(pipeline_dir),
        })
    return versions


@app.put("/api/campaigns/{campaign_id}/pipeline/config")
def update_pipeline_config(
    campaign_id: int,
    pipeline_name: str = Form(...),
    pipeline_description: str = Form(...),
    locations_json: str = Form(...),
    job_description: str = Form(...),
    filter_criteria: str = Form(...),
    current_user=Depends(get_current_user),
):
    """Edit a campaign's pipeline config.

    If the current version has never produced results, edits overwrite its files in place. If it
    already has a shortlist, editing must not disturb those saved results -- so this starts a new
    version instead: a fresh pipeline_dir with the new config, while the old version's files and
    pipeline_campaign_configs row before this edit stay exactly as they were, still reachable via
    GET .../config-versions.
    """
    conn = get_connection()

    campaign = _get_owned_campaign(conn, campaign_id, current_user)
    if not campaign:
        conn.close()
        raise HTTPException(status_code=404, detail="Campaign not found")

    current_row = conn.execute("""
        SELECT pipeline_dir
        FROM pipeline_campaign_configs
        WHERE campaign_id = ?
    """, (campaign_id,)).fetchone()

    if not current_row:
        conn.close()
        raise HTTPException(status_code=400, detail="Pipeline config not found. Save config first.")

    latest_version_row = conn.execute("""
        SELECT MAX(version_number) AS version_number
        FROM pipeline_config_versions
        WHERE campaign_id = ?
    """, (campaign_id,)).fetchone()
    current_version_number = (latest_version_row["version_number"] if latest_version_row else None) or 1

    try:
        parsed_locations = json.loads(locations_json)
    except json.JSONDecodeError:
        conn.close()
        raise HTTPException(status_code=400, detail="locations_json must be valid JSON")

    if not isinstance(parsed_locations, list) or len(parsed_locations) == 0:
        conn.close()
        raise HTTPException(status_code=400, detail="locations_json must be a non-empty JSON array")

    cleaned_locations = []
    for item in parsed_locations:
        if not isinstance(item, dict):
            conn.close()
            raise HTTPException(status_code=400, detail="Each location must be an object with name and hint")
        name = str(item.get("name", "")).strip()
        hint = str(item.get("hint", "")).strip()
        if not name:
            conn.close()
            raise HTTPException(status_code=400, detail="Each location must include a non-empty name")
        cleaned_locations.append({"name": name, "hint": hint})

    current_pipeline_dir = Path(current_row["pipeline_dir"])
    starts_new_version = _pipeline_results_summary(current_pipeline_dir)["has_results"]

    campaign_extra = conn.execute(
        "SELECT target_profiles, sample_cv_filename FROM campaigns WHERE id = ?",
        (campaign_id,),
    ).fetchone()
    target_profiles = (campaign_extra["target_profiles"] if campaign_extra else None) or 40
    sample_cv_filename = campaign_extra["sample_cv_filename"] if campaign_extra else None

    if starts_new_version:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        folder_name = f"{_slugify(pipeline_name)}_{stamp}"
        pipeline_dir = CANDIDATE_POOL_CAMPAIGNS_DIR / folder_name
        if pipeline_dir.exists():
            conn.close()
            raise HTTPException(status_code=409, detail="Pipeline campaign directory already exists")
        version_number = current_version_number + 1
    else:
        pipeline_dir = current_pipeline_dir
        version_number = current_version_number

    input_dir = pipeline_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    (pipeline_dir / "data").mkdir(parents=True, exist_ok=True)
    (pipeline_dir / "output").mkdir(parents=True, exist_ok=True)
    (pipeline_dir / "logs").mkdir(parents=True, exist_ok=True)

    campaign_yaml_path = pipeline_dir / "campaign.yaml"
    job_description_path = input_dir / "job_description.md"
    filter_criteria_path = input_dir / "filter_criteria.md"

    campaign_yaml_path.write_text(
        _build_campaign_yaml(pipeline_name, pipeline_description, cleaned_locations, max_candidates=target_profiles),
        encoding="utf-8",
    )
    job_description_path.write_text(job_description, encoding="utf-8")

    location_clause = _build_location_filter_clause(cleaned_locations)
    full_filter_criteria = (
        f"{location_clause}\n{filter_criteria}" if location_clause else filter_criteria
    )
    filter_criteria_path.write_text(full_filter_criteria, encoding="utf-8")
    (input_dir / "filter_criteria_raw.md").write_text(filter_criteria, encoding="utf-8")

    if sample_cv_filename:
        source_cv_path = UPLOAD_DIR / sample_cv_filename
        if source_cv_path.exists():
            seed_cv_dir = input_dir / "seed_cvs"
            seed_cv_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_cv_path, seed_cv_dir / source_cv_path.name)

    now = utc_now()
    conn.execute("""
        UPDATE pipeline_campaign_configs
        SET pipeline_dir = ?, campaign_yaml_path = ?, job_description_path = ?,
            filter_criteria_path = ?, updated_at = ?
        WHERE campaign_id = ?
    """, (
        str(pipeline_dir), str(campaign_yaml_path), str(job_description_path),
        str(filter_criteria_path), now, campaign_id,
    ))

    if starts_new_version:
        conn.execute("""
            INSERT INTO pipeline_config_versions (
                campaign_id, version_number, pipeline_dir,
                campaign_yaml_path, job_description_path, filter_criteria_path, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            campaign_id, version_number, str(pipeline_dir),
            str(campaign_yaml_path), str(job_description_path), str(filter_criteria_path), now,
        ))

    conn.commit()
    conn.close()

    return {
        "success": True,
        "new_version_created": starts_new_version,
        "version_number": version_number,
        "pipeline_dir": str(pipeline_dir),
    }


def _parse_template_locations(locations_json: str) -> list:
    try:
        parsed = json.loads(locations_json)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="locations_json must be valid JSON")

    if not isinstance(parsed, list) or len(parsed) == 0:
        raise HTTPException(status_code=400, detail="locations_json must be a non-empty JSON array")

    cleaned = []
    for item in parsed:
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail="Each location must be an object with name and hint")
        name = str(item.get("name", "")).strip()
        hint = str(item.get("hint", "")).strip()
        if not name:
            raise HTTPException(status_code=400, detail="Each location must include a non-empty name")
        cleaned.append({"name": name, "hint": hint})
    return cleaned


@app.post("/api/campaign-templates")
def create_campaign_template(
    template_name: str = Form(...),
    pipeline_description: str = Form(""),
    locations_json: str = Form(...),
    job_description: str = Form(...),
    filter_criteria: str = Form(...),
    source_campaign_id: Optional[int] = Form(None),
    current_user=Depends(get_current_user),
):
    """Save a reusable pipeline campaign config (name/locations/JD/criteria).

    Lets recruiters reuse a previous campaign's setup instead of retyping it.
    Optionally bound to the campaign it was actually used to create.
    """
    if not template_name.strip():
        raise HTTPException(status_code=400, detail="Config name is required")

    cleaned_locations = _parse_locations_payload(locations_json)

    conn = get_connection()

    if source_campaign_id is not None and not _get_owned_campaign(conn, source_campaign_id, current_user):
        conn.close()
        raise HTTPException(status_code=404, detail="Campaign not found")

    now = utc_now()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO pipeline_campaign_templates (
            template_name,
            pipeline_description,
            locations_json,
            job_description,
            filter_criteria,
            source_campaign_id,
            created_by_user_id,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        template_name.strip(),
        pipeline_description.strip(),
        json.dumps(cleaned_locations),
        job_description,
        filter_criteria,
        source_campaign_id,
        current_user["id"],
        now,
        now,
    ))
    template_id = cur.lastrowid

    conn.commit()
    conn.close()

    return {"success": True, "template_id": template_id}


@app.get("/api/campaign-templates")
def list_campaign_templates(current_user=Depends(get_current_user)):
    conn = get_connection()

    if current_user["role"] == "admin":
        rows = conn.execute("""
            SELECT
                t.*,
                c.campaign_name AS source_campaign_name,
                c.campaign_code AS source_campaign_code
            FROM pipeline_campaign_templates t
            LEFT JOIN campaigns c ON c.id = t.source_campaign_id
            ORDER BY t.created_at DESC
        """).fetchall()
    else:
        rows = conn.execute("""
            SELECT
                t.*,
                c.campaign_name AS source_campaign_name,
                c.campaign_code AS source_campaign_code
            FROM pipeline_campaign_templates t
            LEFT JOIN campaigns c ON c.id = t.source_campaign_id
            WHERE t.created_by_user_id = ?
            ORDER BY t.created_at DESC
        """, (current_user["id"],)).fetchall()

    conn.close()

    results = []
    for row in rows:
        item = dict(row)
        try:
            item["locations"] = json.loads(item.pop("locations_json") or "[]")
        except json.JSONDecodeError:
            item["locations"] = []
        results.append(item)

    return results


@app.get("/api/campaigns/{campaign_id}/pipeline/config-versions")
def list_config_versions(campaign_id: int, current_user=Depends(get_current_user)):
    """Every saved config for this campaign, newest first, with that version's result counts.

    Each version is a separate candidate list: selecting one in the UI shows the candidates that
    version's run produced, so earlier runs stay browsable after a config edit.
    """
    conn = get_connection()

    if not _get_owned_campaign(conn, campaign_id, current_user):
        conn.close()
        raise HTTPException(status_code=404, detail="Campaign not found")

    rows = conn.execute("""
        SELECT
            v.*,
            (
                SELECT COUNT(*)
                FROM candidate_rankings cr
                WHERE cr.campaign_id = v.campaign_id AND cr.config_version_id = v.id
            ) AS imported_candidates,
            (
                SELECT COUNT(*)
                FROM pipeline_runs r
                WHERE r.campaign_id = v.campaign_id AND r.config_version_id = v.id
            ) AS run_count,
            (
                SELECT r.accepted_candidates
                FROM pipeline_runs r
                WHERE r.campaign_id = v.campaign_id
                  AND r.config_version_id = v.id
                  AND r.accepted_candidates IS NOT NULL
                ORDER BY r.started_at DESC
                LIMIT 1
            ) AS accepted_candidates,
            (
                SELECT r.ranked_candidates
                FROM pipeline_runs r
                WHERE r.campaign_id = v.campaign_id
                  AND r.config_version_id = v.id
                  AND r.ranked_candidates IS NOT NULL
                ORDER BY r.started_at DESC
                LIMIT 1
            ) AS ranked_candidates
        FROM pipeline_config_versions v
        WHERE v.campaign_id = ?
        ORDER BY v.version_number DESC
    """, (campaign_id,)).fetchall()

    results = []
    for row in rows:
        item = dict(row)
        try:
            item["locations"] = json.loads(item.pop("locations_json") or "[]")
        except json.JSONDecodeError:
            item["locations"] = []

        item["is_current"] = bool(item["is_current"])
        item["has_results"] = bool(item["imported_candidates"]) or (
            Path(item["pipeline_dir"]) / "data" / "ranked_results.json"
        ).exists()
        results.append(item)

    conn.close()
    return results


@app.put("/api/campaigns/{campaign_id}/pipeline/config")
def update_pipeline_config(
    campaign_id: int,
    pipeline_name: str = Form(...),
    pipeline_description: str = Form(""),
    locations_json: str = Form(...),
    job_description: str = Form(...),
    filter_criteria: str = Form(...),
    current_user=Depends(get_current_user),
):
    """Edit a campaign's pipeline config.

    If the current version has already produced results, this creates the *next* version in a
    fresh folder and leaves the old one intact, so the recruiter keeps one candidate list per
    config they've run. If it hasn't been run yet there's nothing to preserve, so it's updated
    in place (and its config-derived caches are dropped so a rerun doesn't reuse queries and
    scoring features designed from the superseded text).
    """
    if not pipeline_name.strip():
        raise HTTPException(status_code=400, detail="Campaign name is required")
    if not job_description.strip() or not filter_criteria.strip():
        raise HTTPException(status_code=400, detail="Job description and filter criteria are required")

    cleaned_locations = _parse_locations_payload(locations_json)

    conn = get_connection()

    if not _get_owned_campaign(conn, campaign_id, current_user):
        conn.close()
        raise HTTPException(status_code=404, detail="Campaign not found")

    current_version = _get_config_version(conn, campaign_id)
    if not current_version:
        conn.close()
        raise HTTPException(
            status_code=400,
            detail="No pipeline config found for this campaign. Save config first.",
        )

    _mark_stale_running_runs(conn)

    running = conn.execute("""
        SELECT id FROM pipeline_runs
        WHERE campaign_id = ? AND status = 'Running'
        LIMIT 1
    """, (campaign_id,)).fetchone()

    if running:
        conn.close()
        raise HTTPException(
            status_code=409,
            detail="A pipeline run is in progress. Wait for it to finish before editing the config.",
        )

    target_profiles = conn.execute(
        "SELECT target_profiles FROM campaigns WHERE id = ?",
        (campaign_id,),
    ).fetchone()
    max_candidates = (target_profiles["target_profiles"] if target_profiles else None) or 40

    create_new_version = _config_version_has_results(conn, current_version)
    now = utc_now()
    pipeline_name = pipeline_name.strip()
    pipeline_description = pipeline_description.strip()

    if create_new_version:
        next_number = int(conn.execute(
            "SELECT COALESCE(MAX(version_number), 0) + 1 AS next FROM pipeline_config_versions WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()["next"])

        version_dir = _new_version_dir(pipeline_name, next_number)
        if version_dir.exists():
            conn.close()
            raise HTTPException(status_code=409, detail="Pipeline campaign directory already exists")
    else:
        next_number = int(current_version["version_number"])
        version_dir = Path(current_version["pipeline_dir"])

    try:
        yaml_path, jd_path, criteria_path = _write_pipeline_config_files(
            campaign_dir=version_dir,
            pipeline_name=pipeline_name,
            pipeline_description=pipeline_description,
            locations=cleaned_locations,
            job_description=job_description,
            filter_criteria=filter_criteria,
            max_candidates=int(max_candidates),
        )
    except OSError as exc:
        conn.close()
        raise HTTPException(status_code=500, detail=f"Could not write config files: {exc}")

    if create_new_version:
        # Seed CVs feed query generation, so a new version inherits them rather than silently
        # losing the sample CV the recruiter uploaded with the campaign.
        previous_seed_cvs = Path(current_version["pipeline_dir"]) / "input" / "seed_cvs"
        if previous_seed_cvs.is_dir():
            shutil.copytree(previous_seed_cvs, version_dir / "input" / "seed_cvs", dirs_exist_ok=True)

        conn.execute(
            "UPDATE pipeline_config_versions SET is_current = 0, updated_at = ? WHERE campaign_id = ?",
            (now, campaign_id),
        )
        version_id = conn.execute("""
            INSERT INTO pipeline_config_versions (
                campaign_id, version_number, is_current, pipeline_name, pipeline_description,
                locations_json, job_description, filter_criteria, pipeline_dir,
                campaign_yaml_path, job_description_path, filter_criteria_path,
                created_by_user_id, created_at, updated_at
            )
            VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            campaign_id,
            next_number,
            pipeline_name,
            pipeline_description,
            json.dumps(cleaned_locations, ensure_ascii=False),
            job_description,
            filter_criteria,
            str(version_dir),
            str(yaml_path),
            str(jd_path),
            str(criteria_path),
            current_user["id"],
            now,
            now,
        )).lastrowid
    else:
        _clear_config_derived_cache(version_dir)
        conn.execute("""
            UPDATE pipeline_config_versions
            SET pipeline_name = ?, pipeline_description = ?, locations_json = ?,
                job_description = ?, filter_criteria = ?, updated_at = ?
            WHERE id = ?
        """, (
            pipeline_name,
            pipeline_description,
            json.dumps(cleaned_locations, ensure_ascii=False),
            job_description,
            filter_criteria,
            now,
            current_version["id"],
        ))
        version_id = current_version["id"]

    version_row = conn.execute(
        "SELECT * FROM pipeline_config_versions WHERE id = ?",
        (version_id,),
    ).fetchone()
    _point_current_config_at(conn, campaign_id, version_row, now)

    conn.execute("""
        UPDATE campaigns
        SET campaign_name = ?, position_name = ?, location = ?,
            updated_by_user_id = ?, updated_at = ?
        WHERE id = ?
    """, (
        pipeline_name,
        pipeline_name,
        ", ".join(loc["name"] for loc in cleaned_locations),
        current_user["id"],
        now,
        campaign_id,
    ))

    description = (
        f"Pipeline config saved as version {next_number}"
        if create_new_version
        else f"Pipeline config version {next_number} updated in place"
    )
    conn.execute("""
        INSERT INTO audit_events (entity_type, entity_id, action, description, user_id, created_at)
        VALUES ('campaign', ?, 'Updated Config', ?, ?, ?)
    """, (campaign_id, description, current_user["id"], now))

    conn.commit()
    conn.close()

    return {
        "success": True,
        "campaign_id": campaign_id,
        "config_version_id": version_id,
        "version_number": next_number,
        "new_version_created": create_new_version,
        "pipeline_dir": str(version_dir),
    }


@app.get("/api/campaigns/{campaign_id}/pipeline/runs")
def list_pipeline_runs(campaign_id: int, current_user=Depends(get_current_user)):
    conn = get_connection()

    if not _get_owned_campaign(conn, campaign_id, current_user):
        conn.close()
        raise HTTPException(status_code=404, detail="Campaign not found")

    _mark_stale_running_runs(conn)

    rows = conn.execute("""
        SELECT
            r.id,
            r.campaign_id,
            r.run_type,
            r.status,
            r.command,
            r.campaign_dir,
            r.artifact_path,
            r.error_message,
            r.started_at,
            r.completed_at,
            r.accepted_candidates,
            r.ranked_candidates,
            r.config_version_id,
            v.version_number AS config_version_number
        FROM pipeline_runs r
        LEFT JOIN pipeline_config_versions v ON v.id = r.config_version_id
        WHERE r.campaign_id = ?
        ORDER BY r.started_at DESC
    """, (campaign_id,)).fetchall()
    conn.close()

    return [dict(row) for row in rows]


def _read_pipeline_progress(campaign_dir: Optional[str]) -> Optional[dict]:
    """Read the phase a running subprocess is currently in.

    `run_campaign.py` runs as an opaque subprocess, so this file is the only way to tell the
    recruiter whether we're still searching or already ranking. Absent/partial/garbage file
    just means "no phase info" -- it must never interrupt the event stream.
    """
    if not campaign_dir:
        return None

    try:
        status_path = Path(campaign_dir) / "data" / "pipeline_status.json"
        if not status_path.exists():
            return None
        payload = json.loads(status_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    if not isinstance(payload, dict) or not payload.get("phase"):
        return None
    return payload


@app.get("/api/campaigns/{campaign_id}/pipeline/events")
def stream_pipeline_events(
    campaign_id: int,
    token: Optional[str] = Query(default=None),
    authorization: Optional[str] = Header(default=None),
):
    if authorization and authorization.startswith("Bearer "):
        raw_token = authorization.replace("Bearer ", "").strip()
    elif token:
        raw_token = token.strip()
    else:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Validate caller once for SSE handshake.
    current_user = _get_current_user_from_raw_token(raw_token)

    conn = get_connection()
    owned = _get_owned_campaign(conn, campaign_id, current_user)
    conn.close()
    if not owned:
        raise HTTPException(status_code=404, detail="Campaign not found")

    def event_stream():
        last_signature = None

        while True:
            conn = get_connection()
            row = conn.execute(
                """
                SELECT
                    r.id,
                    r.campaign_id,
                    r.run_type,
                    r.status,
                    r.command,
                    r.campaign_dir,
                    r.artifact_path,
                    r.error_message,
                    r.started_at,
                    r.completed_at,
                    r.accepted_candidates,
                    r.ranked_candidates,
                    r.config_version_id,
                    v.version_number AS config_version_number
                FROM pipeline_runs r
                LEFT JOIN pipeline_config_versions v ON v.id = r.config_version_id
                WHERE r.campaign_id = ?
                ORDER BY r.started_at DESC
                LIMIT 1
                """,
                (campaign_id,),
            ).fetchone()
            conn.close()

            latest_run = dict(row) if row else None
            progress = (
                _read_pipeline_progress(latest_run.get("campaign_dir"))
                if latest_run and latest_run.get("status") == "Running"
                else None
            )
            signature = json.dumps(
                {"run": latest_run, "progress": progress}, sort_keys=True, default=str
            )

            if signature != last_signature:
                payload = {
                    "campaign_id": campaign_id,
                    "run": latest_run,
                    "progress": progress,
                    "server_time": utc_now(),
                }
                yield f"event: pipeline_run_update\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                last_signature = signature
            else:
                heartbeat = {"campaign_id": campaign_id, "server_time": utc_now()}
                yield f"event: heartbeat\ndata: {json.dumps(heartbeat)}\n\n"

            time.sleep(2)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@app.post("/api/campaigns/{campaign_id}/pipeline/run")
def run_pipeline(
    campaign_id: int,
    run_type: str = Form("full"),
    max_candidates: Optional[int] = Form(default=None),
    current_user=Depends(get_current_user),
):
    allowed_run_types = {
        "full": [],
        # --force-queries because asking for a queries run is an explicit request to regenerate
        # them; without it QueryGenerator short-circuits on the cached generated_queries.yaml
        # and the run is a no-op.
        "queries": ["--queries-only", "--force-queries"],
        "search": ["--search-only"],
        "filter": ["--filter-only"],
        "rank": ["--rank-only"],
        "report": ["--report-only"],
    }

    if run_type not in allowed_run_types:
        raise HTTPException(status_code=400, detail="Invalid run_type")

    if max_candidates is not None and (max_candidates < 1 or max_candidates > 100):
        raise HTTPException(status_code=400, detail="max_candidates must be between 1 and 100")

    conn = get_connection()

    if not _get_owned_campaign(conn, campaign_id, current_user):
        conn.close()
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Runs always target the current config version, so an edited config is what gets run.
    current_version = _get_config_version(conn, campaign_id)

    if not current_version:
        conn.close()
        raise HTTPException(status_code=400, detail="Pipeline config not found. Save config first.")

    pipeline_dir = Path(current_version["pipeline_dir"])
    if not pipeline_dir.exists():
        conn.close()
        raise HTTPException(status_code=404, detail="Pipeline directory not found")

    _mark_stale_running_runs(conn)

    running_row = conn.execute(
        """
        SELECT id
        FROM pipeline_runs
        WHERE campaign_id = ? AND status = 'Running'
        ORDER BY started_at DESC
        LIMIT 1
        """,
        (campaign_id,),
    ).fetchone()

    if running_row:
        conn.close()
        raise HTTPException(status_code=409, detail="A pipeline run is already in progress")

    preferred_venv_python = CANDIDATE_POOL_ROOT / ".venv" / "bin" / "python"
    python_bin = os.getenv("CANDIDATE_POOL_PYTHON")
    if not python_bin:
        if preferred_venv_python.exists():
            python_bin = str(preferred_venv_python)
        else:
            python_bin = "python3"
    command = [
        python_bin,
        "scripts/run_campaign.py",
        str(pipeline_dir),
        *allowed_run_types[run_type],
    ]

    if max_candidates is not None:
        runtime_workers = min(max_candidates, MAX_WORKERS_CAP)
        command += [
            "--filter-max-candidates",
            str(max_candidates),
            "--ranking-max-candidates",
            str(max_candidates),
            "--filter-max-workers",
            str(runtime_workers),
            "--ranking-max-workers",
            str(runtime_workers),
        ]

    now = utc_now()
    cur = conn.execute(
        """
        INSERT INTO pipeline_runs (
            campaign_id,
            run_type,
            status,
            command,
            campaign_dir,
            artifact_path,
            started_at,
            created_by_user_id,
            config_version_id
        )
        VALUES (?, ?, 'Running', ?, ?, ?, ?, ?, ?)
        """,
        (
            campaign_id,
            run_type,
            " ".join(command),
            str(pipeline_dir),
            str(pipeline_dir / "data" / "ranked_results.json"),
            now,
            current_user["id"],
            current_version["id"],
        ),
    )
    run_id = cur.lastrowid
    conn.commit()
    conn.close()

    thread = threading.Thread(
        target=_run_pipeline_in_background,
        args=(run_id, command, CANDIDATE_POOL_ROOT),
        daemon=True,
    )
    thread.start()

    return {
        "success": True,
        "run_id": run_id,
        "status": "Running",
        "command": " ".join(command),
    }


@app.post("/api/campaigns/{campaign_id}/pipeline/import-ranked")
def import_ranked_results(
    campaign_id: int,
    ranked_results_path: str = Form(""),
    config_version_id: Optional[int] = Form(default=None),
    current_user=Depends(get_current_user),
):
    """Import a run's ranked_results.json into the DB, attributed to a config version.

    config_version_id should be the version the run belonged to (the frontend passes the
    completed run's own value). Results are keyed per version, so importing a new run no longer
    overwrites the candidate list an earlier config produced.
    """
    conn = get_connection()

    if not _get_owned_campaign(conn, campaign_id, current_user):
        conn.close()
        raise HTTPException(status_code=404, detail="Campaign not found")

    version_row = _get_config_version(conn, campaign_id, config_version_id)
    if config_version_id is not None and not version_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Config version not found")

    version_id = version_row["id"] if version_row else 0
    pipeline_dir = version_row["pipeline_dir"] if version_row else ""
    artifact_path = ranked_results_path.strip()
    if not artifact_path:
        if not pipeline_dir:
            conn.close()
            raise HTTPException(
                status_code=400,
                detail="No pipeline config found. Provide ranked_results_path or setup pipeline first.",
            )
        artifact_path = str(Path(pipeline_dir) / "data" / "ranked_results.json")

    artifact_file = Path(artifact_path)
    if not artifact_file.exists():
        conn.close()
        raise HTTPException(status_code=404, detail="ranked_results.json not found")

    now = utc_now()
    run_cur = conn.execute("""
        INSERT INTO pipeline_runs (
            campaign_id,
            run_type,
            status,
            command,
            campaign_dir,
            artifact_path,
            started_at,
            created_by_user_id,
            config_version_id
        )
        VALUES (?, 'import', 'Running', ?, ?, ?, ?, ?, ?)
    """, (
        campaign_id,
        "import-ranked-results",
        pipeline_dir or str(artifact_file.parent.parent),
        str(artifact_file),
        now,
        current_user["id"],
        version_id,
    ))
    run_id = run_cur.lastrowid

    try:
        ranked_candidates = json.loads(artifact_file.read_text(encoding="utf-8"))
        if not isinstance(ranked_candidates, list):
            raise ValueError("ranked_results.json must contain a list")

        created_count = 0
        updated_count = 0
        linked_count = 0

        for item in ranked_candidates:
            if not isinstance(item, dict):
                continue

            profile_url = str(item.get("url") or "").strip()
            email = str(item.get("email") or "").strip().lower()
            full_name = str(item.get("title") or "").strip()
            job_title = str(item.get("extracted_title") or "").strip() or full_name
            source = str(item.get("source") or "candidate_pool")
            location = str(item.get("location") or "").strip()
            recommendation = str((item.get("ai_review") or {}).get("recommendation") or "PENDING").upper()
            candidate_status = _candidate_status_from_review(recommendation)
            english_confidence = str(item.get("english_confidence") or "").strip().upper() or None
            english_confidence_reason = str(item.get("english_confidence_reason") or "").strip() or None

            manual = (item.get("ranking") or {}).get("manual") or {}
            agent = (item.get("ranking") or {}).get("agent") or {}
            manual_score = manual.get("manual_score")
            score_value = manual_score if manual_score is not None else (item.get("score") or 0)

            try:
                score_int = int(round(float(score_value)))
            except (TypeError, ValueError):
                score_int = 0

            score_int = max(0, min(100, score_int))
            years_experience = _extract_years_experience(str(item.get("text") or ""))

            existing = None
            if profile_url:
                existing = conn.execute(
                    "SELECT id FROM candidates WHERE profile_url = ?",
                    (profile_url,),
                ).fetchone()

            if not existing and email:
                existing = conn.execute(
                    "SELECT id FROM candidates WHERE email = ?",
                    (email,),
                ).fetchone()

            if existing:
                candidate_id = existing["id"]
                conn.execute("""
                    UPDATE candidates
                    SET
                        full_name = ?,
                        email = ?,
                        current_title = ?,
                        location = ?,
                        source = ?,
                        profile_url = CASE WHEN ? != '' THEN ? ELSE profile_url END,
                        score = ?,
                        status = ?,
                        years_experience = COALESCE(?, years_experience),
                        english_confidence = COALESCE(?, english_confidence),
                        english_confidence_reason = COALESCE(?, english_confidence_reason),
                        last_updated = ?
                    WHERE id = ?
                """, (
                    full_name or "Unknown Candidate",
                    email or None,
                    job_title,
                    location,
                    source,
                    profile_url,
                    profile_url,
                    score_int,
                    candidate_status,
                    years_experience,
                    english_confidence,
                    english_confidence_reason,
                    now,
                    candidate_id,
                ))
                updated_count += 1
            else:
                candidate_code = _next_candidate_code(conn)
                cur = conn.execute("""
                    INSERT INTO candidates (
                        candidate_code,
                        full_name,
                        email,
                        current_title,
                        location,
                        source,
                        profile_url,
                        score,
                        status,
                        years_experience,
                        english_confidence,
                        english_confidence_reason,
                        last_updated,
                        notes
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    candidate_code,
                    full_name or "Unknown Candidate",
                    email or None,
                    job_title,
                    location,
                    source,
                    profile_url or None,
                    score_int,
                    candidate_status,
                    years_experience,
                    english_confidence,
                    english_confidence_reason,
                    now,
                    str((item.get("ai_review") or {}).get("reasoning") or "").strip() or None,
                ))
                candidate_id = cur.lastrowid
                created_count += 1

            conn.execute("""
                INSERT INTO campaign_candidates (
                    campaign_id,
                    candidate_id,
                    match_score,
                    pipeline_stage,
                    added_by_user_id,
                    added_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(campaign_id, candidate_id)
                DO UPDATE SET
                    match_score = excluded.match_score,
                    pipeline_stage = excluded.pipeline_stage
            """, (
                campaign_id,
                candidate_id,
                score_int,
                _pipeline_stage_from_status(candidate_status),
                current_user["id"],
                now,
            ))
            linked_count += 1

            conn.execute("""
                INSERT INTO candidate_rankings (
                    campaign_id,
                    config_version_id,
                    candidate_id,
                    manual_score,
                    category,
                    rank,
                    feature_contributions_json,
                    gate_penalty,
                    ai_adjustment,
                    raw_agent_json,
                    raw_manual_json,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(campaign_id, config_version_id, candidate_id)
                DO UPDATE SET
                    manual_score = excluded.manual_score,
                    category = excluded.category,
                    rank = excluded.rank,
                    feature_contributions_json = excluded.feature_contributions_json,
                    gate_penalty = excluded.gate_penalty,
                    ai_adjustment = excluded.ai_adjustment,
                    raw_agent_json = excluded.raw_agent_json,
                    raw_manual_json = excluded.raw_manual_json,
                    updated_at = excluded.updated_at
            """, (
                campaign_id,
                version_id,
                candidate_id,
                manual.get("manual_score"),
                manual.get("category"),
                manual.get("rank"),
                json.dumps(manual.get("feature_contributions") or {}, ensure_ascii=False),
                manual.get("gate_penalty"),
                manual.get("ai_adjustment"),
                json.dumps(agent, ensure_ascii=False),
                json.dumps(manual, ensure_ascii=False),
                now,
                now,
            ))

        # Auto-populate the tag taxonomy from this campaign's AI-designed scoring capabilities
        # (e.g. "MLOps/LLMOps Production Engineering") instead of only ever growing from
        # whatever recruiters happened to type by hand in past campaigns — a brand-new role
        # type otherwise starts with zero relevant tag suggestions.
        if pipeline_dir:
            schema_path = Path(pipeline_dir) / "data" / "ranking_feature_schema.json"
            if schema_path.exists():
                try:
                    feature_schema = json.loads(schema_path.read_text(encoding="utf-8"))
                    capabilities = feature_schema.get("capabilities") if isinstance(feature_schema, dict) else None
                    if isinstance(capabilities, list):
                        # feature_designer_agent.py sometimes emits a full descriptive sentence
                        # here instead of a short label (seen up to 200+ chars) -- those aren't
                        # tags, they're paragraph fragments, and rendering one as a tag pill
                        # breaks the campaign card layout. Keep only capability strings short
                        # enough to plausibly be a tag; real examples run ~15-40 chars
                        # ("MLOps/LLMOps Production Engineering", "Turkey/Regional Connection").
                        # Also reject anything containing a literal comma: desired_skills is
                        # serialized end-to-end as a comma-joined string (campaign_summary's
                        # GROUP_CONCAT, and the edit-campaign form's split(",")) with no escaping,
                        # so a tag like "Production-grade systems integration (APIs, databases)"
                        # gets silently sliced into garbage fragments ("...APIs" / "databases)")
                        # on display. Skip rather than reformat -- safer than guessing how to
                        # rewrite AI-generated text.
                        tag_like_capabilities = [
                            c for c in capabilities
                            if isinstance(c, str) and 0 < len(c.strip()) <= 60 and "," not in c
                        ]
                        _link_skill_names_to_campaign(conn.cursor(), campaign_id, tag_like_capabilities)
                except Exception:
                    logger.exception("Failed to auto-populate tags from %s", schema_path)

        conn.execute("""
            UPDATE pipeline_runs
            SET status = 'Completed', completed_at = ?
            WHERE id = ?
        """, (utc_now(), run_id))

        conn.commit()
    except Exception as exc:
        conn.execute("""
            UPDATE pipeline_runs
            SET status = 'Failed', completed_at = ?, error_message = ?
            WHERE id = ?
        """, (utc_now(), str(exc), run_id))
        conn.commit()
        conn.close()
        raise HTTPException(status_code=500, detail=f"Import failed: {exc}")

    conn.close()
    return {
        "success": True,
        "run_id": run_id,
        "artifact_path": str(artifact_file),
        "config_version_id": version_id,
        "created_candidates": created_count,
        "updated_candidates": updated_count,
        "linked_to_campaign": linked_count,
    }


@app.get("/api/campaigns/{campaign_id}/export/excel")
def export_campaign_excel(
    campaign_id: int,
    config_version_id: Optional[int] = Query(default=None),
    token: Optional[str] = Query(default=None),
    authorization: Optional[str] = Header(default=None),
):
    if authorization and authorization.startswith("Bearer "):
        raw_token = authorization.replace("Bearer ", "").strip()
    elif token:
        raw_token = token.strip()
    else:
        raise HTTPException(status_code=401, detail="Not authenticated")

    current_user = _get_current_user_from_raw_token(raw_token)

    conn = get_connection()

    campaign = _get_owned_campaign(conn, campaign_id, current_user)
    if not campaign:
        conn.close()
        raise HTTPException(status_code=404, detail="Campaign not found")

    try:
        pipeline_dir = _resolve_pipeline_dir(conn, campaign_id, current_user, config_version_id)
    finally:
        conn.close()

    output_dir = pipeline_dir / "output"
    xlsx_files = sorted(
        output_dir.glob("shortlist_*.xlsx"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if not xlsx_files:
        raise HTTPException(status_code=404, detail="No Excel export found. Run the pipeline first.")

    latest = xlsx_files[0]
    download_name = f"{campaign['campaign_code']}_candidates.xlsx"

    return FileResponse(
        path=latest,
        filename=download_name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _resolve_ranked_results_artifact(
    conn,
    campaign_id: int,
    current_user,
    config_version_id: Optional[int] = None,
):
    pipeline_dir = _resolve_pipeline_dir(conn, campaign_id, current_user, config_version_id)
    return pipeline_dir / "data" / "ranked_results.json"


def _resolve_pipeline_dir(
    conn,
    campaign_id: int,
    current_user,
    config_version_id: Optional[int] = None,
) -> Path:
    """Folder holding a campaign's pipeline artifacts — per config version.

    Each version has its own folder, so passing config_version_id reads that version's
    artifacts (search results, ranked output, scoring policy) instead of the newest ones.
    """
    if not _get_owned_campaign(conn, campaign_id, current_user):
        raise HTTPException(status_code=404, detail="Campaign not found")

    version_row = _get_config_version(conn, campaign_id, config_version_id)
    if config_version_id is not None and not version_row:
        raise HTTPException(status_code=404, detail="Config version not found")

    pipeline_dir = (version_row["pipeline_dir"] if version_row else "").strip()
    if not pipeline_dir:
        raise HTTPException(
            status_code=400,
            detail="No pipeline config found. Save pipeline config first.",
        )

    return Path(pipeline_dir)


def _resolve_search_results_files(
    conn,
    campaign_id: int,
    current_user,
    config_version_id: Optional[int] = None,
) -> list[Path]:
    pipeline_dir = _resolve_pipeline_dir(conn, campaign_id, current_user, config_version_id)
    data_dir = pipeline_dir / "data"
    if not data_dir.exists():
        return []

    return sorted(data_dir.glob("*/raw_results.json"))


@app.get("/api/campaigns/{campaign_id}/pipeline/scoring-explainer")
def get_scoring_explainer(
    campaign_id: int,
    config_version_id: Optional[int] = Query(default=None),
    current_user=Depends(get_current_user),
):
    """Feature schema + scoring policy for this campaign, so the UI can show *why* each
    feature exists (name/description/reason) and how much it weighs — not just a bare
    feature_id and a number. Recruiters otherwise have no way to tell what a score is
    actually measuring or how it was weighted.

    Version-scoped: each config version designs its own features, so an old version's
    candidate list is explained by the policy that actually scored it."""
    conn = get_connection()
    try:
        pipeline_dir = _resolve_pipeline_dir(conn, campaign_id, current_user, config_version_id)
    finally:
        conn.close()

    schema_path = pipeline_dir / "data" / "ranking_feature_schema.json"
    policy_path = pipeline_dir / "data" / "ranking_scoring_policy.json"

    feature_schema = {}
    if schema_path.exists():
        try:
            feature_schema = json.loads(schema_path.read_text(encoding="utf-8"))
        except Exception:
            feature_schema = {}

    scoring_policy = {}
    if policy_path.exists():
        try:
            scoring_policy = json.loads(policy_path.read_text(encoding="utf-8"))
        except Exception:
            scoring_policy = {}

    features = feature_schema.get("features") if isinstance(feature_schema, dict) else None
    features = features if isinstance(features, list) else []
    weights = scoring_policy.get("weights") if isinstance(scoring_policy, dict) else None
    weights = weights if isinstance(weights, dict) else {}
    hard_gates = scoring_policy.get("hard_gates") if isinstance(scoring_policy, dict) else None
    hard_gates = hard_gates if isinstance(hard_gates, list) else []

    features_by_id = {}
    for feat in features:
        if not isinstance(feat, dict) or not feat.get("id"):
            continue
        fid = str(feat["id"])
        features_by_id[fid] = {
            "id": fid,
            "name": feat.get("name") or fid,
            "description": feat.get("description") or "",
            "reason": feat.get("reason") or "",
            "max_points": feat.get("max_points"),
            "weight_pct": weights.get(fid),
        }

    return {
        "exists": bool(features_by_id),
        "features": list(features_by_id.values()),
        "hard_gates": hard_gates,
        "tiers": scoring_policy.get("tiers") if isinstance(scoring_policy, dict) else None,
        "capabilities": feature_schema.get("capabilities") if isinstance(feature_schema, dict) else [],
        "schema_fallback": bool(feature_schema.get("fallback")) if isinstance(feature_schema, dict) else False,
    }


@app.get("/api/campaigns/{campaign_id}/pipeline/usage-summary")
def get_usage_summary_endpoint(
    campaign_id: int,
    config_version_id: Optional[int] = Query(default=None),
    current_user=Depends(get_current_user),
):
    """LLM cost/token usage for this campaign's most recent pipeline run.

    Written by run_campaign.py at the end of each run to data/usage_summary.json. Older
    campaigns run before this was added won't have the file yet -- exists=False in that case.
    """
    conn = get_connection()
    try:
        pipeline_dir = _resolve_pipeline_dir(conn, campaign_id, current_user, config_version_id)
    finally:
        conn.close()

    usage_path = pipeline_dir / "data" / "usage_summary.json"
    if not usage_path.exists():
        return {"exists": False}

    try:
        usage = json.loads(usage_path.read_text(encoding="utf-8"))
    except Exception:
        return {"exists": False}

    return {"exists": True, **usage}


@app.get("/api/campaigns/{campaign_id}/pipeline/search-results-status")
def get_search_results_status(
    campaign_id: int,
    config_version_id: Optional[int] = Query(default=None),
    current_user=Depends(get_current_user),
):
    conn = get_connection()
    try:
        files = _resolve_search_results_files(conn, campaign_id, current_user, config_version_id)
    finally:
        conn.close()

    total_candidates = 0
    for path in files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, list):
            total_candidates += len(payload)

    return {
        "exists": bool(files),
        "file_count": len(files),
        "total_candidates": total_candidates,
        "artifact_paths": [str(path) for path in files],
    }


@app.get("/api/campaigns/{campaign_id}/pipeline/export-search-csv")
def export_search_csv(
    campaign_id: int,
    config_version_id: Optional[int] = Query(default=None),
    current_user=Depends(get_current_user),
):
    conn = get_connection()
    try:
        files = _resolve_search_results_files(conn, campaign_id, current_user, config_version_id)
    finally:
        conn.close()

    if not files:
        raise HTTPException(status_code=404, detail="No search raw_results.json files found")

    rows: list[dict] = []
    for path in files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, list):
            rows.extend(item for item in payload if isinstance(item, dict))

    if not rows:
        raise HTTPException(status_code=404, detail="Search results files are empty")

    flattened_rows, ordered_fields = _build_csv_rows(rows, SEARCH_CSV_EXCLUDED_FIELDS)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=ordered_fields)
    writer.writeheader()
    for flat in flattened_rows:
        writer.writerow(flat)

    csv_bytes = output.getvalue().encode("utf-8")
    filename = f"campaign_{campaign_id}_search_results.csv"

    return StreamingResponse(
        iter([csv_bytes]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/api/campaigns/{campaign_id}/pipeline/ranked-results-status")
def get_ranked_results_status(
    campaign_id: int,
    config_version_id: Optional[int] = Query(default=None),
    current_user=Depends(get_current_user),
):
    conn = get_connection()
    try:
        artifact_file = _resolve_ranked_results_artifact(
            conn,
            campaign_id,
            current_user,
            config_version_id,
        )
    finally:
        conn.close()

    return {
        "exists": artifact_file.exists(),
        "artifact_path": str(artifact_file),
    }


@app.get("/api/campaigns/{campaign_id}/pipeline/export-ranked-csv")
def export_ranked_csv(
    campaign_id: int,
    config_version_id: Optional[int] = Query(default=None),
    current_user=Depends(get_current_user),
):
    conn = get_connection()
    try:
        artifact_file = _resolve_ranked_results_artifact(
            conn,
            campaign_id,
            current_user,
            config_version_id,
        )
    finally:
        conn.close()

    if not artifact_file.exists():
        raise HTTPException(status_code=404, detail="ranked_results.json not found")

    rows = json.loads(artifact_file.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise HTTPException(status_code=400, detail="ranked_results.json must contain a list")

    flattened_rows, ordered_fields = _build_csv_rows(
        rows,
        RANKED_CSV_EXCLUDED_FIELDS,
        rank_summary_only=True,
    )
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=ordered_fields)
    writer.writeheader()
    for flat in flattened_rows:
        writer.writerow(flat)

    csv_bytes = output.getvalue().encode("utf-8")
    filename = f"campaign_{campaign_id}_ranked_results.csv"

    return StreamingResponse(
        iter([csv_bytes]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/api/campaigns/{campaign_id}/rankings")
def list_campaign_rankings(
    campaign_id: int,
    config_version_id: Optional[int] = Query(default=None),
    current_user=Depends(get_current_user),
):
    """Rankings for one config version — the current one unless another is requested."""
    conn = get_connection()

    if not _get_owned_campaign(conn, campaign_id, current_user):
        conn.close()
        raise HTTPException(status_code=404, detail="Campaign not found")

    version_row = _get_config_version(conn, campaign_id, config_version_id)
    if config_version_id is not None and not version_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Config version not found")

    version_id = version_row["id"] if version_row else 0

    rows = conn.execute("""
        SELECT
            cr.candidate_id,
            c.full_name,
            c.profile_url,
            c.current_title,
            c.location,
            c.status,
            cr.manual_score,
            cr.category,
            cr.rank,
            cr.feature_contributions_json,
            cr.gate_penalty,
            cr.ai_adjustment,
            cr.raw_agent_json,
            cr.raw_manual_json,
            cr.updated_at
        FROM candidate_rankings cr
        JOIN candidates c ON c.id = cr.candidate_id
        WHERE cr.campaign_id = ? AND cr.config_version_id = ?
        ORDER BY cr.rank ASC, cr.manual_score DESC
    """, (campaign_id, version_id)).fetchall()
    conn.close()

    results = []
    for row in rows:
        item = dict(row)
        item["feature_contributions"] = json.loads(item.pop("feature_contributions_json") or "{}")
        item["agent"] = json.loads(item.pop("raw_agent_json") or "{}")
        item["manual"] = json.loads(item.pop("raw_manual_json") or "{}")
        results.append(item)

    return results


@app.get("/api/campaigns/{campaign_id}/candidates")
def list_campaign_candidates(
    campaign_id: int,
    page: int = 1,
    page_size: int = 10,
    config_version_id: Optional[int] = Query(default=None),
    current_user=Depends(get_current_user),
):
    """Candidates for a campaign.

    With `config_version_id`, returns just the candidates that version's run produced — one
    distinct list per config the recruiter has run. Without it, returns every candidate ever
    found for the campaign (all versions combined), which is what the dashboard shows.
    """
    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 10
    if page_size > 50:
        page_size = 50

    offset = (page - 1) * page_size

    conn = get_connection()

    if not _get_owned_campaign(conn, campaign_id, current_user):
        conn.close()
        raise HTTPException(status_code=404, detail="Campaign not found")

    if config_version_id is not None:
        version_row = _get_config_version(conn, campaign_id, config_version_id)
        if not version_row:
            conn.close()
            raise HTTPException(status_code=404, detail="Config version not found")

        # candidate_rankings is the per-version membership record: the import writes one row per
        # candidate in that version's ranked_results.json.
        membership_sql = """
            FROM candidate_rankings cr
            JOIN candidates cand ON cand.id = cr.candidate_id
            LEFT JOIN candidate_skills cs ON cs.candidate_id = cand.id
            LEFT JOIN skills s ON s.id = cs.skill_id
            WHERE cr.campaign_id = ? AND cr.config_version_id = ?
        """
        membership_params = (campaign_id, config_version_id)
        count_sql = """
            SELECT COUNT(*) AS count
            FROM candidate_rankings
            WHERE campaign_id = ? AND config_version_id = ?
        """
    else:
        membership_sql = """
            FROM campaign_candidates cc
            JOIN candidates cand ON cand.id = cc.candidate_id
            LEFT JOIN candidate_skills cs ON cs.candidate_id = cand.id
            LEFT JOIN skills s ON s.id = cs.skill_id
            LEFT JOIN candidate_rankings cr
                ON cr.campaign_id = cc.campaign_id
                AND cr.candidate_id = cc.candidate_id
            WHERE cc.campaign_id = ?
        """
        membership_params = (campaign_id,)
        count_sql = """
            SELECT COUNT(*) AS count
            FROM campaign_candidates
            WHERE campaign_id = ?
        """

    total_count = conn.execute(count_sql, membership_params).fetchone()["count"]

    rows = conn.execute(
        f"""
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
            cand.english_confidence,
            cand.english_confidence_reason,
            cand.last_updated,
            cand.notes,
            GROUP_CONCAT(DISTINCT s.name) AS skills,
            cr.manual_score,
            cr.category AS ranking_category,
            cr.rank AS ranking_rank,
            cr.feature_contributions_json,
            cr.raw_agent_json,
            cr.raw_manual_json
        {membership_sql}
        GROUP BY cand.id
        ORDER BY COALESCE(cr.rank, 999999) ASC, cand.score DESC
        LIMIT ? OFFSET ?
        """,
        (*membership_params, page_size, offset),
    ).fetchall()
    conn.close()

    candidates = []
    for row in rows:
        item = dict(row)
        item["ranking"] = {
            "manual_score": item.pop("manual_score"),
            "category": item.pop("ranking_category"),
            "rank": item.pop("ranking_rank"),
            "feature_contributions": json.loads(item.pop("feature_contributions_json") or "{}"),
            "agent": json.loads(item.pop("raw_agent_json") or "{}"),
            "manual": json.loads(item.pop("raw_manual_json") or "{}"),
        }
        candidates.append(item)

    total_pages = (total_count + page_size - 1) // page_size if total_count else 0

    return {
        "items": candidates,
        "config_version_id": config_version_id,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_items": total_count,
            "total_pages": total_pages,
        },
    }


@app.get("/api/campaigns/active")
def list_active_campaigns(current_user=Depends(get_current_user)):
    conn = get_connection()
    if current_user["role"] == "admin":
        rows = conn.execute("""
            SELECT *
            FROM campaign_summary
            WHERE status = 'Active'
            ORDER BY created_at DESC
        """).fetchall()
    else:
        rows = conn.execute("""
            SELECT *
            FROM campaign_summary
            WHERE status = 'Active' AND created_by_user_id = ?
            ORDER BY created_at DESC
        """, (current_user["id"],)).fetchall()
    conn.close()

    return [dict(row) for row in rows]


@app.get("/api/campaigns/past")
def list_past_campaigns(current_user=Depends(get_current_user)):
    conn = get_connection()
    if current_user["role"] == "admin":
        rows = conn.execute("""
            SELECT *
            FROM campaign_summary
            WHERE status = 'Past'
            ORDER BY created_at DESC
        """).fetchall()
    else:
        rows = conn.execute("""
            SELECT *
            FROM campaign_summary
            WHERE status = 'Past' AND created_by_user_id = ?
            ORDER BY created_at DESC
        """, (current_user["id"],)).fetchall()
    conn.close()

    return [dict(row) for row in rows]


@app.get("/api/candidates")
def list_candidates(current_user=Depends(get_current_user)):
    conn = get_connection()
    rows = conn.execute("""
        SELECT *
        FROM candidate_profile_summary
        ORDER BY score DESC
    """).fetchall()
    conn.close()

    return [dict(row) for row in rows]


@app.get("/api/skills")
def list_skills(current_user=Depends(get_current_user)):
    conn = get_connection()
    rows = conn.execute("""
        SELECT name
        FROM skills
        ORDER BY name
    """).fetchall()
    conn.close()

    return [row["name"] for row in rows]


@app.post("/api/candidates/refresh")
def refresh_candidates(current_user=Depends(get_current_user)):
    conn = get_connection()

    now = datetime.utcnow().isoformat(timespec="seconds")

    conn.execute("""
        UPDATE candidates
        SET 
            last_updated = ?,
            score = CASE
                WHEN score < 99 THEN score + 1
                ELSE score
            END
    """, (now,))

    conn.execute("""
        INSERT INTO refresh_logs (
            candidate_id,
            refresh_type,
            status,
            message,
            created_at
        )
        VALUES (
            NULL,
            'bulk_profile_refresh',
            'Success',
            'Mock candidate refresh completed.',
            ?
        )
    """, (now,))

    conn.commit()
    conn.close()

    return {"success": True, "message": "Candidates refreshed"}


def _link_skill_names_to_campaign(cur, campaign_id: int, skill_names) -> None:
    """Ensure each skill name exists in `skills` and is linked to this campaign."""
    for skill in skill_names:
        skill = str(skill or "").strip()
        if not skill:
            continue

        cur.execute("INSERT OR IGNORE INTO skills (name) VALUES (?)", (skill,))
        skill_row = cur.execute("SELECT id FROM skills WHERE name = ?", (skill,)).fetchone()
        cur.execute(
            "INSERT OR IGNORE INTO campaign_skills (campaign_id, skill_id) VALUES (?, ?)",
            (campaign_id, skill_row["id"]),
        )


def _save_uploaded_sample_cv(sample_cv: Optional[UploadFile]) -> Optional[str]:
    """Save an uploaded sample CV to UPLOAD_DIR and return its stored filename, or None."""
    if sample_cv is None or not sample_cv.filename:
        return None

    if not sample_cv.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    safe_filename = sample_cv.filename.replace(" ", "_")
    saved_filename = f"{timestamp}_{safe_filename}"
    saved_path = UPLOAD_DIR / saved_filename

    with open(saved_path, "wb") as buffer:
        shutil.copyfileobj(sample_cv.file, buffer)

    return saved_filename


def _sync_pipeline_config_for_campaign(conn, campaign_id: int, target_profiles, sample_cv_filename):
    """Propagate a campaign's target_profiles / sample CV into an already-set-up pipeline.

    setup_pipeline_campaign() bakes these into campaign.yaml / input/seed_cvs/ at setup time,
    but editing a campaign afterwards (via update_campaign) previously never touched the
    pipeline directory at all, so changing "Target Profiles" or re-uploading a CV after setup
    had no effect on future pipeline runs. This keeps them in sync.
    """
    config_row = conn.execute(
        "SELECT pipeline_dir FROM pipeline_campaign_configs WHERE campaign_id = ?",
        (campaign_id,),
    ).fetchone()
    if not config_row or not config_row["pipeline_dir"]:
        return

    pipeline_dir = Path(config_row["pipeline_dir"])
    campaign_yaml_path = pipeline_dir / "campaign.yaml"

    if target_profiles and campaign_yaml_path.exists():
        try:
            config = yaml.safe_load(campaign_yaml_path.read_text(encoding="utf-8")) or {}
            config.setdefault("filter", {})["max_candidates"] = int(target_profiles)
            campaign_yaml_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        except Exception:
            logger.exception("Failed to sync target_profiles into %s", campaign_yaml_path)

    if sample_cv_filename:
        source_cv_path = UPLOAD_DIR / sample_cv_filename
        if source_cv_path.exists():
            seed_cv_dir = pipeline_dir / "input" / "seed_cvs"
            seed_cv_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_cv_path, seed_cv_dir / source_cv_path.name)


@app.post("/api/campaigns")
def create_campaign(
    campaign_name: str = Form(...),
    location: str = Form(...),
    position_name: str = Form(...),
    experience: str = Form(...),
    desired_skills: str = Form(...),
    target_profiles: int = Form(25),
    sample_cv: Optional[UploadFile] = File(None),
    current_user=Depends(get_current_user)
):
    # FIX 1: Fixed Deprecation Warning by using timezone-aware UTC datetime
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    saved_filename = _save_uploaded_sample_cv(sample_cv)

    conn = get_connection()
    cur = conn.cursor()

    def _next_campaign_code():
        # COUNT(*)-based numbering breaks as soon as any campaign is ever
        # deleted (count goes down, but existing higher codes remain), which
        # produces a code that already exists and fails the UNIQUE
        # constraint. Deriving the next number from the highest existing
        # "CMP-NNN" suffix instead is gap- and deletion-safe.
        rows = conn.execute("""
            SELECT campaign_code FROM campaigns WHERE campaign_code LIKE 'CMP-%'
        """).fetchall()
        max_n = 0
        for row in rows:
            suffix = row["campaign_code"].rsplit("-", 1)[-1]
            if suffix.isdigit():
                max_n = max(max_n, int(suffix))
        return f"CMP-{max_n + 1:03d}"

    # Retry a few times on a code collision (e.g. a concurrent request from
    # another user grabbing the same next number in the small window between
    # computing it and inserting it) rather than failing the whole request.
    for attempt in range(5):
        campaign_code = _next_campaign_code()
        try:
            cur.execute("""
               INSERT INTO campaigns (
                    campaign_code,
                    campaign_name,
                    location,
                    position_name,
                    experience,
                    sample_cv_filename,
                    target_profiles,
                    status,
                    owner,
                    created_by_user_id,
                    created_at,
                    updated_at
                )
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                campaign_code,
                campaign_name,
                location,
                position_name,
                experience,
                saved_filename,
                target_profiles,
                "Active",
                "System",
                current_user["id"],
                now,
                now
            ))
            break
        except sqlite3.IntegrityError:
            if attempt == 4:
                conn.close()
                raise
            continue

    campaign_id = cur.lastrowid

    skills = [
        skill.strip()
        for skill in desired_skills.split(",")
        if skill.strip()
    ]

    for skill in skills:

        cur.execute("""
            INSERT OR IGNORE INTO skills (name)
            VALUES (?)
        """, (skill,))

        skill_id = cur.execute("""
            SELECT id
            FROM skills
            WHERE name = ?
        """, (skill,)).fetchone()["id"]

        cur.execute("""
           INSERT OR IGNORE INTO campaign_skills (
                campaign_id,
                skill_id
           )
            VALUES (?, ?)
        """, (campaign_id, skill_id))

    conn.commit()
    conn.close()

    return {
        "success": True,
        "campaign_id": campaign_id,
        "campaign_code": campaign_code
    }



@app.get("/api/campaigns/{campaign_id}")
def get_campaign(campaign_id: int,
                 current_user=Depends(get_current_user)):
    conn = get_connection()

    if not _get_owned_campaign(conn, campaign_id, current_user):
        conn.close()
        raise HTTPException(status_code=404, detail="Campaign not found")

    row = conn.execute("""
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
            c.created_at,
            c.updated_at,
            COUNT(DISTINCT cc.candidate_id) AS candidate_count,
            SUM(
                CASE
                    WHEN cc.pipeline_stage = 'Shortlisted' THEN 1
                    ELSE 0
                END
            ) AS shortlisted_count,
            GROUP_CONCAT(DISTINCT s.name) AS desired_skills
        FROM campaigns c
        LEFT JOIN campaign_candidates cc
            ON cc.campaign_id = c.id
        LEFT JOIN campaign_skills cs
            ON cs.campaign_id = c.id
        LEFT JOIN skills s
            ON s.id = cs.skill_id
        WHERE c.id = ?
        GROUP BY c.id
    """, (campaign_id,)).fetchone()

    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Campaign not found")

    return dict(row)


@app.put("/api/campaigns/{campaign_id}")
def update_campaign(
    campaign_id: int,
    campaign_name: str = Form(...),
    location: str = Form(...),
    position_name: str = Form(...),
    experience: str = Form(...),
    desired_skills: str = Form(...),
    target_profiles: int = Form(25),
    status: str = Form("Active"),
    sample_cv: Optional[UploadFile] = File(None),
    current_user=Depends(get_current_user)
):
    conn = get_connection()
    cur = conn.cursor()
    now = datetime.utcnow().isoformat(timespec="seconds")

    if not _get_owned_campaign(conn, campaign_id, current_user):
        conn.close()
        raise HTTPException(status_code=404, detail="Campaign not found")

    # The edit form has always let recruiters re-upload a sample CV here, but this endpoint
    # never declared a sample_cv parameter, so FastAPI silently dropped it — the file was
    # never saved and never reached the pipeline. Handle it the same way create_campaign does.
    saved_filename = _save_uploaded_sample_cv(sample_cv)

    cur.execute(
        """
        UPDATE campaigns
        SET
            campaign_name = ?,
            location = ?,
            position_name = ?,
            experience = ?,
            target_profiles = ?,
            status = ?,
            sample_cv_filename = COALESCE(?, sample_cv_filename),
            updated_at = ?
        WHERE id = ?
        """,
        (
            campaign_name,
            location,
            position_name,
            experience,
            target_profiles,
            status,
            saved_filename,
            now,
            campaign_id,
        ),
    )

    _sync_pipeline_config_for_campaign(conn, campaign_id, target_profiles, saved_filename)

    cur.execute(
        "DELETE FROM campaign_skills WHERE campaign_id = ?",
        (campaign_id,)
    )

    skills = [
        skill.strip()
        for skill in desired_skills.split(",")
        if skill.strip()
    ]

    for skill in skills:
        cur.execute("""
            INSERT OR IGNORE INTO skills (name)
            VALUES (?)
        """, (skill,))

        skill_row = cur.execute("""
            SELECT id FROM skills WHERE name = ?
        """, (skill,)).fetchone()

        cur.execute("""
            INSERT OR IGNORE INTO campaign_skills (
                campaign_id,
                skill_id
            )
            VALUES (?, ?)
        """, (campaign_id, skill_row["id"]))

    conn.commit()
    conn.close()

    return {
        "success": True,
        "message": "Campaign updated successfully"
    }


@app.delete("/api/campaigns/{campaign_id}")
def delete_campaign(campaign_id: int, current_user=Depends(get_current_user)):
    conn = get_connection()

    if not _get_owned_campaign(conn, campaign_id, current_user):
        conn.close()
        raise HTTPException(status_code=404, detail="Campaign not found")

    candidate_rows = conn.execute(
        """
        SELECT DISTINCT candidate_id
        FROM campaign_candidates
        WHERE campaign_id = ?
        """,
        (campaign_id,),
    ).fetchall()
    candidate_ids = [row["candidate_id"] for row in candidate_rows]

    # Every config version has its own folder, so deleting only the current one would leak the
    # previous versions' folders onto disk.
    pipeline_dirs = {
        row["pipeline_dir"]
        for row in conn.execute(
            "SELECT pipeline_dir FROM pipeline_config_versions WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchall()
        if row["pipeline_dir"]
    }

    pipeline_cfg = conn.execute(
        """
        SELECT pipeline_dir
        FROM pipeline_campaign_configs
        WHERE campaign_id = ?
        """,
        (campaign_id,),
    ).fetchone()
    if pipeline_cfg and pipeline_cfg["pipeline_dir"]:
        pipeline_dirs.add(pipeline_cfg["pipeline_dir"])

    deleted_candidates = 0

    try:
        conn.execute("BEGIN")

        if candidate_ids:
            placeholders = ",".join("?" for _ in candidate_ids)
            conn.execute(
                f"DELETE FROM candidates WHERE id IN ({placeholders})",
                candidate_ids,
            )
            deleted_candidates = len(candidate_ids)

        conn.execute(
            "DELETE FROM campaigns WHERE id = ?",
            (campaign_id,),
        )

        for pipeline_dir in pipeline_dirs:
            _remove_pipeline_campaign_dir(pipeline_dir)

        conn.commit()
    except Exception as exc:
        conn.rollback()
        conn.close()
        raise HTTPException(
            status_code=500,
            detail=f"Campaign delete failed: {exc}",
        )

    conn.close()

    return {
        "success": True,
        "campaign_id": campaign_id,
        "deleted_candidates": deleted_candidates,
        "deleted_campaign_dir": bool(pipeline_dirs),
        "deleted_campaign_dirs": len(pipeline_dirs),
    }

@app.get("/api/candidates/{candidate_id}")
def get_candidate(candidate_id: int,
                  current_user=Depends(get_current_user)):
    conn = get_connection()

    row = conn.execute("""
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
            cand.english_confidence,
            cand.english_confidence_reason,
            cand.last_updated,
            cand.notes,
            GROUP_CONCAT(DISTINCT s.name) AS skills
        FROM candidates cand
        LEFT JOIN candidate_skills cs
            ON cs.candidate_id = cand.id
        LEFT JOIN skills s
            ON s.id = cs.skill_id
        WHERE cand.id = ?
        GROUP BY cand.id
    """, (candidate_id,)).fetchone()

    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Candidate not found")

    return dict(row)


@app.put("/api/candidates/{candidate_id}")
def update_candidate(
    candidate_id: int,
    full_name: str = Form(...),
    email: str = Form(""),
    current_title: str = Form(""),
    location: str = Form(""),
    source: str = Form("Manual"),
    profile_url: str = Form(""),
    score: int = Form(0),
    status: str = Form("New"),
    years_experience: float = Form(0),
    skills: str = Form(""),
    notes: str = Form(""),
    current_user=Depends(get_current_user)
):
    conn = get_connection()
    cur = conn.cursor()
    now = datetime.utcnow().isoformat(timespec="seconds")

    existing = conn.execute(
        "SELECT id FROM candidates WHERE id = ?",
        (candidate_id,)
    ).fetchone()

    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Candidate not found")

    cur.execute("""
        UPDATE candidates
        SET
            full_name = ?,
            email = ?,
            current_title = ?,
            location = ?,
            source = ?,
            profile_url = ?,
            score = ?,
            status = ?,
            years_experience = ?,
            notes = ?,
            last_updated = ?
        WHERE id = ?
    """, (
        full_name,
        email,
        current_title,
        location,
        source,
        profile_url,
        score,
        status,
        years_experience,
        notes,
        now,
        candidate_id
    ))

    cur.execute(
        "DELETE FROM candidate_skills WHERE candidate_id = ?",
        (candidate_id,)
    )

    skill_names = [
        skill.strip()
        for skill in skills.split(",")
        if skill.strip()
    ]

    for skill in skill_names:
        cur.execute("""
            INSERT OR IGNORE INTO skills (name)
            VALUES (?)
        """, (skill,))

        skill_row = cur.execute("""
            SELECT id FROM skills WHERE name = ?
        """, (skill,)).fetchone()

        cur.execute("""
            INSERT OR IGNORE INTO candidate_skills (
                candidate_id,
                skill_id
            )
            VALUES (?, ?)
        """, (candidate_id, skill_row["id"]))

    conn.commit()
    conn.close()

    return {
        "success": True,
        "message": "Candidate updated successfully"
    }

@app.post("/api/users")
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


@app.post("/api/auth/signin")
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


@app.post("/api/auth/signout")
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


@app.get("/api/auth/me")
def me(current_user=Depends(get_current_user)):
    return public_user(current_user)


@app.get("/api/users")
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


@app.get("/api/candidates/{candidate_id}/activities")
def get_candidate_activities(candidate_id: int, current_user=Depends(get_current_user)):
    conn = get_connection()
    rows = conn.execute("""
        SELECT a.id, a.action, a.description, a.created_at, u.full_name as user_name
        FROM audit_events a
        LEFT JOIN users u ON a.user_id = u.id
        WHERE a.entity_type IN ('candidate', 'campaign_candidate') AND a.entity_id = ?
        ORDER BY a.created_at DESC
    """, (candidate_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/api/candidates/{candidate_id}/comments")
def get_candidate_comments(candidate_id: int, current_user=Depends(get_current_user)):
    conn = get_connection()
    rows = conn.execute("""
        SELECT c.id, c.parent_id, c.content, c.created_at, u.full_name as user_name, c.user_id
        FROM candidate_comments c
        JOIN users u ON c.user_id = u.id
        WHERE c.candidate_id = ?
        ORDER BY c.created_at ASC
    """, (candidate_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/candidates/{candidate_id}/comments")
def add_candidate_comment(
    candidate_id: int, 
    content: str = Form(...), 
    parent_id: Optional[int] = Form(None), 
    current_user=Depends(get_current_user)
):
    if not content:
        raise HTTPException(status_code=400, detail="Content is required")

    conn = get_connection()
    cur = conn.cursor()
    now = datetime.utcnow().isoformat(timespec="seconds")
    
    cur.execute("""
        INSERT INTO candidate_comments (candidate_id, user_id, parent_id, content, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (candidate_id, current_user["id"], parent_id, content, now))
    
    conn.commit()
    
    # Audit event
    cur.execute("""
        INSERT INTO audit_events (entity_type, entity_id, action, description, user_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, ('candidate', candidate_id, 'Added Comment', "Comment added", current_user["id"], now))
    
    conn.commit()
    conn.close()
    
    return {"status": "success"}



# Must be mounted last: a catch-all for anything not matched by the /api/* routes above.
# nginx strips the public /hr prefix before proxying here (see PLAN.md Phase 6), so this
# serves the built frontend at the app root both in prod and in local dev/testing.
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")