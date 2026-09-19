"""AI-driven candidate filtering via Claude headless mode."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import pipeline_status
from llm_provider import call_model_text
from typesafe_client import ask_choice, ask_noul, ask_score

logger = logging.getLogger(__name__)

# PENDING is correct for production: a failed review still needs a human look before a real
# candidate gets dropped. Set to "reject" for fast local iteration (e.g. testing against a
# flaky/rate-limited local model) where auto-rejecting failed calls is a bigger productivity win
# than the false rejections it introduces. Never set to "reject" on the deployed server.
_FAIL_MODE = os.environ.get("CANDIDATE_POOL_FAIL_MODE", "pending").strip().lower()
if _FAIL_MODE not in {"pending", "reject"}:
    logger.warning("Unknown CANDIDATE_POOL_FAIL_MODE=%r; defaulting to 'pending'", _FAIL_MODE)
    _FAIL_MODE = "pending"

# Set to disable the TypeSafe/Jev ING-employer check and revert to the original
# regex-on-Claude's-extraction-only behavior -- e.g. if TypeSafe has an outage/incident, or the
# key gets revoked, or its judgment ever looks wrong on a real campaign. Validated 2026-09-19
# against a real campaign's ING-employer decisions: 33/33 agreement (see
# typesafe_pilot_ing_check.py). Even when enabled, any single failed TypeSafe call falls back to
# the regex check automatically -- this flag is for turning it off entirely, not per-call retry.
_TYPESAFE_ING_CHECK_DISABLED = os.environ.get(
    "CANDIDATE_POOL_DISABLE_TYPESAFE_ING_CHECK", ""
).strip().lower() in {"1", "true", "yes"}

_ING_CHECK_INSTRUCTIONS = (
    "Is this candidate CURRENTLY employed at ING or a clear ING entity (e.g. 'ING Bank', "
    "'ING Hubs', 'ING Hubs Türkiye/Turkey', 'ING Groep', 'ING Direct', or any other obvious "
    "ING subsidiary/brand)? Answer no for companies that merely contain the letters 'ing' as "
    "part of an unrelated word or name (e.g. Consulting, Engineering, Marketing, Wingie, Turing)."
)

# Set to disable the TypeSafe/Jev english_confidence rating and always use Claude's own rating
# instead. Validated 2026-09-19 against every MEDIUM example in the system plus a HIGH sample
# (42 candidates pooled across all campaigns) through three prompt iterations -- see
# typesafe_pilot_english_confidence.py: 81% agreement (90% on HIGH, 73% on MEDIUM), the best of
# three tries. english_confidence is a soft display signal only (never affects
# ACCEPT/REJECT/PENDING), so this bar is intentionally lower than the ING check's. Any single
# failed TypeSafe call falls back to Claude's own rating automatically -- this flag is for
# turning it off entirely, not per-call retry.
_TYPESAFE_ENGLISH_CHECK_DISABLED = os.environ.get(
    "CANDIDATE_POOL_DISABLE_TYPESAFE_ENGLISH_CHECK", ""
).strip().lower() in {"1", "true", "yes"}

_ENGLISH_CONFIDENCE_LEVELS = ["LOW", "MEDIUM", "HIGH"]
_ENGLISH_CONFIDENCE_CRITERIA = [
    "LOW: profile is entirely in another language with no English or international signals at all.",
    "MEDIUM: the 'About' section (or equivalent) is short, telegraphic, or keyword/bullet-list style "
    "-- e.g. a string of job titles, tech keywords, or sentence fragments -- even if grammatically "
    "fine. This is extremely common on LinkedIn regardless of true fluency (many people write "
    "minimal, list-style summaries), so it's weak evidence on its own. Also default here whenever "
    "signals are mixed, weak, or you're genuinely unsure.",
    "HIGH: either (a) multiple complete, well-constructed English sentences forming actual flowing "
    "prose -- not just a title/keyword list -- that demonstrate real command of the language on "
    "their own, even without external credentials; or (b) an explicit English proficiency/"
    "certification claim (IELTS/TOEFL, 'fluent in English'); or (c) concrete international study/"
    "work history (foreign university, employer headquartered abroad, international team).",
]
_ENGLISH_CONFIDENCE_INSTRUCTIONS = (
    "Rate how confident you are that this candidate is proficient in English, based on the "
    "profile below. A short list of job titles and keywords is not enough on its own -- look for "
    "actual flowing prose, an explicit fluency/certification claim, or international history."
)

# Opt-in, unlike the two flags above -- this one defaults OFF. Validated 2026-09-19 across three
# prompt iterations against 35-36 candidates (data-ai-chapter-lead-engineer_20260826_070714, all
# three ACCEPT/REJECT/PENDING outcomes): best result was 81% agreement with REJECT at 100%, but
# ACCEPT dropped to 67% as a direct tradeoff -- Claude gives some candidates credit for *leading*
# ML initiatives without hands-on coding, a nuance this prompt deliberately excludes to avoid
# false ACCEPTs, and that tradeoff didn't resolve cleanly after three tries (see
# typesafe_pilot_recommendation.py for the full history). Given this drives the actual
# ACCEPT/REJECT/PENDING decision -- the highest-stakes of the three checks -- production stays on
# Claude alone unless this is explicitly turned on for further testing.
_TYPESAFE_RECOMMENDATION_ENABLED = os.environ.get(
    "CANDIDATE_POOL_ENABLE_TYPESAFE_RECOMMENDATION", ""
).strip().lower() in {"1", "true", "yes"}

_RECOMMENDATION_INSTRUCTIONS = (
    "Decide whether this candidate should be accepted, rejected, or marked pending for the role "
    "described in the filtering criteria, based on the candidate profile. Both are given in the "
    "state. If the criteria include a location requirement, treat it as a hard requirement: only "
    "choose ACCEPT when the candidate's real location clearly and unambiguously satisfies it. "
    "Watch specifically for CONFLICTING location signals -- e.g. a profile header naming one city "
    "while the current employer and recent role history are all listed in a different city or "
    "country. That conflict means the real current location cannot be determined, even though "
    "the profile mentions a location -- choose PENDING in that case, not a guess at which signal "
    "to trust. Only choose REJECT when the location is clearly and consistently stated and it "
    "does not satisfy the requirement. Never resolve a genuine conflict by picking a side. "
    "\n\nWhen a criterion asks for a 'strong background' or 'foundation' in a specific technical "
    "discipline (e.g. ML, not just adjacent/supporting work), read it strictly: working with data "
    "pipelines, ETL, data platforms/warehousing, or applying a pre-built GenAI/RAG/LLM tool as an "
    "end user does NOT by itself demonstrate a strong foundation in that discipline. Look "
    "specifically for hands-on model building, training, evaluation, or algorithm design/research "
    "experience in that discipline. A candidate whose real substance is adjacent-but-different "
    "work should be REJECTed for that criterion, not ACCEPTed on the assumption that adjacent "
    "experience is close enough."
)
_RECOMMENDATION_CRITERIA = {
    "ACCEPT": "Candidate satisfies the Accept criteria and any hard requirements are clearly, "
    "unambiguously met -- no conflicting signals about them.",
    "REJECT": "Candidate clearly and consistently fails a hard requirement (no conflicting signals "
    "about it), or matches a Reject condition in the criteria.",
    "PENDING": "A hard requirement can't be determined from the profile text, OR there are "
    "conflicting signals about it (e.g. the profile header states one location but the person's "
    "actual employer/role history points to a different one) -- don't guess which signal to "
    "trust, mark it PENDING. Also use this when there isn't enough information to confidently "
    "decide either way on a non-hard-requirement criterion.",
}

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

First, determine the candidate's real current location, real current job title, and real \
current employer strictly from the profile text/highlights above (ignore any "location" value \
already attached to the profile — that value reflects which search bucket the record was pulled \
from, not a verified fact). If the profile text does not state a location, title, or employer \
clearly, use null.

If the Filtering Criteria include a location requirement, treat it as a hard requirement: only \
recommend ACCEPT when the candidate's real location (as you just determined it) clearly satisfies \
it. If the real location clearly does not satisfy it, recommend REJECT and say so in main_concern. \
If the location cannot be determined from the profile text, recommend PENDING (not ACCEPT) so a \
human can verify.

Standing hard rule, independent of the Filtering Criteria above: this search is run by ING \
recruiters to find candidates from OUTSIDE the company, so a candidate whose real current \
employer is ING or a clear ING entity (e.g. "ING Bank", "ING Hubs", "ING Hubs Türkiye/Turkey", \
"ING Groep", "ING Direct", or any other obvious ING subsidiary/brand — not just companies whose \
name happens to contain the letters "ing", like consulting or engineering firms) must always be \
recommended REJECT, with main_concern noting the candidate currently works at ING. This applies \
even if the candidate otherwise matches the role well.

Also assess an English Language Confidence signal — a SOFT risk signal only, never a reason by \
itself to REJECT or lower confidence. Base it strictly on what's observable in the profile: \
whether the profile text itself is written in English vs. entirely in another language, explicit \
mentions of English proficiency/certifications (e.g. IELTS/TOEFL scores, "fluent in English"), \
and any international study or work history (foreign university, employer headquartered abroad, \
international team). Rate "HIGH" when there's clear positive evidence (profile itself in fluent \
English, explicit certification/fluency claim, or international study/work history), "LOW" when \
the profile is entirely in another language with no English or international signals at all, and \
"MEDIUM" when signals are mixed or absent either way (absence of evidence is not evidence of low \
English — default to MEDIUM, not LOW, when you simply don't know).

Evaluate this candidate and return a JSON object with exactly these fields:
{{
  "recommendation": "ACCEPT" | "REJECT" | "PENDING",
  "confidence": "HIGH" | "MEDIUM" | "LOW",
  "candidate_location": "<candidate's real current location as stated in their profile text, or null>",
  "candidate_job_title": "<candidate's real current job title as stated in their profile text, or null>",
  "candidate_current_employer": "<candidate's real current employer as stated in their profile text, or null>",
  "english_confidence": "HIGH" | "MEDIUM" | "LOW",
  "english_confidence_reason": "<one short phrase citing the specific evidence observed, e.g. 'profile written in English, mentions international MBA'>",
  "key_strength": "<one sentence describing the strongest qualification>",
  "main_concern": "<one sentence describing the main gap, or null if none>",
  "reasoning": "<2-3 sentence explanation of the decision>"
}}
"""

