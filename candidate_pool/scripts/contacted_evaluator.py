"""Evaluator and recorder for contacted candidates discovered during search.

Operates independently of campaign results:
When candidates from the recruiter's contacted Excel/CSV appear in search results,
they are excluded from the active campaign candidate pool. This module filters and
grades those candidates against the campaign's criteria and scoring policies,
storing the results in an independent cross-campaign analysis log and generating
side-by-side comparison reports for HR review analysis.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


def resolve_contacted_evaluations_path(
    campaign_dir: Path | None = None,
    config: dict[str, Any] | None = None,
) -> Path:
    """Resolve the persistent JSONL path for contacted candidates evaluations."""
    config = config or {}

    # 1. Configured path
    configured = (
        config.get("analysis", {}).get("contacted_evaluations_path")
        or config.get("dedup", {}).get("contacted_evaluations_path")
    )
    if configured:
        p = Path(configured)
        if not p.is_absolute() and campaign_dir:
            p = (campaign_dir / p).resolve()
        return p

    # 2. Environment variable
    env_path = os.environ.get("CONTACTED_EVALUATIONS_PATH")
    if env_path:
        return Path(env_path).resolve()

    # 3. Default independent directory: candidate_pool/analysis/contacted_evaluations.jsonl
    base_dir = Path(__file__).resolve().parent.parent / "analysis"
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / "contacted_evaluations.jsonl"


def resolve_comparison_report_path(
    campaign_dir: Path | None = None,
    config: dict[str, Any] | None = None,
    format: str = "xlsx",
) -> Path:
    """Resolve the output path for HR vs AI comparison reports."""
    config = config or {}
    configured = config.get("analysis", {}).get("contacted_comparison_report_path")
    if configured:
        p = Path(configured)
        if not p.is_absolute() and campaign_dir:
            p = (campaign_dir / p).resolve()
        if format and p.suffix.lower() != f".{format}":
            p = p.with_suffix(f".{format}")
        return p

    base_dir = Path(__file__).resolve().parent.parent / "analysis"
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / f"contacted_hr_vs_ai_comparison.{format}"


def _find_field(record: dict[str, Any], aliases: list[str]) -> str:
    """Find a value in a dictionary matching any alias (case-insensitive)."""
    norm_map = {str(k).strip().lower(): v for k, v in record.items()}
    for alias in aliases:
        if alias in norm_map and norm_map[alias]:
            return str(norm_map[alias]).strip()
    return ""


def determine_alignment(hr_status: str, hr_notes: str, ai_rec: str) -> str:
    """Compute high-level alignment indicator between HR notes and AI recommendation."""
    combined_hr = f"{hr_status} {hr_notes}".lower()
    ai_rec_upper = str(ai_rec or "").upper()

    is_hr_negative = bool(
        re.search(
            r"\b(reject|rejected|red|elendi|olumsuz|passed|not suitable|unsuitable|dropped|failed|declined)\b",
            combined_hr,
        )
    )
    is_hr_positive = bool(
        re.search(
            r"\b(interview|interviewed|olumlu|offer|offered|hired|accepted|shortlist|shortlisted|contacted|reach out|gorusuldu|görüşüldü)\b",
            combined_hr,
        )
    )

    if not combined_hr.strip():
        return "No HR Feedback Recorded"

    if ai_rec_upper == "REJECT" and is_hr_negative:
        return "Aligned (Both Rejected)"
    if ai_rec_upper == "ACCEPT" and is_hr_positive and not is_hr_negative:
        return "Aligned (Both Accepted/Interested)"
    if ai_rec_upper == "ACCEPT" and is_hr_negative:
        return "Discrepancy (HR Rejected vs AI Accepted)"
    if ai_rec_upper == "REJECT" and is_hr_positive:
        return "Discrepancy (HR Positive vs AI Rejected)"
    if ai_rec_upper == "PENDING":
        return "AI Marked Pending"

    return "Reviewed"


class ContactedCandidateEvaluator:
    """Evaluates contacted candidates and logs comparisons independently of campaign results."""

    def __init__(self, campaign_dir: Path, config: dict[str, Any]) -> None:
        self.campaign_dir = Path(campaign_dir).resolve()
        self.config = config
        self.evaluations_path = resolve_contacted_evaluations_path(self.campaign_dir, self.config)

    def load_contacted_hits(self) -> list[dict[str, Any]]:
        """Collect all contacted search hits saved across location subdirectories."""
        data_dir = self.campaign_dir / "data"
        if not data_dir.exists():
            return []

        hits: list[dict[str, Any]] = []
        seen_urls: set[str] = set()

        for loc_dir in sorted(data_dir.iterdir()):
            if not loc_dir.is_dir():
                continue
            hits_path = loc_dir / "contacted_search_hits.json"
            if not hits_path.exists():
                continue

            try:
                with open(hits_path, encoding="utf-8") as f:
                    batch = json.load(f)
                for item in batch:
                    url = item.get("url") or ""
                    if url and url in seen_urls:
                        continue
                    if url:
                        seen_urls.add(url)
                    hits.append(item)
            except Exception as e:
                logger.warning("Could not read contacted hits from %s: %s", hits_path, e)

        return hits

    def evaluate_candidates(
        self,
        candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Filter and grade contacted candidates against campaign criteria and ranking."""
        if not candidates:
            return []

        evaluated: list[dict[str, Any]] = []

        # 1. AI Filter Review
        from filter import CandidateFilter

        try:
            candidate_filter = CandidateFilter(self.campaign_dir, self.config)
            has_filter = True
        except Exception as e:
            logger.warning("Could not initialize CandidateFilter for contacted candidates: %s", e)
            has_filter = False
            candidate_filter = None

        # 2. Ranking / Grading setup if available
        ranking_enabled = self.config.get("ranking", {}).get("enabled", True)
        feature_schema_path = self.campaign_dir / "data" / "ranking_feature_schema.json"
        scoring_policy_path = self.campaign_dir / "data" / "ranking_scoring_policy.json"

        scorer_agent = None
        manual_grader = None
        feature_schema = None
        scoring_policy = None

        if ranking_enabled and feature_schema_path.exists() and scoring_policy_path.exists():
            try:
                with open(feature_schema_path, encoding="utf-8") as f:
                    feature_schema = json.load(f)
                with open(scoring_policy_path, encoding="utf-8") as f:
                    scoring_policy = json.load(f)

                from ranking.agents.candidate_scorer_agent import CandidateScorerAgent
                from ranking.manual_grader import ManualGrader
                from ranking.prompt_store import PromptStore

                rank_cfg = self.config.get("ranking", {})
                model = rank_cfg.get("model", self.config.get("filter", {}).get("model", "claude-sonnet-5"))
                prompt_store = PromptStore(self.campaign_dir, rank_cfg.get("prompts"))
                timeout = int(rank_cfg.get("timeout_seconds", 120))

                scorer_agent = CandidateScorerAgent(model=model, prompt_store=prompt_store, timeout=timeout)
                manual_grader = ManualGrader(
                    scoring_policy=scoring_policy,
                    ai_review_adjustments=rank_cfg.get("ai_review_adjustments"),
                )
            except Exception as e:
                logger.warning("Could not initialize ranking components for contacted candidates: %s", e)

        for cand in candidates:
            item = dict(cand)

            # Perform filter review
            if has_filter and candidate_filter is not None:
                try:
                    item = candidate_filter._review_candidate(item)
                except Exception as e:
                    logger.warning("Failed to filter contacted candidate %r: %s", item.get("title"), e)
                    item.setdefault("ai_review", {
                        "recommendation": "PENDING",
                        "reasoning": f"Review execution error: {e}",
                    })
            else:
                item.setdefault("ai_review", {
                    "recommendation": "UNREVIEWED",
                    "reasoning": "Filter criteria not initialized.",
                })

            # Perform ranking score
            if scorer_agent and manual_grader and feature_schema and scoring_policy:
                try:
                    text_chars = int(self.config.get("ranking", {}).get("candidate_text_chars", 5000))
                    agent_score = scorer_agent.score_candidate(
                        candidate=item,
                        feature_schema=feature_schema,
                        scoring_policy=scoring_policy,
                        text_chars=text_chars,
                    )
                    grade_res = manual_grader.grade(
                        candidate=item,
                        feature_assessments=agent_score.get("feature_assessments", []),
                        gate_flags=agent_score.get("gate_flags", []),
                    )
                    item["agent_score"] = agent_score
                    item["manual_score"] = grade_res
                    item["total_score"] = grade_res.get("manual_score")
                    item["grade"] = grade_res.get("category")
                    item["feature_assessments"] = agent_score.get("feature_assessments", [])
                except Exception as e:
                    logger.warning("Failed to score contacted candidate %r: %s", item.get("title"), e)

            evaluated.append(item)

        return evaluated

    def record_evaluations(self, evaluated_candidates: list[dict[str, Any]]) -> int:
        """Persist evaluated candidates into the independent cross-campaign store."""
        if not evaluated_candidates:
            return 0

        self.evaluations_path.parent.mkdir(parents=True, exist_ok=True)

        existing_records: list[dict[str, Any]] = []
        if self.evaluations_path.exists():
            try:
                with open(self.evaluations_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            existing_records.append(json.loads(line))
            except Exception as e:
                logger.warning("Could not read existing evaluations from %s: %s", self.evaluations_path, e)

        # Index existing by (url, campaign_name) to allow idempotent updates
        record_map: dict[str, dict[str, Any]] = {}
        for rec in existing_records:
            key = f"{rec.get('profile_url', '')}::{rec.get('campaign_name', '')}"
            record_map[key] = rec

        campaign_name = self.config.get("name", self.campaign_dir.name)
        now_iso = datetime.now(timezone.utc).isoformat()

        updated_count = 0
        for cand in evaluated_candidates:
            contacted_match = cand.get("contacted_match") or {}
            recruiter_row = contacted_match.get("recruiter_record") or {}

            # Determine best candidate name
            name = (
                _find_field(recruiter_row, ["candidate name", "candidate_name", "full name", "ad soyad", "name"])
                or cand.get("name")
                or contacted_match.get("matched_key")
                or cand.get("title", "")
            )

            hr_status = _find_field(recruiter_row, ["status", "durum", "aşama", "stage", "sonuç"])
            hr_notes = _find_field(
                recruiter_row,
                ["notes", "note", "not", "notlar", "review", "feedback", "yorum", "görüş", "değerlendirme", "reason"],
            )
            hr_recruiter = _find_field(recruiter_row, ["recruiter", "ik", "sorumlu", "ekleyen", "assigned"])

            ai_review = cand.get("ai_review") or {}
            ai_recommendation = ai_review.get("recommendation", "UNREVIEWED")
            ai_score = cand.get("total_score")
            ai_grade = cand.get("grade")

            record: dict[str, Any] = {
                "evaluated_at": now_iso,
                "campaign_name": campaign_name,
                "campaign_dir": str(self.campaign_dir),
                "candidate_name": name,
                "profile_url": cand.get("url") or "",
                "search_title": cand.get("title") or "",
                "location": cand.get("location") or "",
                "search_bucket": cand.get("search_bucket") or "",
                "match_type": contacted_match.get("match_type") or "",
                "matched_key": contacted_match.get("matched_key") or "",
                "hr_record": recruiter_row,
                "hr_status": hr_status,
                "hr_notes": hr_notes,
                "hr_recruiter": hr_recruiter,
                "ai_recommendation": ai_recommendation,
                "ai_confidence": ai_review.get("confidence"),
                "ai_score": ai_score,
                "ai_grade": ai_grade,
                "ai_key_strength": ai_review.get("key_strength"),
                "ai_main_concern": ai_review.get("main_concern"),
                "ai_reasoning": ai_review.get("reasoning"),
                "feature_assessments": cand.get("feature_assessments"),
                "alignment": determine_alignment(hr_status, hr_notes, ai_recommendation),
            }

            key = f"{record['profile_url']}::{record['campaign_name']}"
            record_map[key] = record
            updated_count += 1

        # Write back complete JSONL
        with open(self.evaluations_path, "w", encoding="utf-8") as f:
            for rec in record_map.values():
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        logger.info(
            "Saved %d contacted candidate evaluation(s) to %s (total in store: %d)",
            updated_count,
            self.evaluations_path,
            len(record_map),
        )

        # Also generate the Excel / CSV comparison report for HR
        self.export_comparison_reports(list(record_map.values()))
        return updated_count

    def export_comparison_reports(self, records: list[dict[str, Any]]) -> None:
        """Generate side-by-side Excel and CSV comparison tables for HR analysis."""
        if not records:
            return

        rows: list[dict[str, Any]] = []
        for r in records:
            rows.append({
                "Candidate Name": r.get("candidate_name") or "",
                "Profile URL": r.get("profile_url") or "",
                "Campaign": r.get("campaign_name") or "",
                "HR Status": r.get("hr_status") or "",
                "HR Notes / Feedback": r.get("hr_notes") or "",
                "HR Recruiter": r.get("hr_recruiter") or "",
                "AI Recommendation": r.get("ai_recommendation") or "",
                "AI Score": r.get("ai_score") if r.get("ai_score") is not None else "",
                "AI Grade": r.get("ai_grade") or "",
                "AI vs HR Alignment": r.get("alignment") or "",
                "AI Key Strength": r.get("ai_key_strength") or "",
                "AI Main Concern": r.get("ai_main_concern") or "",
                "AI Reasoning": r.get("ai_reasoning") or "",
                "Location": r.get("location") or "",
                "Evaluated Date": str(r.get("evaluated_at", ""))[:19].replace("T", " "),
            })

        df = pd.DataFrame(rows)

        # Sort with discrepancies first, then candidate name
        if "AI vs HR Alignment" in df.columns:
            df["_priority"] = df["AI vs HR Alignment"].apply(
                lambda val: 0 if "Discrepancy" in str(val) else 1
            )
            df = df.sort_values(by=["_priority", "Campaign", "Candidate Name"]).drop(columns=["_priority"])

        excel_path = resolve_comparison_report_path(self.campaign_dir, self.config, format="xlsx")
        csv_path = resolve_comparison_report_path(self.campaign_dir, self.config, format="csv")

        try:
            excel_path.parent.mkdir(parents=True, exist_ok=True)
            with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
                df.to_excel(writer, sheet_name="HR vs AI Comparison", index=False)
            logger.info("Exported HR comparison Excel workbook to %s", excel_path)
        except Exception as e:
            logger.warning("Could not export Excel comparison report (%s); falling back to CSV", e)

        try:
            df.to_csv(csv_path, index=False, encoding="utf-8-sig")
            logger.info("Exported HR comparison CSV to %s", csv_path)
        except Exception as e:
            logger.warning("Could not export CSV comparison report: %s", e)

    def run(self) -> int:
        """Complete workflow: load hits, evaluate, and record comparisons."""
        hits = self.load_contacted_hits()
        if not hits:
            logger.info("No contacted candidate search hits found for %s", self.campaign_dir.name)
            return 0

        logger.info(
            "Found %d contacted candidate search hit(s) for independent evaluation",
            len(hits),
        )
        evaluated = self.evaluate_candidates(hits)
        count = self.record_evaluations(evaluated)
        return count


if __name__ == "__main__":
    import argparse
    import yaml

    parser = argparse.ArgumentParser(description="Evaluate contacted candidates independently")
    parser.add_argument("campaign_dir", type=Path, help="Campaign directory path")
    args = parser.parse_args()

    c_dir = args.campaign_dir.resolve()
    c_config_path = c_dir / "campaign.yaml"
    c_config = {}
    if c_config_path.exists():
        with open(c_config_path, encoding="utf-8") as f:
            c_config = yaml.safe_load(f) or {}

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    evaluator = ContactedCandidateEvaluator(c_dir, c_config)
    total_evaluated = evaluator.run()
    print(f"Evaluated and logged {total_evaluated} contacted candidate(s).")

