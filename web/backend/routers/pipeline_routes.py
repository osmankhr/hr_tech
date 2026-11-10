import csv
import io
import json
import logging
import os
import re
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Form, Header, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse

from auth_utils import utc_now
from core.auth import (
    _get_current_user_from_raw_token,
    _get_owned_campaign,
    get_current_user,
)
from core.config import (
    CANDIDATE_POOL_CAMPAIGNS_DIR,
    CANDIDATE_POOL_ROOT,
    DEFAULT_ACTIVITY_DAYS,
    MAX_WORKERS_CAP,
    UPLOAD_DIR,
)
from core.database import get_connection
from pipeline_progress import attach_pipeline_progress, clear_pipeline_progress
from pipeline_runs import PipelineRunAlreadyRunning, reserve_pipeline_run
from services.campaign_service import (
    RANKED_CSV_EXCLUDED_FIELDS,
    SEARCH_CSV_EXCLUDED_FIELDS,
    _build_campaign_yaml,
    _build_csv_rows,
    _build_mandatory_criteria_clause,
    _candidate_status_from_review,
    _extract_years_experience,
    _link_skill_names_to_campaign,
    _load_best_available_pipeline_candidates,
    _next_candidate_code,
    _parse_platforms_json,
    _pipeline_results_summary,
    _pipeline_stage_from_status,
    _read_pipeline_config_files,
    _run_pipeline_in_background,
    _slugify,
    _validate_activity_days,
    is_ing_affiliated,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["pipeline"])


def _resolve_pipeline_dir(conn, campaign_id: int, current_user) -> Path:
    if not _get_owned_campaign(conn, campaign_id, current_user):
        raise HTTPException(status_code=404, detail="Campaign not found")

    config_row = conn.execute(
        """
        SELECT pipeline_dir
        FROM pipeline_campaign_configs
        WHERE campaign_id = ?
        """,
        (campaign_id,),
    ).fetchone()

    pipeline_dir = (config_row["pipeline_dir"] if config_row else "").strip()
    if not pipeline_dir:
        raise HTTPException(
            status_code=400,
            detail="No pipeline config found. Save pipeline config first.",
        )

    return Path(pipeline_dir)


def _resolve_ranked_results_artifact(
    conn,
    campaign_id: int,
    current_user,
):
    if not _get_owned_campaign(conn, campaign_id, current_user):
        raise HTTPException(status_code=404, detail="Campaign not found")

    pipeline_dir = _resolve_pipeline_dir(conn, campaign_id, current_user)
    return pipeline_dir / "data" / "ranked_results.json"


def _resolve_search_results_files(conn, campaign_id: int, current_user) -> list[Path]:
    pipeline_dir = _resolve_pipeline_dir(conn, campaign_id, current_user)
    data_dir = pipeline_dir / "data"
    if not data_dir.exists():
        return []

    return sorted(data_dir.glob("*/raw_results.json"))


