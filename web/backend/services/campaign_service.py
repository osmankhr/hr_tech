import os
import json
import re
import shutil
import logging
import subprocess
import yaml
from pathlib import Path
from typing import Optional
from datetime import datetime, timezone
from fastapi import HTTPException, UploadFile

from auth_utils import utc_now
from core.config import (
    UPLOAD_DIR,
    CANDIDATE_POOL_CAMPAIGNS_DIR,
    CANDIDATE_POOL_ENV_PATH,
    ALLOWED_COMMUNITY_PLATFORMS,
    DEFAULT_ACTIVITY_DAYS,
)
from core.database import get_connection
from pipeline_progress import clear_pipeline_progress
from services.settings_service import _read_dotenv_dict

logger = logging.getLogger(__name__)


def _slugify(value: str):
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "campaign"


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


_ING_EMPLOYER_RE = re.compile(
    r"\b(ing\s+bank|ing\s+hubs|ing\s+t[uü]rkiye|ing\s+turkey|ing\s+groep|ing\s+direct)\b"
    r"|(?<![a-z0-9])@ing(?![a-z0-9])",
    re.IGNORECASE,
)


def is_ing_affiliated(text: Optional[str]) -> bool:
    """Return True if candidate bio/company indicates current ING employment."""
    if not text or not isinstance(text, str):
        return False
    return bool(_ING_EMPLOYER_RE.search(text))


_MANDATORY_CRITERIA_END_MARKER = "<!-- END MANDATORY CRITERIA -->"


def _build_mandatory_criteria_clause(
    locations,
    pipeline_name: str = "",
    job_description: str = "",
) -> str:
    lines = []

    # 1. Location clause if locations exist
    loc_clause = _build_location_filter_clause(locations)
    if loc_clause:
        lines.append(loc_clause)

    # 2. Standing Company Exclusion (ING)
    lines.extend([
        "## Company Exclusion Rules (hard filter)",
        "",
        "Standing hard rule: This recruitment search is strictly for candidates outside ING. Candidates currently employed at ING, ING Bank, ING Hubs, ING Hubs Türkiye/Turkey, ING Groep, or ING Direct MUST be REJECTED.",
        "",
    ])

    # 3. Seniority & Experience hard filter (detect if role is Senior / 5+ years)
    combined_text = f"{pipeline_name} {job_description}".lower()
    is_senior = any(term in combined_text for term in ("senior", "lead", "principal", "staff", "5+"))
    if is_senior:
        lines.extend([
            "## Seniority & Experience Requirement (hard filter)",
            "",
            "For this senior role, the candidate must have substantial professional industry experience (at least 3+ years hands-on, targeting 5+ years). Candidates who are currently students, interns, trainees, or in entry-level bootcamps, or who have under 3 years of total experience, MUST be REJECTED. Do not credit trainee/intern tenures as senior engineering experience.",
            "",
        ])

    # 4. Technical Community Platforms Rule (GitHub, Hugging Face, Kaggle)
    lines.extend([
        "## Technical Community Platforms Rule (GitHub, Hugging Face, Kaggle)",
        "",
        "The recruitment team explicitly searches GitHub, Hugging Face, and Kaggle to discover active technical builders, open-source model authors, and competitors. Candidates from these platforms typically present code repositories, model weights, datasets, or competition notebooks rather than formal corporate CVs.",
        "- If a candidate is from GitHub, Hugging Face, or Kaggle and demonstrates substantive hands-on ML/Data Science technical work (e.g. models, datasets, active repositories, competition solutions) and has a connection to Turkey (Turkish name, Turkish NLP/models/datasets, or Turkey bio) with no contradictory foreign location, you MUST evaluate them as ACCEPT.",
        "- Do NOT reject them or leave them pending solely because their platform page lacks corporate employer history, job titles, or explicit years of experience. The recruitment team will manually evaluate their background and reach out to them.",
        "- Only REJECT a community candidate if they are currently employed at ING, or are clearly based in a foreign country (e.g. USA, Germany, Netherlands), or are an active student/intern with no substantive technical work.",
        "",
    ])

    # 5. Evidence Verification & Social Feed Stripping
    lines.extend([
        "## Evidence Verification Rule",
        "",
        "Evaluate the candidate strictly on their own verified accomplishments, repositories, and direct employment history. Disregard social feed activity such as posts, awards, or articles that the candidate merely liked, commented on, or reposted (e.g. '[... liked this]').",
        "",
        _MANDATORY_CRITERIA_END_MARKER,
        "",
    ])

    return "\n".join(lines)


