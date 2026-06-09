"""AI-driven candidate filtering via Claude headless mode."""
from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SYSTEM_INSTRUCTIONS = """\
You are a recruitment assistant. Review the candidate profile against the provided \
criteria and respond ONLY with a valid JSON object — no markdown fences, no preamble.
"""

_PROMPT_TEMPLATE = """\
{system}

## Filtering Criteria

{criteria}

## Candidate Profile

{candidate_json}

## Instructions

Evaluate this candidate and return a JSON object with exactly these fields:
{{
  "recommendation": "ACCEPT" | "REJECT" | "PENDING",
  "confidence": "HIGH" | "MEDIUM" | "LOW",
  "key_strength": "<one sentence describing the strongest qualification>",
  "main_concern": "<one sentence describing the main gap, or null if none>",
  "reasoning": "<2-3 sentence explanation of the decision>"
}}
"""


def _extract_json(text: str) -> dict[str, Any] | None:
    """Extract first JSON object from claude output."""
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
        self.model = filter_cfg.get("model", "claude-sonnet-4-5")
        self.max_candidates = filter_cfg.get("max_candidates", 100)

        criteria_path = campaign_dir / "input" / "filter_criteria.md"
        if not criteria_path.exists():
            raise FileNotFoundError(f"filter_criteria.md not found: {criteria_path}")
        self.criteria = criteria_path.read_text()

    def _call_claude(self, prompt: str) -> dict[str, Any] | None:
        try:
            result = subprocess.run(
                ["claude", "--print", "--model", self.model],
                input=prompt,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except FileNotFoundError:
            logger.error("claude CLI not found — ensure Claude Code is installed and on PATH")
            return None
        except subprocess.TimeoutExpired:
            logger.warning("claude CLI timed out")
            return None

        if result.returncode != 0:
            logger.warning("claude CLI returned non-zero: %s", result.stderr[:200])

        return _extract_json(result.stdout)

    def _review_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        summary = {
            "url": candidate.get("url"),
            "title": candidate.get("title"),
            "location": candidate.get("location"),
            "highlights": candidate.get("highlights"),
            "text_excerpt": (candidate.get("text") or "")[:3000],
        }

        prompt = _PROMPT_TEMPLATE.format(
            system=_SYSTEM_INSTRUCTIONS,
            criteria=self.criteria,
            candidate_json=json.dumps(summary, indent=2, ensure_ascii=False),
        )

        review = self._call_claude(prompt)
        if review is None:
            review = {
                "recommendation": "PENDING",
                "confidence": "LOW",
                "key_strength": None,
                "main_concern": "AI review failed — manual review required",
                "reasoning": "Claude CLI call failed or returned unparseable output.",
            }

        return {**candidate, "ai_review": review}

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
        for i, candidate in enumerate(to_review, 1):
            label = candidate.get("title") or candidate.get("url", "?")
            logger.info("[%d/%d] %s", i, len(to_review), label)
            reviewed.append(self._review_candidate(candidate))

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
