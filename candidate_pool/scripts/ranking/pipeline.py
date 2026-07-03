"""End-to-end agentic ranking pipeline with deterministic scoring."""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from .agents.candidate_scorer_agent import CandidateScorerAgent
from .agents.feature_designer_agent import FeatureDesignerAgent
from .manual_grader import ManualGrader
from .prompt_store import PromptStore
from .agents.scoring_designer_agent import ScoringDesignerAgent

logger = logging.getLogger(__name__)


class RankingPipeline:
    def __init__(self, campaign_dir: Path, config: dict[str, Any]) -> None:
        self.campaign_dir = campaign_dir
        self.config = config
        self.rank_cfg = config.get("ranking", {})

        self.model = self.rank_cfg.get(
            "model",
            config.get("filter", {}).get("model", "claude-sonnet-4-5"),
        )
        self.max_features = int(self.rank_cfg.get("max_features", 10))
        self.max_candidates = int(self.rank_cfg.get("max_candidates", 1000))
        self.text_chars = int(self.rank_cfg.get("candidate_text_chars", 5000))
        self.batch_size = max(1, int(self.rank_cfg.get("batch_size", 50)))
        self.max_workers = max(1, int(self.rank_cfg.get("max_workers", self.batch_size)))
        self.only_accepted = bool(self.rank_cfg.get("only_accepted", False))
        self.force_redesign = bool(self.rank_cfg.get("force_redesign", False))

        self.input_path = self.campaign_dir / self.rank_cfg.get("input_path", "data/filtered_results.json")
        self.feature_schema_path = self.campaign_dir / self.rank_cfg.get(
            "feature_schema_path", "data/ranking_feature_schema.json"
        )
        self.scoring_policy_path = self.campaign_dir / self.rank_cfg.get(
            "scoring_policy_path", "data/ranking_scoring_policy.json"
        )
        self.output_path = self.campaign_dir / self.rank_cfg.get("output_path", "data/ranked_results.json")
        self.summary_path = self.campaign_dir / self.rank_cfg.get("summary_path", "data/ranking_summary.json")

        prompt_store = PromptStore(self.campaign_dir, self.rank_cfg.get("prompts"))
        timeout = int(self.rank_cfg.get("timeout_seconds", 120))

        self.feature_agent = FeatureDesignerAgent(model=self.model, prompt_store=prompt_store, timeout=timeout)
        self.scoring_agent = ScoringDesignerAgent(model=self.model, prompt_store=prompt_store, timeout=timeout)
        self.candidate_agent = CandidateScorerAgent(model=self.model, prompt_store=prompt_store, timeout=timeout)

    def run(self) -> list[dict[str, Any]]:
        candidates = self._load_candidates()
        job_description, filter_criteria = self._load_inputs()

        feature_schema = self._load_or_build_feature_schema(
            job_description=job_description,
            filter_criteria=filter_criteria,
        )
        scoring_policy = self._load_or_build_scoring_policy(
            job_description=job_description,
            filter_criteria=filter_criteria,
            feature_schema=feature_schema,
        )

        grader = ManualGrader(
            scoring_policy=scoring_policy,
            ai_review_adjustments=self.rank_cfg.get("ai_review_adjustments"),
        )

        ranked_with_source_index: list[tuple[int, dict[str, Any]]] = []
        total_candidates = len(candidates)

        def _score_one(source_index: int, candidate: dict[str, Any]) -> tuple[int, dict[str, Any]]:
            label = candidate.get("title") or candidate.get("url") or "unknown"
            logger.info("[Rank %d/%d] %s", source_index + 1, total_candidates, label)

            agent_score = self.candidate_agent.score_candidate(
                candidate=candidate,
                feature_schema=feature_schema,
                scoring_policy=scoring_policy,
                text_chars=self.text_chars,
            )
            manual = grader.grade(
                candidate=candidate,
                feature_assessments=agent_score["feature_assessments"],
                gate_flags=agent_score["gate_flags"],
            )

            ranked_candidate = {
                **candidate,
                "ranking": {
                    "manual": manual,
                    "agent": {
                        "feature_assessments": agent_score["feature_assessments"],
                        "gate_flags": agent_score["gate_flags"],
                        "summary": agent_score["summary"],
                    },
                },
            }
            return source_index, ranked_candidate

        for batch_start in range(0, total_candidates, self.batch_size):
            batch_end = min(batch_start + self.batch_size, total_candidates)
            batch = candidates[batch_start:batch_end]
            logger.info(
                "Ranking batch %d-%d of %d (batch_size=%d, workers=%d)",
                batch_start + 1,
                batch_end,
                total_candidates,
                self.batch_size,
                min(self.max_workers, len(batch)),
            )

            with ThreadPoolExecutor(max_workers=min(self.max_workers, len(batch))) as executor:
                future_map = {
                    executor.submit(_score_one, batch_start + offset, candidate): batch_start + offset
                    for offset, candidate in enumerate(batch)
                }

                for future in as_completed(future_map):
                    ranked_with_source_index.append(future.result())

        ranked_with_source_index.sort(key=lambda item: item[0])
        ranked = [item[1] for item in ranked_with_source_index]

        ranked.sort(
            key=lambda c: (
                (c.get("ranking") or {}).get("manual", {}).get("manual_score") or 0,
                (c.get("score") or 0),
            ),
            reverse=True,
        )

        for pos, candidate in enumerate(ranked, 1):
            candidate.setdefault("ranking", {}).setdefault("manual", {})["rank"] = pos

        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.output_path, "w") as f:
            json.dump(ranked, f, indent=2, ensure_ascii=False)

        summary = self._build_summary(ranked)
        with open(self.summary_path, "w") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        logger.info("Ranking complete: saved %s", self.output_path)
        logger.info("Ranking summary: saved %s", self.summary_path)
        return ranked

    def _load_candidates(self) -> list[dict[str, Any]]:
        if not self.input_path.exists():
            raise FileNotFoundError(f"Ranking input file not found: {self.input_path}")

        with open(self.input_path) as f:
            rows = json.load(f)

        if not isinstance(rows, list):
            raise ValueError(f"Ranking input must be a list of candidates: {self.input_path}")

        candidates = [r for r in rows if isinstance(r, dict)]
        if self.only_accepted:
            candidates = [
                c
                for c in candidates
                if (c.get("ai_review") or {}).get("recommendation") == "ACCEPT"
            ]

        candidates = candidates[: self.max_candidates]
        logger.info("Loaded %d candidates for ranking", len(candidates))
        return candidates

    def _load_inputs(self) -> tuple[str, str]:
        jd_path = self.campaign_dir / self.rank_cfg.get("job_description_path", "input/job_description.md")
        criteria_path = self.campaign_dir / self.rank_cfg.get("filter_criteria_path", "input/filter_criteria.md")

        if not jd_path.exists():
            raise FileNotFoundError(f"Job description file not found: {jd_path}")
        if not criteria_path.exists():
            raise FileNotFoundError(f"Filter criteria file not found: {criteria_path}")

        return jd_path.read_text(), criteria_path.read_text()

    def _load_or_build_feature_schema(
        self,
        *,
        job_description: str,
        filter_criteria: str,
    ) -> dict[str, Any]:
        if self.feature_schema_path.exists() and not self.force_redesign:
            with open(self.feature_schema_path) as f:
                schema = json.load(f)
            logger.info("Loaded cached feature schema: %s", self.feature_schema_path)
            return schema

        schema = self.feature_agent.design(
            job_description=job_description,
            filter_criteria=filter_criteria,
            max_features=self.max_features,
        )
        self.feature_schema_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.feature_schema_path, "w") as f:
            json.dump(schema, f, indent=2, ensure_ascii=False)
        logger.info("Generated feature schema: %s", self.feature_schema_path)
        return schema

    def _load_or_build_scoring_policy(
        self,
        *,
        job_description: str,
        filter_criteria: str,
        feature_schema: dict[str, Any],
    ) -> dict[str, Any]:
        if self.scoring_policy_path.exists() and not self.force_redesign:
            with open(self.scoring_policy_path) as f:
                policy = json.load(f)
            logger.info("Loaded cached scoring policy: %s", self.scoring_policy_path)
            return policy

        policy = self.scoring_agent.design(
            job_description=job_description,
            filter_criteria=filter_criteria,
            feature_schema=feature_schema,
        )
        self.scoring_policy_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.scoring_policy_path, "w") as f:
            json.dump(policy, f, indent=2, ensure_ascii=False)
        logger.info("Generated scoring policy: %s", self.scoring_policy_path)
        return policy

    def _build_summary(self, ranked: list[dict[str, Any]]) -> dict[str, Any]:
        tiers = {"A": 0, "B": 0, "C": 0, "D": 0}
        for c in ranked:
            category = (c.get("ranking") or {}).get("manual", {}).get("category")
            if category in tiers:
                tiers[category] += 1

        top_candidates = [
            {
                "rank": (c.get("ranking") or {}).get("manual", {}).get("rank"),
                "title": c.get("title"),
                "url": c.get("url"),
                "score": (c.get("ranking") or {}).get("manual", {}).get("manual_score"),
                "category": (c.get("ranking") or {}).get("manual", {}).get("category"),
            }
            for c in ranked[:10]
        ]

        return {
            "total_ranked": len(ranked),
            "tiers": tiers,
            "top_10": top_candidates,
        }
