"""Pilot: does TypeSafe's Choice question match filter.py's ACCEPT/REJECT/PENDING recommendation?

Standalone comparison script -- NOT wired into run_campaign.py. Loads a completed campaign's
filter_criteria.md + filtered_results.json, asks TypeSafe a Choice question with the same
criteria + candidate profile Claude saw, and diffs against Claude's actual recommendation.

Excludes candidates whose final recommendation was forced to REJECT by the ING-employer backstop
(already piloted separately in typesafe_pilot_ing_check.py) -- that's a different, already-tested
decision layered on top of this one, and including it here would conflate the two.

Usage:
    python scripts/typesafe_pilot_recommendation.py campaigns/<campaign_dir>
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

API_URL = "https://api.typesafe.ai/v1/systemone"
ING_RE = re.compile(r"\bing\b", re.IGNORECASE)

OPTIONS = ["ACCEPT", "REJECT", "PENDING"]

INSTRUCTIONS = (
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
CRITERIA = {
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


def candidate_state(criteria: str, candidate: dict) -> dict:
    return {
        "filtering_criteria": criteria,
        "candidate_profile": {
            "url": candidate.get("url"),
            "title": candidate.get("title"),
            "location": candidate.get("location"),
            "highlights": candidate.get("highlights"),
            "text_excerpt": (candidate.get("text") or "")[:3000],
        },
    }


def ask_typesafe(api_key: str, state: dict) -> dict:
    resp = requests.post(
        API_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "state": state,
            "model": "jev-latest",
            "questions": {
                "recommendation": {
                    "type": "choice",
                    "instructions": INSTRUCTIONS,
                    "criteria": CRITERIA,
                }
            },
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def is_ing_forced_reject(candidate: dict) -> bool:
    employer = candidate.get("ai_review", {}).get("candidate_current_employer") or ""
    return bool(ING_RE.search(employer)) and candidate.get("ai_review", {}).get("recommendation") == "REJECT"


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python typesafe_pilot_recommendation.py <campaign_dir>")

    api_key = os.environ.get("TYPESAFE_API_KEY")
    if not api_key:
        raise SystemExit("TYPESAFE_API_KEY not set (check candidate_pool/.env)")

    campaign_dir = Path(sys.argv[1])
    criteria = (campaign_dir / "input" / "filter_criteria.md").read_text(encoding="utf-8")
    candidates = json.loads((campaign_dir / "data" / "filtered_results.json").read_text(encoding="utf-8"))

    non_ing = [c for c in candidates if not is_ing_forced_reject(c)]
    # Exclude candidates Claude never actually reviewed (ran out of max_candidates budget, got a
    # synthetic PENDING stub) -- comparing TypeSafe's real judgment against a placeholder isn't a
    # real disagreement, it inflates the apparent PENDING mismatch rate for free.
    reviewed = [
        c for c in non_ing
        if "beyond max_candidates cap" not in (c.get("ai_review", {}).get("main_concern") or "")
    ]
    # Balance the sample across the three outcomes rather than taking them in original order.
    by_rec: dict[str, list[dict]] = {"ACCEPT": [], "REJECT": [], "PENDING": []}
    for c in reviewed:
        rec = c.get("ai_review", {}).get("recommendation")
        if rec in by_rec:
            by_rec[rec].append(c)
    sample = by_rec["ACCEPT"][:15] + by_rec["REJECT"][:15] + by_rec["PENDING"][:15]

    print(f"Testing {len(sample)} candidates from {campaign_dir.name} "
          f"({len(by_rec['ACCEPT'][:15])} ACCEPT, {len(by_rec['REJECT'][:15])} REJECT, {len(by_rec['PENDING'][:15])} PENDING)\n")

    agree = 0
    disagree = []
    confusion: dict[tuple[str, str], int] = {}
    total_latency = 0.0

    for c in sample:
        expected = c["ai_review"]["recommendation"]

        t0 = time.monotonic()
        result = ask_typesafe(api_key, candidate_state(criteria, c))
        elapsed = time.monotonic() - t0
        total_latency += elapsed

        answer = result["answers"]["recommendation"]
        got = answer["choice"]
        confusion[(expected, got)] = confusion.get((expected, got), 0) + 1

        status = "OK " if got == expected else "DIFF"
        print(f"[{status}] expected={expected:8} typesafe={got:8} (confidence={answer['confidence']:.2f}, {elapsed*1000:.0f}ms)")

        if got == expected:
            agree += 1
        else:
            disagree.append({
                "expected": expected, "typesafe": got, "probs": answer["probabilities"], "url": c.get("url"),
                "main_concern": c.get("ai_review", {}).get("main_concern"),
            })

    n = len(sample)
    print(f"\n--- Summary ---")
    print(f"Agreement: {agree}/{n} ({100*agree/n:.0f}%)")
    print(f"Avg latency: {total_latency/n*1000:.0f}ms per call")
    print(f"\nConfusion (expected -> typesafe): {confusion}")

    if disagree:
        print(f"\n--- Disagreements ({len(disagree)}) ---")
        for d in disagree:
            print(f"  expected={d['expected']}  typesafe={d['typesafe']}  probs={d['probs']}")
            print(f"    Claude's main_concern: {d['main_concern']!r}  {d['url']}")


if __name__ == "__main__":
    main()
