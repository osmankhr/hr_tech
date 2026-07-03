"""Agent that designs weighted scoring policy for the dynamic feature schema."""
from __future__ import annotations

import json
from typing import Any

from .agent_base import JsonAgent
from ..prompt_store import PromptStore
from ..utils.json_utils import ensure_dict, ensure_list


class ScoringDesignerAgent(JsonAgent):
    def __init__(self, model: str, prompt_store: PromptStore, timeout: int = 120) -> None:
        super().__init__(model=model, timeout=timeout)
        self.prompt_store = prompt_store

    def design(
        self,
        *,
        job_description: str,
        filter_criteria: str,
        feature_schema: dict[str, Any],
    ) -> dict[str, Any]:
        system = self.prompt_store.get("scoring_designer_system")
        user = self.prompt_store.get("scoring_designer_user").format(
            job_description=job_description,
            filter_criteria=filter_criteria,
            feature_schema_json=json.dumps(feature_schema, indent=2, ensure_ascii=False),
        )

        obj = self.call_json(system=system, user=user) or {}
        weights = ensure_dict(obj.get("weights"))
        features = ensure_list(feature_schema.get("features"))

        feature_ids = [str(f.get("id")) for f in features if isinstance(f, dict) and f.get("id")]
        normalized = self._normalize_weights(weights, feature_ids)
        hard_gates = self._normalize_hard_gates(obj.get("hard_gates"))

        return {
            "weights": normalized,
            "hard_gates": hard_gates,
            "scoring_rules": ensure_dict(obj.get("scoring_rules")),
            "normalization": ensure_dict(obj.get("normalization")),
            "sanity_checks": ensure_list(obj.get("sanity_checks")),
            "tiers": self._normalize_tiers(ensure_dict(obj.get("tiers"))),
            "notes": ensure_list(obj.get("notes")),
            "raw_response": obj,
        }

    def _normalize_weights(self, weights: dict[str, Any], feature_ids: list[str]) -> dict[str, int]:
        if not feature_ids:
            return {}

        cleaned: dict[str, float] = {}
        for fid in feature_ids:
            raw = weights.get(fid)
            if isinstance(raw, (int, float)) and raw >= 0:
                cleaned[fid] = float(raw)

        if not cleaned:
            even = 100.0 / len(feature_ids)
            cleaned = {fid: even for fid in feature_ids}

        # Fill missing features with zero then rebalance to sum 100
        for fid in feature_ids:
            cleaned.setdefault(fid, 0.0)

        total = sum(cleaned.values())
        if total <= 0:
            even = 100.0 / len(feature_ids)
            cleaned = {fid: even for fid in feature_ids}
            total = 100.0

        scaled = {fid: (val / total) * 100.0 for fid, val in cleaned.items()}

        # Convert to int while preserving sum=100
        ints = {fid: int(val) for fid, val in scaled.items()}
        remainder = 100 - sum(ints.values())
        order = sorted(feature_ids, key=lambda f: scaled[f] - ints[f], reverse=True)
        for idx in range(remainder):
            ints[order[idx % len(order)]] += 1

        return ints

    def _normalize_tiers(self, tiers: dict[str, Any]) -> dict[str, int]:
        defaults = {"A": 85, "B": 70, "C": 55}
        out: dict[str, int] = {}
        for key in ("A", "B", "C"):
            value = tiers.get(key, defaults[key])
            if not isinstance(value, (int, float)):
                value = defaults[key]
            out[key] = max(0, min(100, int(value)))

        # Keep monotonic descending thresholds
        out["A"] = max(out["A"], out["B"])
        out["B"] = max(out["B"], out["C"])
        return out

    def _normalize_hard_gates(self, hard_gates: Any) -> list[dict[str, Any]]:
        # Backward-compatible shape: list of gate dicts.
        if isinstance(hard_gates, list):
            return [g for g in hard_gates if isinstance(g, dict)]

        # New generalized shape from prompt: {must_have: [...], reject_if: [...]}.
        if isinstance(hard_gates, dict):
            out: list[dict[str, Any]] = []
            must_have = hard_gates.get("must_have")
            reject_if = hard_gates.get("reject_if")

            if isinstance(must_have, list):
                for i, rule in enumerate(must_have, 1):
                    out.append(
                        {
                            "id": f"must_have_{i}",
                            "description": str(rule),
                            "trigger_rule": f"Missing required condition: {rule}",
                            "penalty": "REJECT",
                            "group": "must_have",
                        }
                    )

            if isinstance(reject_if, list):
                for i, rule in enumerate(reject_if, 1):
                    out.append(
                        {
                            "id": f"reject_if_{i}",
                            "description": str(rule),
                            "trigger_rule": str(rule),
                            "penalty": "REJECT",
                            "group": "reject_if",
                        }
                    )

            return out

        return []