def _parse_platforms_json(platforms_json: Optional[str]) -> list[str]:
    """Validate and normalize a JSON-encoded list of community platform identifiers."""
    if platforms_json is None or not str(platforms_json).strip():
        return []

    try:
        parsed = json.loads(platforms_json)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="platforms_json must be valid JSON")

    if not isinstance(parsed, list):
        raise HTTPException(status_code=400, detail="platforms_json must be a JSON array")

    cleaned: list[str] = []
    for item in parsed:
        normalized = str(item or "").strip().lower()
        if not normalized:
            continue
        if normalized not in ALLOWED_COMMUNITY_PLATFORMS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported platform '{normalized}'. Allowed: {', '.join(ALLOWED_COMMUNITY_PLATFORMS)}",
            )
        if normalized not in cleaned:
            cleaned.append(normalized)
    return cleaned


def _validate_activity_days(activity_days: Optional[int]) -> int:
    """Validate the recency window (in days) used for active candidate verification."""
    if activity_days is None:
        return DEFAULT_ACTIVITY_DAYS
    try:
        val = int(activity_days)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="activity_days must be an integer")
    if val < 1 or val > 3650:
        raise HTTPException(status_code=400, detail="activity_days must be between 1 and 3650")
    return val


def _build_campaign_yaml(
    name: str,
    description: str,
    locations,
    max_candidates: Optional[int] = None,
    platforms: Optional[list[str]] = None,
    activity_days: int = DEFAULT_ACTIVITY_DAYS,
):
    """Build the campaign.yaml file content for a pipeline campaign."""
    normalized_platforms = [
        p for p in (platforms or []) if p in ALLOWED_COMMUNITY_PLATFORMS
    ]
    validated_days = _validate_activity_days(activity_days)

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
        f"  platforms: {json.dumps(normalized_platforms)}",
        f"  activity_days: {validated_days}",
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
    ])

    if max_candidates is not None and int(max_candidates) > 0:
        lines.append(f"  max_candidates: {int(max_candidates)}")

    lines.extend([
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
    ])

    if max_candidates is not None and int(max_candidates) > 0:
        lines.append(f"  max_candidates: {int(max_candidates)}")

    lines.extend([
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


_LOCATION_CLAUSE_MARKER = "## Location Requirement (hard filter)"
_LOCATION_CLAUSE_END_MARKER = "pending for manual review rather than accepting."


def _strip_location_clause(text: str) -> str:
    """Undo _build_mandatory_criteria_clause() / _build_location_filter_clause()."""
    if _MANDATORY_CRITERIA_END_MARKER in text:
        end_idx = text.find(_MANDATORY_CRITERIA_END_MARKER)
        return text[end_idx + len(_MANDATORY_CRITERIA_END_MARKER):].lstrip("\n")
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
    platforms: list[str] = []
    activity_days: int = DEFAULT_ACTIVITY_DAYS
    if campaign_yaml_path.exists():
        try:
            parsed = yaml.safe_load(campaign_yaml_path.read_text(encoding="utf-8")) or {}
            name = parsed.get("name") or ""
            description = parsed.get("description") or ""
            locations = parsed.get("locations") or []
            search_cfg = parsed.get("search") or {}
            raw_platforms = search_cfg.get("platforms")
            if isinstance(raw_platforms, list):
                platforms = [
                    str(p).strip().lower()
                    for p in raw_platforms
                    if str(p).strip().lower() in ALLOWED_COMMUNITY_PLATFORMS
                ]
            raw_days = search_cfg.get("activity_days")
            if raw_days is not None:
                try:
                    activity_days = max(1, min(3650, int(raw_days)))
                except (TypeError, ValueError):
                    activity_days = DEFAULT_ACTIVITY_DAYS
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
        "platforms": platforms,
        "activity_days": activity_days,
        "job_description": job_description,
        "filter_criteria": filter_criteria,
    }


def _pipeline_results_summary(pipeline_dir: Path) -> dict:
    """Whether a pipeline version has been run, and how far."""
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
    rec = str(recommendation or "").upper()
    if rec in ("ACCEPT", "SHORTLIST", "APPROVE"):
        return "Shortlisted"
    if rec in ("REJECT", "DISQUALIFY"):
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
    run_row = None
    try:
        run_row = conn.execute(
            "SELECT campaign_dir FROM pipeline_runs WHERE id = ?",
            (run_id,),
        ).fetchone()

        child_env = os.environ.copy()
        child_env.update(_read_dotenv_dict(CANDIDATE_POOL_ENV_PATH))
        child_env["PYTHONUTF8"] = "1"
        child_env["PYTHONIOENCODING"] = "utf-8"

        result = subprocess.run(
            command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=child_env,
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
        if run_row and run_row["campaign_dir"]:
            clear_pipeline_progress(
                run_row["campaign_dir"],
                campaigns_root=CANDIDATE_POOL_CAMPAIGNS_DIR,
            )
        conn.commit()
        conn.close()


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


def _save_uploaded_sample_cv(sample_cv: Optional[UploadFile]) -> Optional[str]:
    """Save an uploaded sample CV to UPLOAD_DIR and return its stored filename, or None."""
    if sample_cv is None or not sample_cv.filename:
        return None

    raw_name = Path(sample_cv.filename).name
    # Strip any directory traversal or path characters
    safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", raw_name)
    if not safe_name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    saved_filename = f"{timestamp}_{safe_name}"
    saved_path = (UPLOAD_DIR / saved_filename).resolve()
    # Security: Ensure saved_path stays strictly inside UPLOAD_DIR
    if not saved_path.is_relative_to(UPLOAD_DIR.resolve()):
        raise HTTPException(status_code=400, detail="Invalid filename")

    MAX_CV_BYTES = 10 * 1024 * 1024  # 10 MB upload cap to prevent DoS
    size = 0
    with open(saved_path, "wb") as buffer:
        while True:
            chunk = sample_cv.file.read(8192)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_CV_BYTES:
                buffer.close()
                saved_path.unlink(missing_ok=True)
                raise HTTPException(status_code=400, detail="Uploaded file exceeds 10 MB limit")
            buffer.write(chunk)

    return saved_filename


def _sync_pipeline_config_for_campaign(conn, campaign_id: int, target_profiles, sample_cv_filename):
    """Propagate a campaign's target_profiles / sample CV into an already-set-up pipeline."""
    config_row = conn.execute(
        "SELECT pipeline_dir FROM pipeline_campaign_configs WHERE campaign_id = ?",
        (campaign_id,),
    ).fetchone()
    if not config_row or not config_row["pipeline_dir"]:
        return

    pipeline_dir = Path(config_row["pipeline_dir"])
    campaign_yaml_path = pipeline_dir / "campaign.yaml"

    if campaign_yaml_path.exists():
        try:
            config = yaml.safe_load(campaign_yaml_path.read_text(encoding="utf-8")) or {}
            if target_profiles and int(target_profiles) > 0:
                config.setdefault("filter", {})["max_candidates"] = int(target_profiles)
                config.setdefault("ranking", {})["max_candidates"] = int(target_profiles)
            else:
                if "filter" in config and "max_candidates" in config["filter"]:
                    del config["filter"]["max_candidates"]
                if "ranking" in config and "max_candidates" in config["ranking"]:
                    del config["ranking"]["max_candidates"]
            campaign_yaml_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        except Exception:
            logger.exception("Failed to sync target_profiles into %s", campaign_yaml_path)

    if sample_cv_filename:
        source_cv_path = UPLOAD_DIR / sample_cv_filename
        if source_cv_path.exists():
            seed_cv_dir = pipeline_dir / "input" / "seed_cvs"
            seed_cv_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_cv_path, seed_cv_dir / source_cv_path.name)


def _load_best_available_pipeline_candidates(pipeline_dir: Path) -> tuple[list[dict], Optional[Path]]:
    """Load the most advanced candidate artifact available in a pipeline directory.

    Priority order:
    1. data/ranked_results.json (ranked & AI-reviewed)
    2. data/filtered_results.json (AI-reviewed)
    3. data/*/raw_results.json (discovered from Exa + GitHub + Hugging Face + Kaggle)
    """
    data_dir = pipeline_dir / "data"
    ranked_file = data_dir / "ranked_results.json"
    if ranked_file.exists():
        try:
            rows = json.loads(ranked_file.read_text(encoding="utf-8"))
            if isinstance(rows, list) and rows:
                return rows, ranked_file
        except Exception:
            logger.exception("Failed to read ranked_results.json at %s", ranked_file)

    filtered_file = data_dir / "filtered_results.json"
    if filtered_file.exists():
        try:
            rows = json.loads(filtered_file.read_text(encoding="utf-8"))
            if isinstance(rows, list) and rows:
                return rows, filtered_file
        except Exception:
            logger.exception("Failed to read filtered_results.json at %s", filtered_file)

    merged_raw: list[dict] = []
    seen_urls: set[str] = set()
    first_raw_file: Optional[Path] = None
    if data_dir.exists():
        for raw_file in sorted(data_dir.glob("*/raw_results.json")):
            if first_raw_file is None:
                first_raw_file = raw_file
            loc_name = raw_file.parent.name
            try:
                rows = json.loads(raw_file.read_text(encoding="utf-8"))
                if isinstance(rows, list):
                    for item in rows:
                        if not isinstance(item, dict):
                            continue
                        url = str(item.get("url") or "").strip()
                        if url and url in seen_urls:
                            continue
                        if url:
                            seen_urls.add(url)
                        enriched = dict(item)
                        if not enriched.get("location"):
                            enriched["location"] = loc_name
                        merged_raw.append(enriched)
            except Exception:
                logger.exception("Failed to read raw_results.json at %s", raw_file)

    return merged_raw, first_raw_file


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



