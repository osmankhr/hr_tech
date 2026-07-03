"""Deterministic grading layer over agent-produced feature assessments."""
from __future__ import annotations

from typing import Any


class ManualGrader:
    """Compute reproducible weighted scores from extracted feature assessments."""

    def __init__(self, scoring_policy: dict[str, Any], ai_review_adjustments: dict[str, float] | None = None) -> None:
        self.scoring_policy = scoring_policy
        self.weights: dict[str, int] = {
            str(k): int(v)
            for k, v in (scoring_policy.get("weights") or {}).items()
            if isinstance(v, (int, float))
        }
        self.tiers = scoring_policy.get("tiers") or {"A": 85, "B": 70, "C": 55}
        self.ai_review_adjustments = ai_review_adjustments or {
            "ACCEPT": 3.0,
            "PENDING": 0.0,
            "REJECT": -5.0,
        }

    def grade(
        self,
        *,
        candidate: dict[str, Any],
        feature_assessments: list[dict[str, Any]],
        gate_flags: list[dict[str, Any]],
    ) -> dict[str, Any]:
        by_id = {str(row.get("feature_id")): row for row in feature_assessments if isinstance(row, dict)}

        contributions: dict[str, float] = {}
        total = 0.0
        for feature_id, weight in self.weights.items():
            row = by_id.get(feature_id, {})
            raw_points = row.get("raw_points", 0)
            max_points = row.get("max_points", 0)
            if not isinstance(raw_points, (int, float)):
                raw_points = 0.0
            if not isinstance(max_points, (int, float)) or max_points <= 0:
                max_points = 1.0

            contribution = float(weight) * max(0.0, min(1.0, float(raw_points) / float(max_points)))
            contributions[feature_id] = round(contribution, 2)
            total += contribution

        gate_penalty, triggered_gates = self._apply_gate_penalties(gate_flags)
        total += gate_penalty

        ai_review = (candidate.get("ai_review") or {}).get("recommendation")
        ai_adjustment = float(self.ai_review_adjustments.get(str(ai_review), 0.0))
        total += ai_adjustment

        final_score = round(max(0.0, min(100.0, total)), 2)
        category = self._category_for_score(final_score, has_reject_gate=any(g["penalty"] == "REJECT" for g in triggered_gates))

        return {
            "manual_score": final_score,
            "category": category,
            "feature_contributions": contributions,
            "gate_penalty": gate_penalty,
            "ai_adjustment": ai_adjustment,
            "triggered_gates": triggered_gates,
        }

    def _apply_gate_penalties(self, gate_flags: list[dict[str, Any]]) -> tuple[float, list[dict[str, Any]]]:
        total_penalty = 0.0
        triggered: list[dict[str, Any]] = []

        gate_by_id: dict[str, dict[str, Any]] = {}
        for gate in self.scoring_policy.get("hard_gates") or []:
            if isinstance(gate, dict) and gate.get("id"):
                gate_by_id[str(gate["id"])] = gate

        for flag in gate_flags:
            if not isinstance(flag, dict):
                continue
            if not flag.get("triggered"):
                continue
            gate_id = str(flag.get("gate_id") or "")
            gate = gate_by_id.get(gate_id, {})
            penalty = str(gate.get("penalty") or "")
            if penalty.startswith("MINUS_"):
                amount = penalty.replace("MINUS_", "")
                if amount.isdigit():
                    total_penalty -= float(amount)
            triggered.append(
                {
                    "gate_id": gate_id,
                    "penalty": penalty or "UNKNOWN",
                    "reason": str(flag.get("reason") or gate.get("description") or ""),
                }
            )

        return total_penalty, triggered

    def _category_for_score(self, score: float, has_reject_gate: bool) -> str:
        if has_reject_gate:
            return "D"

        threshold_a = float(self.tiers.get("A", 85))
        threshold_b = float(self.tiers.get("B", 70))
        threshold_c = float(self.tiers.get("C", 55))

        if score >= threshold_a:
            return "A"
        if score >= threshold_b:
            return "B"
        if score >= threshold_c:
            return "C"
        return "D"
