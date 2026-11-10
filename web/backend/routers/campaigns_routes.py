import json
import sqlite3
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from auth_utils import utc_now
from core.auth import _get_owned_campaign, get_current_user
from core.config import ALLOWED_COMMUNITY_PLATFORMS, DEFAULT_ACTIVITY_DAYS
from core.database import get_connection
from services.campaign_service import (
    _parse_platforms_json,
    _parse_template_locations,
    _remove_pipeline_campaign_dir,
    _save_uploaded_sample_cv,
    _sync_pipeline_config_for_campaign,
    _validate_activity_days,
)

router = APIRouter(tags=["campaigns"])


@router.get("/api/campaigns")
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


@router.get("/api/campaigns/active")
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


@router.get("/api/campaigns/past")
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


@router.post("/api/campaigns")
def create_campaign(
    campaign_name: str = Form(...),
    location: str = Form(...),
    position_name: str = Form(...),
    experience: str = Form(...),
    desired_skills: str = Form(""),
    target_profiles: int = Form(25),
    sample_cv: Optional[UploadFile] = File(None),
    current_user=Depends(get_current_user),
):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    saved_filename = _save_uploaded_sample_cv(sample_cv)

    conn = get_connection()
    cur = conn.cursor()

    def _next_campaign_code():
        rows = conn.execute("""
            SELECT campaign_code FROM campaigns WHERE campaign_code LIKE 'CMP-%'
        """).fetchall()
        max_n = 0
        for row in rows:
            suffix = row["campaign_code"].rsplit("-", 1)[-1]
            if suffix.isdigit():
                max_n = max(max_n, int(suffix))
        return f"CMP-{max_n + 1:03d}"

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
                now,
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
        "campaign_code": campaign_code,
    }


@router.get("/api/campaigns/{campaign_id}")
def get_campaign(
    campaign_id: int,
    current_user=Depends(get_current_user),
):
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


@router.put("/api/campaigns/{campaign_id}")
def update_campaign(
    campaign_id: int,
    campaign_name: str = Form(...),
    location: str = Form(...),
    position_name: str = Form(...),
    experience: str = Form(...),
    desired_skills: str = Form(""),
    target_profiles: int = Form(25),
    status: str = Form("Active"),
    sample_cv: Optional[UploadFile] = File(None),
    current_user=Depends(get_current_user),
):
    conn = get_connection()
    cur = conn.cursor()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if not _get_owned_campaign(conn, campaign_id, current_user):
        conn.close()
        raise HTTPException(status_code=404, detail="Campaign not found")

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
        (campaign_id,),
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
        "message": "Campaign updated successfully",
    }


@router.delete("/api/campaigns/{campaign_id}")
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


@router.post("/api/campaign-templates")
def create_campaign_template(
    template_name: str = Form(...),
    pipeline_description: str = Form(""),
    locations_json: str = Form(...),
    job_description: str = Form(...),
    filter_criteria: str = Form(...),
    platforms_json: Optional[str] = Form(default=None),
    activity_days: Optional[int] = Form(default=DEFAULT_ACTIVITY_DAYS),
    source_campaign_id: Optional[int] = Form(None),
    current_user=Depends(get_current_user),
):
    if not template_name.strip():
        raise HTTPException(status_code=400, detail="Config name is required")

    cleaned_locations = _parse_template_locations(locations_json)
    cleaned_platforms = _parse_platforms_json(platforms_json)
    validated_activity_days = _validate_activity_days(activity_days)

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
            platforms_json,
            activity_days,
            source_campaign_id,
            created_by_user_id,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        template_name.strip(),
        pipeline_description.strip(),
        json.dumps(cleaned_locations),
        job_description,
        filter_criteria,
        json.dumps(cleaned_platforms),
        validated_activity_days,
        source_campaign_id,
        current_user["id"],
        now,
        now,
    ))
    template_id = cur.lastrowid

    conn.commit()
    conn.close()

    return {"success": True, "template_id": template_id}


@router.get("/api/campaign-templates")
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
        raw_platforms_json = item.pop("platforms_json", None)
        try:
            parsed_platforms = json.loads(raw_platforms_json or "[]")
            item["platforms"] = [
                p for p in parsed_platforms if p in ALLOWED_COMMUNITY_PLATFORMS
            ] if isinstance(parsed_platforms, list) else []
        except json.JSONDecodeError:
            item["platforms"] = []
        item["activity_days"] = int(item.get("activity_days") or DEFAULT_ACTIVITY_DAYS)
        results.append(item)

    return results
