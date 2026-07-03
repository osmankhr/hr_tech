"""Agent that scores one candidate against dynamic feature schema and policy."""
from __future__ import annotations

import json
from typing import Any

from .agent_base import JsonAgent
from ..prompt_store import PromptStore
from ..utils.json_utils import ensure_list


class CandidateScorerAgent(JsonAgent):
    def __init__(self, model: str, prompt_store: PromptStore, timeout: int = 120) -> None:
        super().__init__(model=model, timeout=timeout)
        self.prompt_store = prompt_store

    def score_candidate(
        self,
        *,
        candidate: dict[str, Any],
        feature_schema: dict[str, Any],
        scoring_policy: dict[str, Any],
        text_chars: int,
    ) -> dict[str, Any]:
        system = self.prompt_store.get("candidate_scorer_system")
        profile = self._candidate_summary(candidate, text_chars=text_chars)

        user = self.prompt_store.get("candidate_scorer_user").format(
            candidate_json=json.dumps(profile, indent=2, ensure_ascii=False),
            feature_schema_json=json.dumps(feature_schema, indent=2, ensure_ascii=False),
            scoring_policy_json=json.dumps(scoring_policy, indent=2, ensure_ascii=False),
        )

        obj = self.call_json(system=system, user=user) or {}
        assessments = self._normalize_assessments(obj.get("feature_assessments"), feature_schema)
        gate_flags = ensure_list(obj.get("gate_flags"))

        return {
            "feature_assessments": assessments,
            "gate_flags": gate_flags,
            "summary": str(obj.get("summary") or ""),
            "raw_response": obj,
        }

    def _candidate_summary(self, candidate: dict[str, Any], text_chars: int) -> dict[str, Any]:
        return {
            "url": candidate.get("url"),
            "title": candidate.get("title"),
            "location": candidate.get("location"),
            "query": candidate.get("query"),
            "published_date": candidate.get("published_date"),
            "ai_review": candidate.get("ai_review"),
            "highlights": candidate.get("highlights"),
            "text_excerpt": (candidate.get("text") or "")[:text_chars],
        }

    def _normalize_assessments(
        self,
        assessments: Any,
        feature_schema: dict[str, Any],
    ) -> list[dict[str, Any]]:
        raw = ensure_list(assessments)
        by_id: dict[str, dict[str, Any]] = {}
        for row in raw:
            if not isinstance(row, dict):
                continue
            fid = str(row.get("feature_id") or "").strip()
            if not fid:
                continue
            by_id[fid] = row

        out: list[dict[str, Any]] = []
        for feat in ensure_list(feature_schema.get("features")):
            if not isinstance(feat, dict):
                continue
            fid = str(feat.get("id") or "")
            max_points = feat.get("max_points") if isinstance(feat.get("max_points"), int) else 10
            row = by_id.get(fid, {})
            raw_points = row.get("raw_points", 0)
            if not isinstance(raw_points, (int, float)):
                raw_points = 0
            raw_points = max(0.0, min(float(max_points), float(raw_points)))

            out.append(
                {
                    "feature_id": fid,
                    "raw_points": raw_points,
                    "max_points": max_points,
                    "confidence": str(row.get("confidence") or "LOW"),
                    "evidence": ensure_list(row.get("evidence")),
                    "notes": str(row.get("notes") or ""),
                }
            )

        return out
