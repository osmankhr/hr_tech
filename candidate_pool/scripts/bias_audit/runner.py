"""Execution engine for demographic bias audit across filter and ranking pipelines."""
from __future__ import annotations

import concurrent.futures
import copy
import logging
import statistics
import time
from typing import Any

from filter import CandidateFilter
from ranking.agents.candidate_scorer_agent import CandidateScorerAgent
from ranking.manual_grader import ManualGrader
from ranking.prompt_store import DEFAULT_PROMPTS, PromptStore

from .benchmark_role import (
    BENCHMARK_FILTER_CRITERIA,
    BENCHMARK_FEATURE_SCHEMA,
    BENCHMARK_SCORING_POLICY,
)
from .perturbations import DEMOGRAPHIC_VARIANTS, perturb_candidate
from .seed_profiles import SEED_PROFILES
from pathlib import Path

logger = logging.getLogger(__name__)


class StandalonePromptStore(PromptStore):
    """Prompt store that serves built-in default ranking prompts without requiring a campaign dir."""

    def __init__(self, overrides: dict[str, str] | None = None) -> None:
        super().__init__(campaign_dir=Path("."))
        self.overrides = overrides or {}

    def get(self, key: str) -> str:
        if key in self.overrides:
            return self.overrides[key]
        if key in DEFAULT_PROMPTS:
            return DEFAULT_PROMPTS[key]
        raise KeyError(f"Unknown prompt key: {key}")


class StandaloneCandidateFilter(CandidateFilter):
    """CandidateFilter that does not require an on-disk campaign folder."""

    def __init__(self, criteria: str, model: str = "claude-sonnet-5") -> None:
        self.criteria = criteria
        self.model = model
        self.max_candidates = None
        self.max_workers = 10
        self.config = {"filter": {"model": model}}
        self.campaign_dir = Path(".")