_ING_EMPLOYER_PATTERN = re.compile(r"\bing\b", re.IGNORECASE)


def _is_ing_employer(employer: str | None) -> bool:
    """Detect ING/ING-entity employers via a whole-word match on 'ING'.

    Word-boundary matching avoids false positives on unrelated words that merely
    contain the letters "ing" (consulting, engineering, marketing, banking, ...),
    since "ing" never appears as its own word inside those.
    """
    if not employer:
        return False
    return bool(_ING_EMPLOYER_PATTERN.search(employer))


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
        # Filter calls are I/O-bound (waiting on the model), so concurrency scales close to
        # linearly. This stage measured as ~60% of total pipeline wall-clock time on real
        # campaigns at the old default of 6 workers, while ranking (default ~50 workers) barely
        # registers despite doing comparable work — raising this to match is the direct fix.
        self.max_workers = max(1, int(filter_cfg.get("max_workers", 20)))

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
            recommendation = "REJECT" if _FAIL_MODE == "reject" else "PENDING"
            main_concern = (
                "AI review failed — rejected unreviewed" if _FAIL_MODE == "reject"
                else "AI review failed — manual review required"
            )
            review = {
                "recommendation": recommendation,
                "confidence": "LOW",
                "candidate_location": None,
                "candidate_job_title": None,
                "candidate_current_employer": None,
                "english_confidence": "MEDIUM",
                "english_confidence_reason": None,
                "key_strength": None,
                "main_concern": main_concern,
                "reasoning": "Model call failed or returned unparseable output.",
            }

        extracted_location = review.get("candidate_location")
        extracted_title = review.get("candidate_job_title")
        extracted_employer = review.get("candidate_current_employer")
        english_confidence = str(review.get("english_confidence") or "MEDIUM").upper()
        if english_confidence not in {"LOW", "MEDIUM", "HIGH"}:
            english_confidence = "MEDIUM"

        # english_confidence rating: ask TypeSafe directly from the same profile summary Claude
        # saw. Falls back to Claude's own rating (computed above) if TypeSafe is disabled or the
        # call fails for any reason -- never blocks on TypeSafe.
        if not _TYPESAFE_ENGLISH_CHECK_DISABLED:
            level_idx = ask_score(summary, _ENGLISH_CONFIDENCE_INSTRUCTIONS, _ENGLISH_CONFIDENCE_CRITERIA)
            if level_idx is not None:
                english_confidence = _ENGLISH_CONFIDENCE_LEVELS[level_idx]

        # ACCEPT/REJECT/PENDING recommendation: opt-in only (see _TYPESAFE_RECOMMENDATION_ENABLED
        # above for why) -- disabled by default, so this block is a no-op in production until
        # explicitly turned on. When enabled, a successful TypeSafe call replaces Claude's
        # recommendation entirely; a failed call leaves Claude's recommendation untouched. The
        # ING-employer backstop below still applies on top regardless of which one decided.
        if _TYPESAFE_RECOMMENDATION_ENABLED:
            choice = ask_choice(
                {"filtering_criteria": self.criteria, "candidate_profile": summary},
                _RECOMMENDATION_INSTRUCTIONS,
                _RECOMMENDATION_CRITERIA,
            )
            if choice in {"ACCEPT", "REJECT", "PENDING"}:
                review = {**review, "recommendation": choice}

        # ING-employer check: ask TypeSafe directly from the same profile summary Claude saw
        # (not just a regex over Claude's own extraction), so a candidate Claude mis-extracted or
        # never flagged still gets caught. Falls back to the original regex-on-extraction check if
        # TypeSafe is disabled or the call fails for any reason -- never blocks on TypeSafe.
        is_ing = None
        if not _TYPESAFE_ING_CHECK_DISABLED:
            noul = ask_noul(summary, _ING_CHECK_INSTRUCTIONS)
            if noul is not None:
                is_ing = noul >= 0.5
        if is_ing is None:
            is_ing = _is_ing_employer(extracted_employer)

        if is_ing and review.get("recommendation") != "REJECT":
            review = {
                **review,
                "recommendation": "REJECT",
                "main_concern": f"Candidate's current employer ({extracted_employer or 'unknown'}) appears to be ING.",
            }

        return {
            **candidate,
            "location": extracted_location or candidate.get("location") or "",
            "extracted_title": extracted_title or "",
            "extracted_employer": extracted_employer or "",
            "english_confidence": english_confidence,
            "english_confidence_reason": str(review.get("english_confidence_reason") or ""),
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

        # Cap max_candidates per search location (search_bucket), not once across every
        # location's candidates pooled together. A shared global cap meant adding more
        # locations to a campaign silently shrank how many candidates from any single
        # location got reviewed — e.g. a 2-location "global" run (Turkey + US) could end up
        # reviewing fewer Turkey candidates than a Turkey-only run with the same
        # max_candidates value, since Turkey and US candidates competed for the same shared
        # budget on raw Exa relevance score. Capping per bucket means adding a location only
        # adds coverage, it never steals budget from an existing one.
        by_bucket: dict[str, list[dict[str, Any]]] = {}
        for candidate in all_candidates:
            bucket = candidate.get("search_bucket") or "unknown"
            by_bucket.setdefault(bucket, []).append(candidate)

        to_review: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for bucket_candidates in by_bucket.values():
            bucket_candidates.sort(key=lambda c: c.get("score") or 0, reverse=True)
            to_review.extend(bucket_candidates[: self.max_candidates])
            skipped.extend(bucket_candidates[self.max_candidates :])

        logger.info(
            "Reviewing %d candidates across %d location(s) (cap=%d per location, skipped=%d)",
            len(to_review),
            len(by_bucket),
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
                # Counted here in the collecting thread rather than inside _review_one, so the
                # status file has a single writer despite the pool.
                for done, future in enumerate(as_completed(futures), 1):
                    idx, result = future.result()
                    reviewed_by_index[idx] = result
                    pipeline_status.write(
                        self.campaign_dir, "filter", current=done, total=len(to_review)
                    )

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
