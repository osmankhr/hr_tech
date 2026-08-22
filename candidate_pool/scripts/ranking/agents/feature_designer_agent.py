"""Agent that designs dynamic feature schema from JD + criteria."""
from __future__ import annotations

import json
import logging
from typing import Any

from .agent_base import JsonAgent
from ..prompt_store import PromptStore
from ..utils.json_utils import ensure_list

logger = logging.getLogger(__name__)


class FeatureDesignerAgent(JsonAgent):
    def __init__(self, model: str, prompt_store: PromptStore, timeout: int = 120) -> None:
        super().__init__(model=model, timeout=timeout)
        self.prompt_store = prompt_store

    def design(
        self,
        *,
        job_description: str,
        filter_criteria: str,
        max_features: int,
    ) -> dict[str, Any]:
        system = self.prompt_store.get("feature_designer_system")
        user = self.prompt_store.get("feature_designer_user").format(
            job_description=job_description,
            filter_criteria=filter_criteria,
            max_features=max_features,
        )

        obj = self.call_json(system=system, user=user, retries=1) or {}
        features = ensure_list(obj.get("features"))
        capabilities = ensure_list(obj.get("capabilities"))

        cleaned: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for i, item in enumerate(features, 1):
            if not isinstance(item, dict):
                continue
            feature_id = str(item.get("id") or f"feature_{i}").strip().lower().replace(" ", "_")
            if not feature_id or feature_id in seen_ids:
                feature_id = f"feature_{i}"
            seen_ids.add(feature_id)

            max_points = item.get("max_points")
            if not isinstance(max_points, int) or max_points <= 0:
                max_points = 10

            cleaned.append(
                {
                    "id": feature_id,
                    "name": str(item.get("name") or feature_id),
                    "description": str(item.get("description") or ""),
                    "reason": str(item.get("reason") or ""),
                    "value_type": str(item.get("value_type") or "numeric"),
                    "max_points": max_points,
                    "extraction_logic": ensure_list(item.get("extraction_logic")),
                    "evidence_examples": ensure_list(item.get("evidence_examples")),
                }
            )

        used_fallback = not cleaned
        if used_fallback:
            logger.error(
                "Feature designer got no usable features from the model after retries — "
                "using a role-agnostic fallback schema instead of role-specific features. "
                "This campaign's job description/filter criteria could not be scored on "
                "role-specific skills; re-run to retry the AI design step."
            )
            # Deliberately role-agnostic: this fires when the model call/parse failed, so we
            # have no signal about what the role actually needs. A previous version hardcoded
            # NLP/LLM/Python-flavored features here, which silently biased every campaign's
            # scoring toward NLP candidates whenever this fallback triggered (reported by
            # recruiters as candidates being scored/tagged for skills the role never asked for).
            cleaned = [
                {
                    "id": "criteria_match",
                    "name": "Filter Criteria Match",
                    "description": "How well the candidate matches the stated filter criteria.",
                    "reason": "Fallback feature — the AI feature-design step failed, so scoring "
                              "falls back to the raw filter criteria instead of role-derived skills.",
                    "value_type": "numeric",
                    "max_points": 25,
                    "extraction_logic": ["See filter_criteria.md for this campaign"],
                    "evidence_examples": [],
                },
                {
                    "id": "seniority",
                    "name": "Seniority",
                    "description": "Role seniority and years of experience.",
                    "reason": "Generic signal, independent of role specialization.",
                    "value_type": "numeric",
                    "max_points": 20,
                    "extraction_logic": ["Total Experience", "Senior", "Lead", "Principal", "Staff"],
                    "evidence_examples": [],
                },
            ]

        return {
            "capabilities": capabilities,
            "features": cleaned[:max_features],
            "notes": ensure_list(obj.get("notes")),
            "raw_response": obj,
            "fallback": used_fallback,
        }
