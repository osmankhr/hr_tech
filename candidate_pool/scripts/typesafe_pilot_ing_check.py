"""Pilot: does TypeSafe's Noul question match filter.py's ING-employer check?

Standalone comparison script -- NOT wired into run_campaign.py. Loads a completed campaign's
filtered_results.json, re-runs the "is this candidate currently at ING" decision via the
TypeSafe API on the same candidate summary filter.py already sends to Claude, and compares the
result against the current pipeline's actual decision (Claude's own extraction + the _is_ing_employer
regex backstop in filter.py). Prints agreement/disagreement plus cost/latency, changes nothing.

Usage:
    python scripts/typesafe_pilot_ing_check.py campaigns/<campaign_dir>
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

QUESTION_INSTRUCTIONS = (
    "Is this candidate CURRENTLY employed at ING or a clear ING entity (e.g. 'ING Bank', "
    "'ING Hubs', 'ING Hubs Türkiye/Turkey', 'ING Groep', 'ING Direct', or any other obvious "
    "ING subsidiary/brand)? Answer no for companies that merely contain the letters 'ing' as "
    "part of an unrelated word or name (e.g. Consulting, Engineering, Marketing, Wingie, Turing)."
)


def candidate_state(candidate: dict) -> dict:
    return {
        "url": candidate.get("url"),
        "title": candidate.get("title"),
        "location": candidate.get("location"),
        "highlights": candidate.get("highlights"),
        "text_excerpt": (candidate.get("text") or "")[:3000],
    }


def ask_typesafe(api_key: str, state: dict) -> dict:
    resp = requests.post(
        API_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "state": state,
            "model": "jev-latest",
            "questions": {
                "is_ing_employee": {
                    "type": "noul",
                    "instructions": QUESTION_INSTRUCTIONS,
                }
            },
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def current_pipeline_verdict(candidate: dict) -> bool:
    """What filter.py's existing regex backstop would decide, given Claude's own extraction."""
    employer = candidate.get("ai_review", {}).get("candidate_current_employer")
    return bool(ING_RE.search(employer or ""))


def pick_sample(candidates: list[dict], limit: int = 35) -> list[dict]:
    true_ing = [c for c in candidates if current_pipeline_verdict(c)]
    substring_false_positives = [
        c for c in candidates
        if "ing" in str(c.get("ai_review", {}).get("candidate_current_employer", "")).lower()
        and not current_pipeline_verdict(c)
    ]
    others = [c for c in candidates if c not in true_ing and c not in substring_false_positives]
    sample = true_ing + substring_false_positives + others[:10]
    return sample[:limit]


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python typesafe_pilot_ing_check.py <campaign_dir>")

    api_key = os.environ.get("TYPESAFE_API_KEY")
    if not api_key:
        raise SystemExit("TYPESAFE_API_KEY not set (check candidate_pool/.env)")

    campaign_dir = Path(sys.argv[1])
    filtered_path = campaign_dir / "data" / "filtered_results.json"
    candidates = json.loads(filtered_path.read_text(encoding="utf-8"))

    sample = pick_sample(candidates)
    print(f"Testing {len(sample)} candidates from {campaign_dir.name}\n")

    agree = 0
    disagree = []
    total_input_tokens = 0
    total_output_tokens = 0
    total_latency = 0.0

    for c in sample:
        expected = current_pipeline_verdict(c)
        employer = c.get("ai_review", {}).get("candidate_current_employer") or "(none extracted)"

        t0 = time.monotonic()
        result = ask_typesafe(api_key, candidate_state(c))
        elapsed = time.monotonic() - t0
        total_latency += elapsed

        noul = result["answers"]["is_ing_employee"]["noul"]
        got = noul >= 0.5
        usage = result.get("usage", {})
        total_input_tokens += usage.get("input_tokens", 0)
        total_output_tokens += usage.get("output_tokens", 0)

        status = "OK " if got == expected else "DIFF"
        print(f"[{status}] expected={expected!s:5} typesafe={got!s:5} (p={noul:.2f}, {elapsed*1000:.0f}ms)  employer={employer!r}")

        if got == expected:
            agree += 1
        else:
            disagree.append({"employer": employer, "expected": expected, "typesafe_p": noul, "url": c.get("url")})

    n = len(sample)
    print(f"\n--- Summary ---")
    print(f"Agreement: {agree}/{n} ({100*agree/n:.0f}%)")
    print(f"Avg latency: {total_latency/n*1000:.0f}ms per call")
    est_cost = total_input_tokens / 1_000_000 * 0.042  # output is free per TypeSafe pricing
    print(f"Tokens: {total_input_tokens} in / {total_output_tokens} out -- est. cost ${est_cost:.4f} for {n} calls")

    if disagree:
        print(f"\n--- Disagreements ({len(disagree)}) ---")
        for d in disagree:
            print(f"  employer={d['employer']!r}  expected={d['expected']}  typesafe_p={d['typesafe_p']:.2f}  {d['url']}")


if __name__ == "__main__":
    main()