class BiasAuditRunner:
    """Runs counterfactual demographic perturbations through filter and ranking."""

    def __init__(
        self,
        *,
        model: str = "claude-sonnet-5",
        filter_criteria: str | None = None,
        feature_schema: dict[str, Any] | None = None,
        scoring_policy: dict[str, Any] | None = None,
        baseline_repeats: int = 3,
        variants_repeats: int = 1,
        max_workers: int = 5,
        timeout: int = 120,
    ) -> None:
        self.model = model
        self.filter_criteria = filter_criteria or BENCHMARK_FILTER_CRITERIA
        self.feature_schema = feature_schema or BENCHMARK_FEATURE_SCHEMA
        self.scoring_policy = scoring_policy or BENCHMARK_SCORING_POLICY
        self.baseline_repeats = max(1, baseline_repeats)
        self.variants_repeats = max(1, variants_repeats)
        self.max_workers = max(1, max_workers)
        self.timeout = timeout

        self.filter_engine = StandaloneCandidateFilter(criteria=self.filter_criteria, model=self.model)
        self.prompt_store = StandalonePromptStore()
        self.scorer_agent = CandidateScorerAgent(model=self.model, prompt_store=self.prompt_store, timeout=self.timeout)
        self.grader = ManualGrader(scoring_policy=self.scoring_policy)

    def evaluate_single_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        """Run one candidate through filter, then ranking, returning complete audit record."""
        # 1. Filter evaluation
        filtered = self.filter_engine._review_candidate(candidate)
        ai_review = filtered.get("ai_review") or {}
        recommendation = ai_review.get("recommendation", "UNKNOWN")
        confidence = ai_review.get("confidence", "UNKNOWN")
        english_confidence = filtered.get("english_confidence", "UNKNOWN")
        reasoning = ai_review.get("reasoning") or ai_review.get("main_concern") or ""

        # 2. Ranking evaluation
        score_res = self.scorer_agent.score_candidate(
            candidate=filtered,
            feature_schema=self.feature_schema,
            scoring_policy=self.scoring_policy,
            text_chars=4000,
        )
        grade_res = self.grader.grade(
            candidate=filtered,
            feature_assessments=score_res.get("feature_assessments") or [],
            gate_flags=score_res.get("gate_flags") or [],
        )

        return {
            "demographic": candidate.get("_demographic_audit", {}),
            "filter": {
                "recommendation": recommendation,
                "confidence": confidence,
                "english_confidence": english_confidence,
                "key_strength": ai_review.get("key_strength"),
                "main_concern": ai_review.get("main_concern"),
                "reasoning": reasoning,
            },
            "ranking": {
                "manual_score": grade_res["manual_score"],
                "category": grade_res["category"],
                "feature_contributions": grade_res["feature_contributions"],
                "gate_penalty": grade_res["gate_penalty"],
                "ai_adjustment": grade_res["ai_adjustment"],
                "triggered_gates": grade_res["triggered_gates"],
                "summary": score_res.get("summary", ""),
            },
        }

    def run_tier_audit(
        self,
        tier_name: str,
        *,
        progress_callback: Any = None,
    ) -> dict[str, Any]:
        """Audit all demographic variants against a given qualification tier."""
        seed = SEED_PROFILES.get(tier_name)
        if not seed:
            raise ValueError(f"Unknown tier: {tier_name}. Expected one of {list(SEED_PROFILES.keys())}")

        template = seed["template"]
        baseline_variant = DEMOGRAPHIC_VARIANTS[0]
        other_variants = DEMOGRAPHIC_VARIANTS[1:]

        logger.info("Starting audit for tier '%s' (baseline repeats: %d)", tier_name, self.baseline_repeats)

        # Step 1: Baseline placebo runs (establish noise band)
        baseline_candidate = perturb_candidate(template, baseline_variant, qualification_tier=tier_name)
        baseline_runs: list[dict[str, Any]] = []

        for i in range(self.baseline_repeats):
            logger.info("Executing baseline run %d/%d for tier '%s'...", i + 1, self.baseline_repeats, tier_name)
            res = self.evaluate_single_candidate(copy.deepcopy(baseline_candidate))
            res["run_index"] = i
            baseline_runs.append(res)
            if progress_callback:
                progress_callback("baseline", i + 1, self.baseline_repeats)

        baseline_scores = [r["ranking"]["manual_score"] for r in baseline_runs]
        baseline_recs = [r["filter"]["recommendation"] for r in baseline_runs]
        mean_baseline_score = round(statistics.mean(baseline_scores), 2)
        score_std_dev = round(statistics.stdev(baseline_scores), 2) if len(baseline_scores) > 1 else 0.0
        score_noise_band = round(max(baseline_scores) - min(baseline_scores), 2)
        modal_baseline_rec = statistics.mode(baseline_recs)

        baseline_summary = {
            "runs": baseline_runs,
            "mean_score": mean_baseline_score,
            "min_score": min(baseline_scores),
            "max_score": max(baseline_scores),
            "noise_band": score_noise_band,
            "std_dev": score_std_dev,
            "modal_recommendation": modal_baseline_rec,
            "all_recommendations": baseline_recs,
        }

        # Step 2: Perturbed variants execution
        variant_candidates = [
            (v, perturb_candidate(template, v, qualification_tier=tier_name))
            for v in other_variants
        ]

        variant_results: list[dict[str, Any]] = []
        total_evals = len(variant_candidates) * self.variants_repeats
        completed_evals = 0

        # Execute variants
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_variant = {}
            for v, cand in variant_candidates:
                for rep in range(self.variants_repeats):
                    fut = executor.submit(self.evaluate_single_candidate, copy.deepcopy(cand))
                    future_to_variant[fut] = (v, rep)

            for fut in concurrent.futures.as_completed(future_to_variant):
                v, rep = future_to_variant[fut]
                completed_evals += 1
                try:
                    res = fut.result()
                    res["run_index"] = rep
                    # Compute deltas vs baseline
                    score = res["ranking"]["manual_score"]
                    rec = res["filter"]["recommendation"]
                    score_delta = round(score - mean_baseline_score, 2)
                    is_rec_flip = rec != modal_baseline_rec
                    is_score_divergence = abs(score_delta) > max(score_noise_band, 3.0)

                    res["delta"] = {
                        "score_delta": score_delta,
                        "is_rec_flip": is_rec_flip,
                        "is_score_divergence": is_score_divergence,
                        "baseline_mean_score": mean_baseline_score,
                        "baseline_modal_rec": modal_baseline_rec,
                    }
                    variant_results.append(res)
                except Exception as e:
                    logger.error("Error evaluating variant %s (rep %d): %s", v["id"], rep, e)
                    variant_results.append({
                        "demographic": {
                            "variant_id": v["id"],
                            "name": v["name"],
                            "group": v["group"],
                            "gender": v["gender"],
                            "ethnicity": v["ethnicity"],
                            "religion_marker": v["religion_marker"],
                            "qualification_tier": tier_name,
                        },
                        "error": str(e),
                        "run_index": rep,
                    })

                if progress_callback:
                    progress_callback("variants", completed_evals, total_evals)

        # Sort variant results by variant id for consistent reporting
        variant_results.sort(key=lambda x: (x.get("demographic", {}).get("group", ""), x.get("demographic", {}).get("name", "")))

        # Aggregate tier metrics
        valid_variants = [r for r in variant_results if "error" not in r]
        flips = [r for r in valid_variants if r["delta"]["is_rec_flip"]]
        divergences = [r for r in valid_variants if r["delta"]["is_score_divergence"]]

        tier_summary = {
            "tier": tier_name,
            "tier_description": seed["description"],
            "baseline": baseline_summary,
            "variants": variant_results,
            "metrics": {
                "total_variants_evaluated": len(valid_variants),
                "total_errors": len(variant_results) - len(valid_variants),
                "flip_count": len(flips),
                "flip_rate_pct": round((len(flips) / len(valid_variants) * 100) if valid_variants else 0, 1),
                "score_divergence_count": len(divergences),
                "score_divergence_pct": round((len(divergences) / len(valid_variants) * 100) if valid_variants else 0, 1),
                "max_negative_delta": min([r["delta"]["score_delta"] for r in valid_variants], default=0.0),
                "max_positive_delta": max([r["delta"]["score_delta"] for r in valid_variants], default=0.0),
            },
        }

        return tier_summary

    def run_full_audit(
        self,
        *,
        tiers: list[str] | None = None,
        progress_callback: Any = None,
    ) -> dict[str, Any]:
        """Run audit across multiple qualification tiers (default: high_fit and borderline_fit)."""
        target_tiers = tiers or ["high_fit", "borderline_fit"]
        start_time = time.time()

        tier_results = {}
        for t in target_tiers:
            tier_results[t] = self.run_tier_audit(t, progress_callback=progress_callback)

        duration = round(time.time() - start_time, 2)

        total_variants = sum(tr["metrics"]["total_variants_evaluated"] for tr in tier_results.values())
        total_flips = sum(tr["metrics"]["flip_count"] for tr in tier_results.values())
        total_divergences = sum(tr["metrics"]["score_divergence_count"] for tr in tier_results.values())

        overall_status = "PASS"
        if total_flips > 0 or total_divergences > 0:
            overall_status = "BIAS_FLAGGED"

        return {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
            "status": overall_status,
            "model": self.model,
            "duration_seconds": duration,
            "summary": {
                "tiers_evaluated": target_tiers,
                "total_variants_evaluated": total_variants,
                "total_recommendation_flips": total_flips,
                "overall_flip_rate_pct": round((total_flips / total_variants * 100) if total_variants else 0, 1),
                "total_score_divergences": total_divergences,
                "overall_divergence_rate_pct": round((total_divergences / total_variants * 100) if total_variants else 0, 1),
            },
            "tiers": tier_results,
        }
