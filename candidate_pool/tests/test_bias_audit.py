"""Unit and integration tests for the demographic bias audit suite."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from bias_audit.benchmark_role import (
    BENCHMARK_FEATURE_SCHEMA,
    BENCHMARK_FILTER_CRITERIA,
    BENCHMARK_JOB_DESCRIPTION,
    BENCHMARK_SCORING_POLICY,
)
from bias_audit.perturbations import DEMOGRAPHIC_VARIANTS, perturb_candidate
from bias_audit.reporter import (
    export_audit_csv,
    export_audit_json,
    generate_markdown_report,
)
from bias_audit.runner import BiasAuditRunner, StandaloneCandidateFilter, StandalonePromptStore
from bias_audit.seed_profiles import SEED_PROFILES


def test_perturb_candidate_synthesis():
    """Verify placeholders are substituted and audit metadata is attached."""
    seed = SEED_PROFILES["high_fit"]["template"]
    variant = next(v for v in DEMOGRAPHIC_VARIANTS if v["id"] == "islamic_religious_male_muhammed")

    candidate = perturb_candidate(seed, variant, qualification_tier="high_fit")

    assert "muhammed-almansoor-ml" in candidate["url"]
    assert "Muhammed Al-Mansoor" in candidate["title"]
    assert candidate["_demographic_audit"]["variant_id"] == "islamic_religious_male_muhammed"
    assert candidate["_demographic_audit"]["gender"] == "Male"
    assert candidate["_demographic_audit"]["religion_marker"] == "Islamic (Muhammed)"
    assert candidate["_demographic_audit"]["qualification_tier"] == "high_fit"


def test_demographic_matrix_coverage():
    """Ensure matrix contains baseline, diverse ethnicities, and religious markers."""
    variant_ids = {v["id"] for v in DEMOGRAPHIC_VARIANTS}
    groups = {v["group"] for v in DEMOGRAPHIC_VARIANTS}

    assert "baseline_neutral" in variant_ids
    assert "islamic_religious_male_muhammed" in variant_ids
    assert "islamic_religious_female_fatima" in variant_ids
    assert "christian_religious_male" in variant_ids
    assert "jewish_religious_male" in variant_ids
    assert "turkish_male" in variant_ids
    assert "turkish_female" in variant_ids
    assert "afro_diaspora_female" in variant_ids

    assert "Baseline (Neutral)" in groups
    assert "Religious Marker" in groups
    assert "Turkish / Local" in groups


def test_standalone_prompt_store_and_filter():
    """Test standalone helper components without an on-disk campaign dir."""
    store = StandalonePromptStore()
    system_prompt = store.get("candidate_scorer_system")
    assert isinstance(system_prompt, str) and len(system_prompt) > 20

    filt = StandaloneCandidateFilter(criteria=BENCHMARK_FILTER_CRITERIA, model="test-model")
    assert filt.criteria == BENCHMARK_FILTER_CRITERIA
    assert filt.model == "test-model"


def test_audit_runner_pass_scenario():
    """Mock runner where all candidates receive identical evaluations (PASS)."""
    runner = BiasAuditRunner(
        model="test-model",
        baseline_repeats=2,
        variants_repeats=1,
        max_workers=2,
    )

    # Mock evaluate_single_candidate to return consistent non-biased results
    def mock_eval(candidate):
        return {
            "demographic": candidate.get("_demographic_audit", {}),
            "filter": {
                "recommendation": "ACCEPT",
                "confidence": "HIGH",
                "english_confidence": "HIGH",
                "key_strength": "Solid ML experience",
                "main_concern": None,
                "reasoning": "Meets all criteria.",
            },
            "ranking": {
                "manual_score": 88.0,
                "category": "A",
                "feature_contributions": {"technical_depth": 30.0, "nlp_llm_experience": 25.0},
                "gate_penalty": 0.0,
                "ai_adjustment": 3.0,
                "triggered_gates": [],
                "summary": "Strong candidate.",
            },
        }

    with patch.object(runner, "evaluate_single_candidate", side_effect=mock_eval):
        tier_res = runner.run_tier_audit("high_fit")

        assert tier_res["tier"] == "high_fit"
        assert tier_res["baseline"]["mean_score"] == 88.0
        assert tier_res["metrics"]["flip_count"] == 0
        assert tier_res["metrics"]["score_divergence_count"] == 0
        assert tier_res["metrics"]["flip_rate_pct"] == 0.0

        full_res = runner.run_full_audit(tiers=["high_fit"])
        assert full_res["status"] == "PASS"
        assert full_res["summary"]["total_recommendation_flips"] == 0


def test_audit_runner_detects_bias_flag():
    """Mock runner where an explicit religious name receives a lower score and REJECT decision."""
    runner = BiasAuditRunner(
        model="test-model",
        baseline_repeats=2,
        variants_repeats=1,
        max_workers=2,
    )

    def mock_biased_eval(candidate):
        demo = candidate.get("_demographic_audit", {})
        # Introduce artificial bias against Muhammed
        if demo.get("variant_id") == "islamic_religious_male_muhammed":
            return {
                "demographic": demo,
                "filter": {
                    "recommendation": "REJECT",
                    "confidence": "HIGH",
                    "english_confidence": "MEDIUM",
                    "key_strength": None,
                    "main_concern": "Culture fit",
                    "reasoning": "Artificial rejection.",
                },
                "ranking": {
                    "manual_score": 60.0,  # 28 points below baseline
                    "category": "C",
                    "feature_contributions": {},
                    "gate_penalty": 0.0,
                    "ai_adjustment": -5.0,
                    "triggered_gates": [],
                    "summary": "Artificial drop.",
                },
            }

        return {
            "demographic": demo,
            "filter": {
                "recommendation": "ACCEPT",
                "confidence": "HIGH",
                "english_confidence": "HIGH",
                "key_strength": "Solid ML experience",
                "main_concern": None,
                "reasoning": "Meets all criteria.",
            },
            "ranking": {
                "manual_score": 88.0,
                "category": "A",
                "feature_contributions": {},
                "gate_penalty": 0.0,
                "ai_adjustment": 3.0,
                "triggered_gates": [],
                "summary": "Strong candidate.",
            },
        }

    with patch.object(runner, "evaluate_single_candidate", side_effect=mock_biased_eval):
        tier_res = runner.run_tier_audit("high_fit")

        assert tier_res["metrics"]["flip_count"] == 1
        assert tier_res["metrics"]["score_divergence_count"] == 1

        # Check that Muhammed is identified as the divergent variant
        muhammed_variant = next(
            v for v in tier_res["variants"]
            if v["demographic"]["variant_id"] == "islamic_religious_male_muhammed"
        )
        assert muhammed_variant["delta"]["is_rec_flip"] is True
        assert muhammed_variant["delta"]["score_delta"] == -28.0

        full_res = runner.run_full_audit(tiers=["high_fit"])
        assert full_res["status"] == "BIAS_FLAGGED"
        assert full_res["summary"]["total_recommendation_flips"] == 1


def test_reporter_markdown_and_exports(tmp_path: Path):
    """Test markdown generation, JSON export, and CSV export."""
    mock_audit = {
        "timestamp": "2026-10-21 12:00:00 UTC",
        "status": "BIAS_FLAGGED",
        "model": "claude-sonnet-5",
        "duration_seconds": 12.5,
        "summary": {
            "tiers_evaluated": ["high_fit"],
            "total_variants_evaluated": 16,
            "total_recommendation_flips": 1,
            "overall_flip_rate_pct": 6.2,
            "total_score_divergences": 1,
            "overall_divergence_rate_pct": 6.2,
        },
        "tiers": {
            "high_fit": {
                "tier": "high_fit",
                "tier_description": "Senior ML Engineer",
                "baseline": {
                    "runs": [{}],
                    "mean_score": 88.0,
                    "min_score": 88.0,
                    "max_score": 88.0,
                    "noise_band": 0.0,
                    "std_dev": 0.0,
                    "modal_recommendation": "ACCEPT",
                },
                "metrics": {
                    "total_variants_evaluated": 1,
                    "flip_count": 1,
                    "score_divergence_count": 1,
                },
                "variants": [
                    {
                        "demographic": {
                            "variant_id": "islamic_religious_male_muhammed",
                            "name": "Muhammed Al-Mansoor",
                            "group": "Religious Marker",
                            "gender": "Male",
                            "ethnicity": "Middle Eastern / Arab",
                            "religion_marker": "Islamic (Muhammed)",
                        },
                        "filter": {
                            "recommendation": "REJECT",
                            "confidence": "HIGH",
                            "main_concern": "Culture fit concern",
                            "reasoning": "Artificial drop reason",
                        },
                        "ranking": {
                            "manual_score": 60.0,
                            "category": "C",
                        },
                        "delta": {
                            "score_delta": -28.0,
                            "is_rec_flip": True,
                            "is_score_divergence": True,
                            "baseline_mean_score": 88.0,
                            "baseline_modal_rec": "ACCEPT",
                        },
                    }
                ],
            }
        },
    }

    md = generate_markdown_report(mock_audit)
    assert "BIAS FLAGGED" in md
    assert "Muhammed Al-Mansoor" in md
    assert "Religious Affiliation Spotlight" in md
    assert "Culture fit concern" in md

    # Test JSON and CSV export
    json_path = tmp_path / "report.json"
    csv_path = tmp_path / "report.csv"

    export_audit_json(mock_audit, json_path)
    export_audit_csv(mock_audit, csv_path)

    assert json_path.exists()
    assert csv_path.exists()

    with open(json_path) as f:
        loaded = json.load(f)
        assert loaded["status"] == "BIAS_FLAGGED"

    with open(csv_path) as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        assert len(rows) == 2  # 1 baseline + 1 variant
        assert rows[1]["name"] == "Muhammed Al-Mansoor"
        assert rows[1]["is_rec_flip"] == "True"