@router.post("/api/campaigns/{campaign_id}/pipeline/setup")
def setup_pipeline_campaign(
    campaign_id: int,
    pipeline_name: str = Form(...),
    pipeline_description: str = Form(...),
    locations_json: str = Form(...),
    job_description: str = Form(...),
    filter_criteria: str = Form(...),
    platforms_json: Optional[str] = Form(default=None),
    activity_days: Optional[int] = Form(default=DEFAULT_ACTIVITY_DAYS),
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
        cleaned_platforms = _parse_platforms_json(platforms_json)
        validated_activity_days = _validate_activity_days(activity_days)
    except HTTPException:
        conn.close()
        raise

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

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
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
        _build_campaign_yaml(
            pipeline_name,
            pipeline_description,
            cleaned_locations,
            max_candidates=None,
            platforms=cleaned_platforms,
            activity_days=validated_activity_days,
        ),
        encoding="utf-8",
    )
    job_description_path.write_text(job_description, encoding="utf-8")

    mandatory_clause = _build_mandatory_criteria_clause(
        cleaned_locations,
        pipeline_name=pipeline_name,
        job_description=job_description,
    )
    full_filter_criteria = (
        f"{mandatory_clause}\n{filter_criteria}" if mandatory_clause else filter_criteria
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


@router.get("/api/campaigns/{campaign_id}/pipeline/config-versions")
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


@router.put("/api/campaigns/{campaign_id}/pipeline/config")
def update_pipeline_config(
    campaign_id: int,
    pipeline_name: str = Form(...),
    pipeline_description: str = Form(...),
    locations_json: str = Form(...),
    job_description: str = Form(...),
    filter_criteria: str = Form(...),
    platforms_json: Optional[str] = Form(default=None),
    activity_days: Optional[int] = Form(default=DEFAULT_ACTIVITY_DAYS),
    current_user=Depends(get_current_user),
):
    conn = get_connection()

    campaign = _get_owned_campaign(conn, campaign_id, current_user)
    if not campaign:
        conn.close()
        raise HTTPException(status_code=404, detail="Campaign not found")

    try:
        cleaned_platforms = _parse_platforms_json(platforms_json)
        validated_activity_days = _validate_activity_days(activity_days)
    except HTTPException:
        conn.close()
        raise

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
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
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
        _build_campaign_yaml(
            pipeline_name,
            pipeline_description,
            cleaned_locations,
            max_candidates=None,
            platforms=cleaned_platforms,
            activity_days=validated_activity_days,
        ),
        encoding="utf-8",
    )
    job_description_path.write_text(job_description, encoding="utf-8")

    mandatory_clause = _build_mandatory_criteria_clause(
        cleaned_locations,
        pipeline_name=pipeline_name,
        job_description=job_description,
    )
    full_filter_criteria = (
        f"{mandatory_clause}\n{filter_criteria}" if mandatory_clause else filter_criteria
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
    location_label = ", ".join(loc["name"] for loc in cleaned_locations if loc.get("name"))
    conn.execute(
        """
        UPDATE campaigns
        SET campaign_name = ?, location = CASE WHEN ? != '' THEN ? ELSE location END
        WHERE id = ?
        """,
        (pipeline_name, location_label, location_label, campaign_id),
    )
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


@router.get("/api/campaigns/{campaign_id}/pipeline/runs")
def list_pipeline_runs(campaign_id: int, current_user=Depends(get_current_user)):
    conn = get_connection()

    if not _get_owned_campaign(conn, campaign_id, current_user):
        conn.close()
        raise HTTPException(status_code=404, detail="Campaign not found")

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

    return [
        attach_pipeline_progress(
            dict(row),
            campaigns_root=CANDIDATE_POOL_CAMPAIGNS_DIR,
        )
        for row in rows
    ]


@router.get("/api/campaigns/{campaign_id}/pipeline/events")
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

            latest_run = (
                attach_pipeline_progress(
                    dict(row),
                    campaigns_root=CANDIDATE_POOL_CAMPAIGNS_DIR,
                )
                if row
                else None
            )
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


@router.post("/api/campaigns/{campaign_id}/pipeline/run")
def run_pipeline(
    campaign_id: int,
    run_type: str = Form("full"),
    max_candidates: Optional[int] = Form(default=None),
    current_user=Depends(get_current_user),
):
    allowed_run_types = {
        "full": ["--force-queries", "--force-ranking-redesign"],
        "queries": ["--queries-only", "--force-queries"],
        "search": ["--search-only"],
        "filter": ["--filter-only"],
        "rank": ["--rank-only", "--force-ranking-redesign"],
        "report": ["--report-only"],
    }

    if run_type not in allowed_run_types:
        raise HTTPException(status_code=400, detail="Invalid run_type")

    if max_candidates is not None and max_candidates < 1:
        raise HTTPException(status_code=400, detail="max_candidates must be at least 1")

    conn = get_connection()

    if not _get_owned_campaign(conn, campaign_id, current_user):
        conn.close()
        raise HTTPException(status_code=404, detail="Campaign not found")

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

    preferred_venv_python = CANDIDATE_POOL_ROOT / ".venv" / "bin" / "python"
    preferred_venv_windows = CANDIDATE_POOL_ROOT / ".venv" / "Scripts" / "python.exe"
    python_bin = os.getenv("CANDIDATE_POOL_PYTHON")
    if not python_bin:
        if preferred_venv_windows.exists():
            python_bin = str(preferred_venv_windows)
        elif preferred_venv_python.exists():
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
    command_text = " ".join(command)
    try:
        run_id = reserve_pipeline_run(
            conn,
            campaign_id=campaign_id,
            run_type=run_type,
            command=command_text,
            campaign_dir=str(pipeline_dir),
            artifact_path=str(pipeline_dir / "data" / "ranked_results.json"),
            started_at=now,
            created_by_user_id=current_user["id"],
        )
    except PipelineRunAlreadyRunning:
        conn.close()
        raise HTTPException(status_code=409, detail="A pipeline run is already in progress")
    except Exception:
        conn.close()
        raise

    clear_pipeline_progress(
        pipeline_dir,
        campaigns_root=CANDIDATE_POOL_CAMPAIGNS_DIR,
    )
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
        "command": command_text,
    }


