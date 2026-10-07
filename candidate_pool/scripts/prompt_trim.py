"""Helpers that shrink per-candidate LLM prompts/outputs without changing what the model is asked.

Measured on a real campaign (Turkish-heavy profiles, ~2.4 chars/token):
  * `highlights` averaged ~7k chars per candidate and ~70% of them were passages already present
    word-for-word in the `text_excerpt` sent in the same prompt.
  * ranking_feature_schema.json / ranking_scoring_policy.json carry a `raw_response` key -- a verbatim
    copy of the designer model's own output, ~46% of those two files -- that was being re-sent with
    every candidate scoring call.
  * Pretty-printed JSON (indent=2) is ~14% bigger than compact JSON.
  * Ranking calls wrote ~3.4k output tokens, mostly long evidence quotes and notes.

Each switch can be turned off independently with an environment variable (set to 0/false/off/no):
  CANDIDATE_POOL_TRIM_PROMPTS   input trimming: strip bookkeeping keys, compact JSON, dedupe highlights
  CANDIDATE_POOL_TERSE_OUTPUT   append short length limits to the ranking scorer prompt
  CANDIDATE_POOL_CLAUDE_EFFORT  `claude --effort` level for per-candidate calls (default "low";
                                set to "off" to use the CLI default). Claude CLI provider only.

Candidate caps (how many candidates get reviewed/ranked) also live here, since they are the biggest
cost lever: see resolve_max_candidates().
"""
from __future__ import annotations

import json
import os
from typing import Any

_OFF = {"0", "false", "off", "no", ""}

# Keys the schema/policy designers store for their own bookkeeping; the scorer never needs them.
BOOKKEEPING_KEYS = ("raw_response", "capabilities", "fallback")

HIGHLIGHT_MAX_ITEMS = 2
HIGHLIGHT_MAX_CHARS = 1500

TERSE_OUTPUT_SUFFIX = (
    "\n\nLength limits: for each feature give at most 2 evidence quotes of 12 words or fewer, "
    "notes of 20 words or fewer, and a summary of 30 words or fewer."
)


def _flag(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in _OFF


def trim_enabled() -> bool:
    return _flag("CANDIDATE_POOL_TRIM_PROMPTS")


def terse_output_enabled() -> bool:
    return _flag("CANDIDATE_POOL_TERSE_OUTPUT")


def candidate_effort() -> str | None:
    """`claude --effort` level for per-candidate calls, or None to use the CLI default."""
    raw = os.environ.get("CANDIDATE_POOL_CLAUDE_EFFORT", "low").strip().lower()
    return None if raw in _OFF else raw


def strip_bookkeeping(obj: Any) -> Any:
    """Drop designer bookkeeping keys from a schema/policy dict (top level only)."""
    if not trim_enabled() or not isinstance(obj, dict):
        return obj
    return {k: v for k, v in obj.items() if k not in BOOKKEEPING_KEYS}


def dumps(obj: Any) -> str:
    """JSON for prompts: compact when trimming is on, otherwise the original indent=2."""
    if trim_enabled():
        return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    return json.dumps(obj, indent=2, ensure_ascii=False)


def dedupe_highlights(highlights: Any, text_excerpt: str) -> Any:
    """Drop highlights that already appear in `text_excerpt`; cap what's left.

    A highlight counts as a duplicate when its first 60 characters occur in the excerpt. Highlights
    from later in the page (outside the excerpt) are kept, since they carry information the excerpt
    doesn't.
    """
    if not trim_enabled() or not isinstance(highlights, list):
        return highlights
    kept = [
        h[:HIGHLIGHT_MAX_CHARS]
        for h in highlights
        if isinstance(h, str) and h.strip() and h[:60] not in text_excerpt
    ]
    return kept[:HIGHLIGHT_MAX_ITEMS]


DEFAULT_MAX_CANDIDATES = 100


def resolve_max_candidates(raw: Any) -> int | None:
    """Turn a `max_candidates` config value into a cap, or None for "no cap".

    * missing/None  -> the default cap (CANDIDATE_POOL_DEFAULT_MAX_CANDIDATES, default 100), so a
                       campaign never silently reviews every candidate Exa returns
    * 0 / negative  -> no cap; an explicit opt-in to review and rank everything
    * N > 0         -> N
    """
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        try:
            return max(1, int(os.environ.get("CANDIDATE_POOL_DEFAULT_MAX_CANDIDATES", DEFAULT_MAX_CANDIDATES)))
        except ValueError:
            return DEFAULT_MAX_CANDIDATES
    value = int(raw)
    return value if value > 0 else None
