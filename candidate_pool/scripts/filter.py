"""AI-driven candidate filtering via Claude headless mode."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging
import re
from pathlib import Path
from typing import Any

from llm_provider import call_model_text

logger = logging.getLogger(__name__)

_SYSTEM_INSTRUCTIONS = """\
You are a recruitment assistant. Review the candidate profile against the provided \
criteria and respond ONLY with a valid JSON object — no markdown fences, no preamble.
"""

_PROMPT_TEMPLATE = """\
## Filtering Criteria

{criteria}

## Candidate Profile

{candidate_json}

## Instructions

First, determine the candidate's real current location and real current job title strictly \
from the profile text/highlights above (ignore any "location" value already attached to the \
profile — that value reflects which search bucket the record was pulled from, not a verified fact). \
If the profile text does not state a location or title clearly, use null.

If the Filtering Criteria include a location requirement, treat it as a hard requirement: only \
recommend ACCEPT when the candidate's real location (as you just determined it) clearly satisfies \
it. If the real location clearly does not satisfy it, recommend REJECT and say so in main_concern. \
If the location cannot be determined from the profile text, recommend PENDING (not ACCEPT) so a \
human can verify.

Evaluate this candidate and return a JSON object with exactly these fields:
{{
  "recommendation": "ACCEPT" | "REJECT" | "PENDING",
  "confidence": "HIGH" | "MEDIUM" | "LOW",
  "candidate_location": "<candidate's real current location as stated in their profile text, or null>",
  "candidate_job_title": "<candidate's real current job title as stated in their profile text, or null>",
  "key_strength": "<one sentence describing the strongest qualification>",
  "main_concern": "<one sentence describing the main gap, or null if none>",
  "reasoning": "<2-3 sentence explanation of the decision>"
}}
"""


def _extract_json(text: str) -> dict[str, Any] | None:
    """Extract first JSON object from model output."""
    match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)?\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return None


class CandidateFilter:
    def __init__(self, campaign_dir: Path, config: dict[str, Any]) -> None:
        self.campaign_dir = campaign_dir
        self.config = config
        filter_cfg = config.get("filter", {})
        self.model = filter_cfg.get("model", "claude-sonnet-5")
        self.max_candidates = filter_cfg.get("max_candidates", 100)
        self.max_workers = max(1, int(filter_cfg.get("max_workers", 6)))

        criteria_path = campaign_dir / "input" / "filter_criteria.md"
        if not criteria_path.exists():
            raise FileNotFoundError(f"filter_criteria.md not found: {criteria_path}")
        self.criteria = criteria_path.read_text()

    def _call_model(self, prompt: str) -> dict[str, Any] | None:
        output = call_model_text(
            prompt=prompt,
            model=self.model,
            system=_SYSTEM_INSTRUCTIONS,
            timeout=120,
        )
        if not output:
            return None
        return _extract_json(output)

    def _review_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        summary = {
            "url": candidate.get("url"),
            "title": candidate.get("title"),
            "location": candidate.get("location"),
            "highlights": candidate.get("highlights"),
            "text_excerpt": (candidate.get("text") or "")[:3000],
        }

        prompt = _PROMPT_TEMPLATE.format(
            criteria=self.criteria,
            candidate_json=json.dumps(summary, indent=2, ensure_ascii=False),
        )

        review = self._call_model(prompt)
        if review is None:
            review = {
                "recommendation": "PENDING",
                "confidence": "LOW",
                "candidate_location": None,
                "candidate_job_title": None,
                "key_strength": None,
                "main_concern": "AI review failed — manual review required",
                "reasoning": "Model call failed or returned unparseable output.",
            }

        extracted_location = review.get("candidate_location")
        extracted_title = review.get("candidate_job_title")

        return {
            **candidate,
            "location": extracted_location or candidate.get("location") or "",
            "extracted_title": extracted_title or "",
            "ai_review": review,
        }

    def _load_all_candidates(self) -> list[dict[str, Any]]:
        data_dir = self.campaign_dir / "data"
        candidates: list[dict[str, Any]] = []
        for loc_dir in sorted(data_dir.iterdir()):
            raw_path = loc_dir / "raw_results.json"
            if not raw_path.exists():
                continue
            with open(raw_path) as f:
                candidates.extend(json.load(f))
        return candidates

    def run(self) -> list[dict[str, Any]]:
        all_candidates = self._load_all_candidates()

        # Sort by Exa relevance score and cap at max_candidates
        all_candidates.sort(key=lambda c: c.get("score") or 0, reverse=True)
        to_review = all_candidates[: self.max_candidates]
        skipped = all_candidates[self.max_candidates :]

        logger.info(
            "Reviewing %d candidates (cap=%d, skipped=%d)",
            len(to_review),
            self.max_candidates,
            len(skipped),
        )

        reviewed: list[dict[str, Any]] = []

        def _review_one(index: int, candidate: dict[str, Any]) -> tuple[int, dict[str, Any]]:
            label = candidate.get("title") or candidate.get("url", "?")
            logger.info("[%d/%d] %s", index + 1, len(to_review), label)
            return index, self._review_candidate(candidate)

        if to_review:
            workers = min(self.max_workers, len(to_review))
            logger.info("Running AI review in parallel with %d workers", workers)
            reviewed_by_index: dict[int, dict[str, Any]] = {}

            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(_review_one, idx, candidate): idx
                    for idx, candidate in enumerate(to_review)
                }
                for future in as_completed(futures):
                    idx, result = future.result()
                    reviewed_by_index[idx] = result

            reviewed = [reviewed_by_index[idx] for idx in sorted(reviewed_by_index)]

        # Candidates beyond cap get a PENDING placeholder (full data preserved)
        for candidate in skipped:
            reviewed.append(
                {
                    **candidate,
                    "ai_review": {
                        "recommendation": "PENDING",
                        "confidence": "LOW",
                        "key_strength": None,
                        "main_concern": "Not reviewed — beyond max_candidates cap",
                        "reasoning": "Candidate was not reviewed due to the max_candidates limit.",
                    },
                }
            )

        out_path = self.campaign_dir / "data" / "filtered_results.json"
        with open(out_path, "w") as f:
            json.dump(reviewed, f, indent=2, ensure_ascii=False)

        accepted = sum(1 for c in reviewed if c["ai_review"]["recommendation"] == "ACCEPT")
        rejected = sum(1 for c in reviewed if c["ai_review"]["recommendation"] == "REJECT")
        pending = sum(1 for c in reviewed if c["ai_review"]["recommendation"] == "PENDING")
        logger.info("Filter done: %d ACCEPT  %d REJECT  %d PENDING", accepted, rejected, pending)

        return reviewed