@router.post("/api/campaigns/{campaign_id}/pipeline/import-ranked")
def import_ranked_results(
    campaign_id: int,
    ranked_results_path: str = Form(""),
    current_user=Depends(get_current_user),
):
    conn = get_connection()

    if not _get_owned_campaign(conn, campaign_id, current_user):
        conn.close()
        raise HTTPException(status_code=404, detail="Campaign not found")

    config_row = conn.execute("""
        SELECT pipeline_dir
        FROM pipeline_campaign_configs
        WHERE campaign_id = ?
    """, (campaign_id,)).fetchone()

    pipeline_dir = config_row["pipeline_dir"] if config_row else ""
    artifact_path = ranked_results_path.strip()
    preloaded_candidates: Optional[list[dict]] = None
    if not artifact_path:
        if not pipeline_dir:
            conn.close()
            raise HTTPException(
                status_code=400,
                detail="No pipeline config found. Provide ranked_results_path or setup pipeline first.",
            )
        ranked_candidate_file = Path(pipeline_dir) / "data" / "ranked_results.json"
        if ranked_candidate_file.exists():
            artifact_file = ranked_candidate_file
        else:
            preloaded_candidates, fallback_file = _load_best_available_pipeline_candidates(Path(pipeline_dir))
            if not fallback_file or not preloaded_candidates:
                conn.close()
                raise HTTPException(status_code=404, detail="No pipeline results found yet")
            artifact_file = fallback_file
    else:
        artifact_file = Path(artifact_path).resolve()
        if not (
            artifact_file.is_relative_to(CANDIDATE_POOL_ROOT.resolve())
            or artifact_file.is_relative_to(UPLOAD_DIR.resolve())
        ):
            conn.close()
            raise HTTPException(status_code=403, detail="artifact_path must be within candidate_pool directory")
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
        if preloaded_candidates is not None:
            ranked_candidates = preloaded_candidates
        else:
            ranked_candidates = json.loads(artifact_file.read_text(encoding="utf-8"))
        if not isinstance(ranked_candidates, list):
            raise ValueError("Candidate results file must contain a list")

        created_count = 0
        updated_count = 0
        linked_count = 0

        camp_meta = conn.execute(
            "SELECT campaign_name, position_name, experience FROM campaigns WHERE id = ?",
            (campaign_id,),
        ).fetchone()
        is_senior_role = False
        if camp_meta:
            pos_combined = f"{camp_meta['campaign_name'] or ''} {camp_meta['position_name'] or ''}".lower()
            exp_combined = str(camp_meta["experience"] or "").lower()
            if any(k in pos_combined for k in ("senior", "lead", "principal", "staff")) or "5+" in exp_combined:
                is_senior_role = True

        for item in ranked_candidates:
            if not isinstance(item, dict):
                continue

            profile_url = str(item.get("url") or "").strip()
            email = str(item.get("email") or "").strip().lower()

            raw_text = str(item.get("text") or "")
            full_name = str(item.get("name") or item.get("title") or "").strip()
            full_name = re.sub(r"\s*[\|\-–—]\s*(LinkedIn|Kaggle|GitHub|Hugging Face).*$", "", full_name, flags=re.IGNORECASE).strip()
            if " - " in full_name:
                cand_name_prefix, _ = full_name.split(" - ", 1)
                if len(cand_name_prefix) < 40 and not ("/" in cand_name_prefix or "http" in cand_name_prefix.lower()):
                    full_name = cand_name_prefix.strip()

            if "/" in full_name or full_name.lower().startswith("http") or "github.com" in full_name.lower():
                m_name = re.search(r"Candidate Name:\s*([^\n\r(@]+)", raw_text)
                if m_name and "/" not in m_name.group(1):
                    full_name = m_name.group(1).strip()
                else:
                    full_name = str(item.get("info", {}).get("username") or item.get("username") or "Developer").strip()

            trunc_m = re.match(r"^([A-ZÇĞİÖŞÜa-zçğıöşü]+)\s+([A-ZÇĞİÖŞÜ])\.?$", full_name)
            if trunc_m:
                first_name = trunc_m.group(1)
                last_initial = trunc_m.group(2).lower()
                slug_m = re.search(r"/in/([a-z0-9\-]+)", profile_url.lower())
                if slug_m:
                    slug_parts = slug_m.group(1).split("-")
                    if len(slug_parts) >= 2:
                        cand_last = slug_parts[-1]
                        if cand_last.lower().startswith(last_initial) and len(cand_last) > 2:
                            text_surname_m = re.search(rf"\b{first_name}\s+([A-ZÇĞİÖŞÜa-zçğıöşü]+)\b", raw_text, re.IGNORECASE)
                            if text_surname_m and text_surname_m.group(1).lower().startswith(last_initial):
                                full_name = f"{first_name} {text_surname_m.group(1)}"
                            else:
                                full_name = f"{first_name} {cand_last.capitalize()}"

            job_title = str(item.get("extracted_title") or item.get("title") or "").strip() or full_name
            source = str(item.get("source") or "candidate_pool")
            location = str(item.get("location") or "").strip()
            ai_rev = item.get("ai_review") or {}
            recommendation = str(ai_rev.get("recommendation") or ai_rev.get("decision") or "PENDING").upper()
            if recommendation == "APPROVE":
                recommendation = "SHORTLIST"
            ranking_obj = item.get("ranking") or {}
            manual = ranking_obj.get("manual") or {}
            agent = ranking_obj.get("agent") or {}
            category_val = str(manual.get("category") or ranking_obj.get("category") or "").upper()
            manual_score = (
                manual.get("manual_score")
                if manual.get("manual_score") is not None
                else (
                    manual.get("total_score")
                    if manual.get("total_score") is not None
                    else ranking_obj.get("manual_score")
                )
            )
            score_value = manual_score if manual_score is not None else (item.get("score") or 0)

            years_experience = _extract_years_experience(raw_text)

            # Hard Gate 1: Strict ING Affiliation Exclusion
            if is_ing_affiliated(full_name) or is_ing_affiliated(job_title) or is_ing_affiliated(raw_text):
                category_val = "REJECT"
                score_value = 0
                manual_score = 0.0

            # Hard Gate 2: Seniority & Trainee / Low Experience Exclusion
            is_trainee_or_intern = bool(
                re.search(r"\b(trainee|intern|internship|stajyer|staj)\b", f"{job_title} {raw_text[:600]}", re.IGNORECASE)
            )
            if is_senior_role:
                if (years_experience is not None and years_experience < 3.0) or (is_trainee_or_intern and (years_experience is None or years_experience < 4.0)):
                    category_val = "REJECT"
                    if score_value is not None:
                        try:
                            score_value = min(float(score_value), 35.0)
                        except (TypeError, ValueError):
                            score_value = 0.0
                    if manual_score is not None:
                        try:
                            manual_score = min(float(manual_score), 35.0)
                        except (TypeError, ValueError):
                            manual_score = 0.0

            if category_val == "SHORTLIST":
                candidate_status = "Shortlisted"
            elif category_val == "REJECT":
                candidate_status = "Rejected"
            elif category_val in ("BACKUP", "REVIEW"):
                candidate_status = "Reviewed"
            else:
                candidate_status = _candidate_status_from_review(recommendation)

            english_confidence = str(item.get("english_confidence") or "").strip().upper() or None
            english_confidence_reason = str(item.get("english_confidence_reason") or "").strip() or None

            try:
                raw_float = float(score_value)
                if manual_score is None and 0.0 < raw_float <= 1.0:
                    raw_float = raw_float * 100.0
                score_int = int(round(raw_float))
            except (TypeError, ValueError):
                score_int = 0

            score_int = max(0, min(100, score_int))
            years_experience = _extract_years_experience(str(item.get("text") or ""))

            ai_reasoning = str((item.get("ai_review") or {}).get("reasoning") or "").strip()
            raw_highlights = item.get("highlights")
            highlights_summary = (
                "\n".join(str(h).strip() for h in raw_highlights if str(h).strip())
                if isinstance(raw_highlights, list)
                else ""
            )
            candidate_notes = ai_reasoning or highlights_summary or None

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
                        notes = COALESCE(?, notes),
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
                    candidate_notes,
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
                    candidate_notes,
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

            pmeta = item.get("platform_metadata") or {}
            raw_skills = list(item.get("skills") or [])
            for extra_list in (pmeta.get("top_languages"), pmeta.get("pipeline_tags")):
                if isinstance(extra_list, list):
                    raw_skills.extend(extra_list)
            for skill_name in raw_skills:
                cleaned_skill = str(skill_name or "").strip()
                if not cleaned_skill:
                    continue
                conn.execute("INSERT OR IGNORE INTO skills (name) VALUES (?)", (cleaned_skill,))
                skill_row = conn.execute("SELECT id FROM skills WHERE name = ?", (cleaned_skill,)).fetchone()
                if skill_row:
                    conn.execute(
                        "INSERT OR IGNORE INTO candidate_skills (candidate_id, skill_id) VALUES (?, ?)",
                        (candidate_id, skill_row["id"]),
                    )

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
                manual_score,
                category_val or manual.get("category") or ranking_obj.get("category"),
                manual.get("rank") or ranking_obj.get("rank"),
                json.dumps(
                    manual.get("feature_contributions")
                    or ranking_obj.get("feature_contributions")
                    or {},
                    ensure_ascii=False,
                ),
                manual.get("gate_penalty") if category_val != "REJECT" else (manual.get("gate_penalty") or -30.0),
                manual.get("ai_adjustment"),
                json.dumps(agent, ensure_ascii=False),
                json.dumps(manual, ensure_ascii=False),
                now,
                now,
            ))

        if pipeline_dir:
            schema_path = Path(pipeline_dir) / "data" / "ranking_feature_schema.json"
            if schema_path.exists():
                try:
                    feature_schema = json.loads(schema_path.read_text(encoding="utf-8"))
                    capabilities = feature_schema.get("capabilities") if isinstance(feature_schema, dict) else None
                    if isinstance(capabilities, list):
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
        "created_candidates": created_count,
        "updated_candidates": updated_count,
        "linked_to_campaign": linked_count,
    }


