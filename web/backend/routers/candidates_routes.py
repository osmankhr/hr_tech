import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Query

from core.auth import _get_owned_campaign, get_current_user
from core.database import get_connection
from services.campaign_service import (
    _candidate_status_from_review,
    _extract_years_experience,
    _load_best_available_pipeline_candidates,
)

router = APIRouter(tags=["candidates"])


@router.get("/api/campaigns/{campaign_id}/rankings")
def list_campaign_rankings(campaign_id: int, current_user=Depends(get_current_user)):
    conn = get_connection()

    if not _get_owned_campaign(conn, campaign_id, current_user):
        conn.close()
        raise HTTPException(status_code=404, detail="Campaign not found")

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


@router.get("/api/campaigns/{campaign_id}/candidates")
def list_campaign_candidates(
    campaign_id: int,
    page: int = 1,
    page_size: int = 10,
    version_number: Optional[int] = Query(default=None),
    sort_by: str = Query(default="score_desc"),
    current_user=Depends(get_current_user),
):
    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 10
    if page_size > 500:
        page_size = 500

    allowed_sort_clauses = {
        "score_desc": "COALESCE(cr.manual_score, cand.score, 0) DESC, COALESCE(cr.rank, 999999) ASC, cand.full_name COLLATE NOCASE ASC",
        "score_asc": "COALESCE(cr.manual_score, cand.score, 0) ASC, cand.full_name COLLATE NOCASE ASC",
        "name_asc": "cand.full_name COLLATE NOCASE ASC, COALESCE(cr.manual_score, cand.score, 0) DESC",
        "name_desc": "cand.full_name COLLATE NOCASE DESC, COALESCE(cr.manual_score, cand.score, 0) DESC",
        "exp_desc": "COALESCE(cand.years_experience, -1) DESC, COALESCE(cr.manual_score, cand.score, 0) DESC",
        "source_asc": "cand.source COLLATE NOCASE ASC, COALESCE(cr.manual_score, cand.score, 0) DESC",
        "recent": "cand.last_updated DESC, cand.id DESC",
    }
    order_by_sql = allowed_sort_clauses.get(sort_by, allowed_sort_clauses["score_desc"])

    offset = (page - 1) * page_size

    conn = get_connection()

    if not _get_owned_campaign(conn, campaign_id, current_user):
        conn.close()
        raise HTTPException(status_code=404, detail="Campaign not found")

    if version_number is not None:
        version_row = conn.execute(
            """
            SELECT id, version_number, pipeline_dir
            FROM pipeline_config_versions
            WHERE campaign_id = ? AND version_number = ?
            """,
            (campaign_id, version_number),
        ).fetchone()

        if not version_row:
            conn.close()
            raise HTTPException(status_code=404, detail="Config version not found")

        pipeline_dir = Path(version_row["pipeline_dir"])
        candidates_raw, _ = _load_best_available_pipeline_candidates(pipeline_dir)

        total_count = len(candidates_raw)
        paged_raw = candidates_raw[offset : offset + page_size]

        candidates = []
        for idx, item in enumerate(paged_raw):
            if not isinstance(item, dict):
                continue
            profile_url = str(item.get("url") or "").strip()
            email = str(item.get("email") or "").strip().lower()
            full_name = str(item.get("name") or item.get("title") or "").strip()
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
            try:
                raw_float = float(score_value)
                if manual_score is None and 0.0 < raw_float <= 1.0:
                    raw_float = raw_float * 100.0
                score_int = int(round(raw_float))
            except (TypeError, ValueError):
                score_int = 0
            score_int = max(0, min(100, score_int))

            years_experience = _extract_years_experience(str(item.get("text") or ""))

            db_match = None
            if profile_url:
                db_match = conn.execute(
                    "SELECT id, candidate_code, notes, last_updated FROM candidates WHERE profile_url = ?",
                    (profile_url,),
                ).fetchone()
            if not db_match and email:
                db_match = conn.execute(
                    "SELECT id, candidate_code, notes, last_updated FROM candidates WHERE email = ?",
                    (email,),
                ).fetchone()

            cand_id = db_match["id"] if db_match else f"v{version_number}-{offset + idx + 1}"
            cand_code = db_match["candidate_code"] if db_match else f"CAN-v{version_number}-{offset + idx + 1:03d}"
            cand_notes = db_match["notes"] if db_match else ""
            cand_last_updated = db_match["last_updated"] if db_match else ""

            skills_raw = item.get("skills") or []
            if isinstance(skills_raw, list):
                skills_str = ", ".join(str(s) for s in skills_raw if s)
            else:
                skills_str = str(skills_raw)

            ranking_obj = item.get("ranking") or {}
            ranking_category = ranking_obj.get("category") or ("ACCEPT" if recommendation == "ACCEPT" else "REVIEW")
            ranking_rank = ranking_obj.get("rank") or (offset + idx + 1)
            feature_contribs = ranking_obj.get("feature_contributions") or {}

            candidates.append({
                "id": cand_id,
                "candidate_code": cand_code,
                "full_name": full_name,
                "email": email,
                "current_title": job_title,
                "location": location,
                "source": source,
                "profile_url": profile_url,
                "score": score_int,
                "status": candidate_status,
                "years_experience": years_experience,
                "english_confidence": english_confidence,
                "english_confidence_reason": english_confidence_reason,
                "last_updated": cand_last_updated,
                "notes": cand_notes,
                "skills": skills_str,
                "ranking": {
                    "manual_score": manual_score,
                    "category": ranking_category,
                    "rank": ranking_rank,
                    "feature_contributions": feature_contribs,
                    "agent": agent,
                    "manual": manual,
                },
            })

        conn.close()
        total_pages = (total_count + page_size - 1) // page_size if total_count else 0
        return {
            "items": candidates,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_items": total_count,
                "total_pages": total_pages,
            },
            "version_number": version_number,
        }

    total_count = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM campaign_candidates
        WHERE campaign_id = ?
        """,
        (campaign_id,),
    ).fetchone()["count"]

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
        FROM campaign_candidates cc
        JOIN candidates cand ON cand.id = cc.candidate_id
        LEFT JOIN candidate_skills cs ON cs.candidate_id = cand.id
        LEFT JOIN skills s ON s.id = cs.skill_id
        LEFT JOIN candidate_rankings cr
            ON cr.campaign_id = cc.campaign_id
            AND cr.candidate_id = cc.candidate_id
        WHERE cc.campaign_id = ?
        GROUP BY cand.id
        ORDER BY {order_by_sql}
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


@router.get("/api/candidates")
def list_candidates(current_user=Depends(get_current_user)):
    conn = get_connection()
    rows = conn.execute("""
        SELECT *
        FROM candidate_profile_summary
        ORDER BY score DESC
    """).fetchall()
    conn.close()

    return [dict(row) for row in rows]


@router.get("/api/skills")
def list_skills(current_user=Depends(get_current_user)):
    conn = get_connection()
    rows = conn.execute("""
        SELECT name
        FROM skills
        ORDER BY name
    """).fetchall()
    conn.close()

    return [row["name"] for row in rows]


@router.post("/api/candidates/refresh")
def refresh_candidates(current_user=Depends(get_current_user)):
    conn = get_connection()

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

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


@router.get("/api/candidates/{candidate_id}")
def get_candidate(
    candidate_id: int,
    current_user=Depends(get_current_user),
):
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


@router.put("/api/candidates/{candidate_id}")
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
    current_user=Depends(get_current_user),
):
    conn = get_connection()
    cur = conn.cursor()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    existing = conn.execute(
        "SELECT id FROM candidates WHERE id = ?",
        (candidate_id,),
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
        candidate_id,
    ))

    cur.execute(
        "DELETE FROM candidate_skills WHERE candidate_id = ?",
        (candidate_id,),
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
        "message": "Candidate updated successfully",
    }


@router.get("/api/candidates/{candidate_id}/activities")
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


@router.get("/api/candidates/{candidate_id}/comments")
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


@router.post("/api/candidates/{candidate_id}/comments")
def add_candidate_comment(
    candidate_id: int, 
    content: str = Form(...), 
    parent_id: Optional[int] = Form(None), 
    current_user=Depends(get_current_user),
):
    if not content:
        raise HTTPException(status_code=400, detail="Content is required")

    conn = get_connection()
    cur = conn.cursor()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    
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
