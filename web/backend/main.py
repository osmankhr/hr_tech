from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from typing import Optional
import sqlite3
import shutil
import os
import json
import re
import subprocess
import threading
import time
from datetime import datetime, timezone 
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

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

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
    return conn


def ensure_pipeline_tables():
    conn = get_connection()
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

        CREATE INDEX IF NOT EXISTS idx_pipeline_runs_campaign ON pipeline_runs(campaign_id, started_at DESC);
        CREATE INDEX IF NOT EXISTS idx_candidate_rankings_campaign ON candidate_rankings(campaign_id, rank ASC);
    """)

    # Backward-compatible columns for run summary metrics.
    for alter_sql in [
        "ALTER TABLE pipeline_runs ADD COLUMN accepted_candidates INTEGER",
        "ALTER TABLE pipeline_runs ADD COLUMN ranked_candidates INTEGER",
    ]:
        try:
            conn.execute(alter_sql)
        except sqlite3.OperationalError:
            pass

    conn.commit()
    conn.close()


@app.on_event("startup")
def on_startup():
    ensure_pipeline_tables()


def _slugify(value: str):
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "campaign"


def _build_campaign_yaml(name: str, description: str, locations):
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
        "  model: openai/gpt-5.3-codex",
        "",
        "filter:",
        "  max_candidates: 10",
        "  model: openai/gpt-5.3-codex",
        "",
        "ranking:",
        "  enabled: true",
        "  model: openai/gpt-5.3-codex",
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
    rows = conn.execute("""
        SELECT *
        FROM campaign_summary
        ORDER BY created_at DESC
    """).fetchall()
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

    campaign = conn.execute(
        "SELECT id, campaign_code FROM campaigns WHERE id = ?",
        (campaign_id,),
    ).fetchone()

    if not campaign:
        conn.close()
        raise HTTPException(status_code=404, detail="Campaign not found")

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

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    folder_name = f"{_slugify(pipeline_name)}_{stamp}"
    campaign_dir = CANDIDATE_POOL_CAMPAIGNS_DIR / folder_name
    input_dir = campaign_dir / "input"

    if campaign_dir.exists():
        conn.close()
        raise HTTPException(status_code=409, detail="Pipeline campaign directory already exists")

    campaign_dir.mkdir(parents=True, exist_ok=False)
    input_dir.mkdir(parents=True, exist_ok=True)
    (campaign_dir / "data").mkdir(parents=True, exist_ok=True)
    (campaign_dir / "output").mkdir(parents=True, exist_ok=True)
    (campaign_dir / "logs").mkdir(parents=True, exist_ok=True)

    campaign_yaml_path = campaign_dir / "campaign.yaml"
    job_description_path = input_dir / "job_description.md"
    filter_criteria_path = input_dir / "filter_criteria.md"

    campaign_yaml_path.write_text(
        _build_campaign_yaml(pipeline_name, pipeline_description, cleaned_locations),
        encoding="utf-8",
    )
    job_description_path.write_text(job_description, encoding="utf-8")
    filter_criteria_path.write_text(filter_criteria, encoding="utf-8")

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

    conn.commit()
    conn.close()

    return {
        "success": True,
        "campaign_id": campaign_id,
        "pipeline_dir": str(campaign_dir),
        "campaign_yaml_path": str(campaign_yaml_path),
        "job_description_path": str(job_description_path),
        "filter_criteria_path": str(filter_criteria_path),
    }


@app.get("/api/campaigns/{campaign_id}/pipeline/runs")
def list_pipeline_runs(campaign_id: int, current_user=Depends(get_current_user)):
    conn = get_connection()
    rows = conn.execute("""
        SELECT
            id,
            campaign_id,
            run_type,
            status,
            command,
            campaign_dir,
            artifact_path,
            error_message,
            started_at,
            completed_at,
            accepted_candidates,
            ranked_candidates
        FROM pipeline_runs
        WHERE campaign_id = ?
        ORDER BY started_at DESC
    """, (campaign_id,)).fetchall()
    conn.close()

    return [dict(row) for row in rows]


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
    _get_current_user_from_raw_token(raw_token)

    def event_stream():
        last_signature = None

        while True:
            conn = get_connection()
            row = conn.execute(
                """
                SELECT
                    id,
                    campaign_id,
                    run_type,
                    status,
                    command,
                    campaign_dir,
                    artifact_path,
                    error_message,
                    started_at,
                    completed_at,
                    accepted_candidates,
                    ranked_candidates
                FROM pipeline_runs
                WHERE campaign_id = ?
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (campaign_id,),
            ).fetchone()
            conn.close()

            latest_run = dict(row) if row else None
            signature = json.dumps(latest_run, sort_keys=True, default=str)

            if signature != last_signature:
                payload = {
                    "campaign_id": campaign_id,
                    "run": latest_run,
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
    current_user=Depends(get_current_user),
):
    allowed_run_types = {
        "full": [],
        "queries": ["--queries-only"],
        "search": ["--search-only"],
        "filter": ["--filter-only"],
        "rank": ["--rank-only"],
        "report": ["--report-only"],
    }

    if run_type not in allowed_run_types:
        raise HTTPException(status_code=400, detail="Invalid run_type")

    conn = get_connection()
    config_row = conn.execute(
        """
        SELECT pipeline_dir
        FROM pipeline_campaign_configs
        WHERE campaign_id = ?
        """,
        (campaign_id,),
    ).fetchone()

    if not config_row:
        conn.close()
        raise HTTPException(status_code=400, detail="Pipeline config not found. Save config first.")

    pipeline_dir = Path(config_row["pipeline_dir"])
    if not pipeline_dir.exists():
        conn.close()
        raise HTTPException(status_code=404, detail="Pipeline directory not found")

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
            created_by_user_id
        )
        VALUES (?, ?, 'Running', ?, ?, ?, ?, ?)
        """,
        (
            campaign_id,
            run_type,
            " ".join(command),
            str(pipeline_dir),
            str(pipeline_dir / "data" / "ranked_results.json"),
            now,
            current_user["id"],
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
    current_user=Depends(get_current_user),
):
    conn = get_connection()

    campaign = conn.execute(
        "SELECT id FROM campaigns WHERE id = ?",
        (campaign_id,),
    ).fetchone()
    if not campaign:
        conn.close()
        raise HTTPException(status_code=404, detail="Campaign not found")

    config_row = conn.execute("""
        SELECT pipeline_dir
        FROM pipeline_campaign_configs
        WHERE campaign_id = ?
    """, (campaign_id,)).fetchone()

    pipeline_dir = config_row["pipeline_dir"] if config_row else ""
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
            created_by_user_id
        )
        VALUES (?, 'import', 'Running', ?, ?, ?, ?, ?)
    """, (
        campaign_id,
        "import-ranked-results",
        pipeline_dir or str(artifact_file.parent.parent),
        str(artifact_file),
        now,
        current_user["id"],
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
            title = str(item.get("title") or "").strip()
            source = str(item.get("source") or "candidate_pool")
            location = str(item.get("location") or "").strip()
            recommendation = str((item.get("ai_review") or {}).get("recommendation") or "PENDING").upper()
            candidate_status = _candidate_status_from_review(recommendation)

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
                        last_updated = ?
                    WHERE id = ?
                """, (
                    title or "Unknown Candidate",
                    email or None,
                    title,
                    location,
                    source,
                    profile_url,
                    profile_url,
                    score_int,
                    candidate_status,
                    years_experience,
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
                        last_updated,
                        notes
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    candidate_code,
                    title or "Unknown Candidate",
                    email or None,
                    title,
                    location,
                    source,
                    profile_url or None,
                    score_int,
                    candidate_status,
                    years_experience,
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
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(campaign_id, candidate_id)
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
        "created_candidates": created_count,
        "updated_candidates": updated_count,
        "linked_to_campaign": linked_count,
    }


@app.get("/api/campaigns/{campaign_id}/rankings")
def list_campaign_rankings(campaign_id: int, current_user=Depends(get_current_user)):
    conn = get_connection()
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
        WHERE cr.campaign_id = ?
        ORDER BY cr.rank ASC, cr.manual_score DESC
    """, (campaign_id,)).fetchall()
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
    current_user=Depends(get_current_user),
):
    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 10
    if page_size > 50:
        page_size = 50

    offset = (page - 1) * page_size

    conn = get_connection()
    total_count = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM campaign_candidates
        WHERE campaign_id = ?
        """,
        (campaign_id,),
    ).fetchone()["count"]

    rows = conn.execute(
        """
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
            GROUP_CONCAT(DISTINCT s.name) AS skills,
            cr.manual_score,
            cr.category AS ranking_category,
            cr.rank AS ranking_rank,
            cr.feature_contributions_json,
            cr.raw_agent_json,
            cr.raw_manual_json
        FROM campaign_candidates cc
        JOIN candidates cand ON cand.id = cc.candidate_id
        LEFT JOIN candidate_skills cs ON cs.candidate_id = cand.id
        LEFT JOIN skills s ON s.id = cs.skill_id
        LEFT JOIN candidate_rankings cr
            ON cr.campaign_id = cc.campaign_id
            AND cr.candidate_id = cc.candidate_id
        WHERE cc.campaign_id = ?
        GROUP BY cand.id
        ORDER BY COALESCE(cr.rank, 999999) ASC, cand.score DESC
        LIMIT ? OFFSET ?
        """,
        (campaign_id, page_size, offset),
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
    rows = conn.execute("""
        SELECT *
        FROM campaign_summary
        WHERE status = 'Active'
        ORDER BY created_at DESC
    """).fetchall()
    conn.close()

    return [dict(row) for row in rows]


@app.get("/api/campaigns/past")
def list_past_campaigns(current_user=Depends(get_current_user)):
    conn = get_connection()
    rows = conn.execute("""
        SELECT *
        FROM campaign_summary
        WHERE status = 'Past'
        ORDER BY created_at DESC
    """).fetchall()
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
    saved_filename = None

    if sample_cv is not None and sample_cv.filename:
        if not sample_cv.filename.lower().endswith(".pdf"):
            raise HTTPException(
                status_code=400,
                detail="Only PDF files are allowed"
            )

        # FIX 1 (Continued): Replaced deprecated utcnow for the file timestamp
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        safe_filename = sample_cv.filename.replace(" ", "_")
        saved_filename = f"{timestamp}_{safe_filename}"
        saved_path = UPLOAD_DIR / saved_filename

        with open(saved_path, "wb") as buffer:
            shutil.copyfileobj(sample_cv.file, buffer)

    conn = get_connection()
    cur = conn.cursor()

    campaign_count = conn.execute("""
        SELECT COUNT(*) AS count
        FROM campaigns
    """).fetchone()["count"]

    campaign_code = f"CMP-{campaign_count + 1:03d}"

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
            created_at,
            updated_at
        )
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        now,
        now
    ))

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
    current_user=Depends(get_current_user)
):
    conn = get_connection()
    cur = conn.cursor()
    now = datetime.utcnow().isoformat(timespec="seconds")

    existing = conn.execute(
        "SELECT id FROM campaigns WHERE id = ?",
        (campaign_id,)
    ).fetchone()

    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Campaign not found")

    cur.execute("""
        UPDATE campaigns
        SET
            campaign_name = ?,
            location = ?,
            position_name = ?,
            experience = ?,
            target_profiles = ?,
            status = ?,
            updated_at = ?
        WHERE id = ?
    """, (
        campaign_name,
        location,
        position_name,
        experience,
        target_profiles,
        status,
        now,
        campaign_id
    ))

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

    campaign = conn.execute(
        "SELECT id FROM campaigns WHERE id = ?",
        (campaign_id,),
    ).fetchone()

    if not campaign:
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

    pipeline_cfg = conn.execute(
        """
        SELECT pipeline_dir
        FROM pipeline_campaign_configs
        WHERE campaign_id = ?
        """,
        (campaign_id,),
    ).fetchone()
    pipeline_dir = pipeline_cfg["pipeline_dir"] if pipeline_cfg else None

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
        "deleted_campaign_dir": bool(pipeline_dir),
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