@router.get("/api/campaigns/{campaign_id}/export/excel")
def export_campaign_excel(
    campaign_id: int,
    version_number: Optional[int] = Query(default=None),
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

    if version_number is not None:
        version_row = conn.execute("""
            SELECT pipeline_dir
            FROM pipeline_config_versions
            WHERE campaign_id = ? AND version_number = ?
        """, (campaign_id, version_number)).fetchone()
        pipeline_dir = Path(version_row["pipeline_dir"]) if version_row else None
    else:
        config_row = conn.execute("""
            SELECT pipeline_dir
            FROM pipeline_campaign_configs
            WHERE campaign_id = ?
        """, (campaign_id,)).fetchone()
        pipeline_dir = Path(config_row["pipeline_dir"]) if config_row else None

    conn.close()

    if not pipeline_dir:
        raise HTTPException(status_code=404, detail="Pipeline config not found for this campaign")

    output_dir = pipeline_dir / "output"
    xlsx_files = sorted(
        output_dir.glob("shortlist_*.xlsx"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if not xlsx_files:
        raise HTTPException(status_code=404, detail="No Excel export found. Run the pipeline first.")

    latest = xlsx_files[0]
    if not latest.resolve().is_relative_to(output_dir.resolve()):
        raise HTTPException(status_code=403, detail="Access denied")
    suffix = f"_v{version_number}" if version_number is not None else ""
    download_name = f"{campaign['campaign_code']}{suffix}_candidates.xlsx"

    return FileResponse(
        path=latest,
        filename=download_name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get("/api/campaigns/{campaign_id}/pipeline/scoring-explainer")
def get_scoring_explainer(
    campaign_id: int,
    current_user=Depends(get_current_user),
):
    conn = get_connection()
    try:
        pipeline_dir = _resolve_pipeline_dir(conn, campaign_id, current_user)
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


@router.get("/api/campaigns/{campaign_id}/pipeline/usage-summary")
def get_usage_summary_endpoint(
    campaign_id: int,
    current_user=Depends(get_current_user),
):
    conn = get_connection()
    try:
        pipeline_dir = _resolve_pipeline_dir(conn, campaign_id, current_user)
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


@router.get("/api/campaigns/{campaign_id}/pipeline/search-results-status")
def get_search_results_status(
    campaign_id: int,
    current_user=Depends(get_current_user),
):
    conn = get_connection()
    try:
        files = _resolve_search_results_files(conn, campaign_id, current_user)
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


@router.get("/api/campaigns/{campaign_id}/pipeline/export-search-csv")
def export_search_csv(
    campaign_id: int,
    current_user=Depends(get_current_user),
):
    conn = get_connection()
    try:
        files = _resolve_search_results_files(conn, campaign_id, current_user)
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


@router.get("/api/campaigns/{campaign_id}/pipeline/ranked-results-status")
def get_ranked_results_status(
    campaign_id: int,
    current_user=Depends(get_current_user),
):
    conn = get_connection()
    try:
        artifact_file = _resolve_ranked_results_artifact(
            conn,
            campaign_id,
            current_user,
        )
    finally:
        conn.close()

    return {
        "exists": artifact_file.exists(),
        "artifact_path": str(artifact_file),
    }


@router.get("/api/campaigns/{campaign_id}/pipeline/export-ranked-csv")
def export_ranked_csv(
    campaign_id: int,
    current_user=Depends(get_current_user),
):
    conn = get_connection()
    try:
        artifact_file = _resolve_ranked_results_artifact(
            conn,
            campaign_id,
            current_user,
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
