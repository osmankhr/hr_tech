"""Pilot: does TypeSafe's Score question match filter.py's english_confidence field?

Standalone comparison script -- NOT wired into run_campaign.py. Loads a completed campaign's
filtered_results.json, re-runs the English-confidence judgment via a TypeSafe Score question on
the same candidate summary filter.py sends to Claude, and diffs the implied level (argmax over
the three levels) against Claude's existing english_confidence field. Changes nothing.

Usage:
    python scripts/typesafe_pilot_english_confidence.py campaigns/<campaign_dir>
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

API_URL = "https://api.typesafe.ai/v1/systemone"

LEVELS = ["LOW", "MEDIUM", "HIGH"]
CRITERIA = [
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

INSTRUCTIONS = (
    "Rate how confident you are that this candidate is proficient in English, based on the "
    "profile below. A short list of job titles and keywords is not enough on its own -- look for "
    "actual flowing prose, an explicit fluency/certification claim, or international history."
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
                "english_confidence": {
                    "type": "score",
                    "instructions": INSTRUCTIONS,
                    "criteria": CRITERIA,
                }
            },
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python typesafe_pilot_english_confidence.py <campaign_dir>")

    api_key = os.environ.get("TYPESAFE_API_KEY")
    if not api_key:
        raise SystemExit("TYPESAFE_API_KEY not set (check candidate_pool/.env)")

    campaign_dir = Path(sys.argv[1])
    candidates = json.loads((campaign_dir / "data" / "filtered_results.json").read_text(encoding="utf-8"))

    # english_confidence is only ever set on candidates that made it through a full review;
    # skip the rest so we're comparing against real Claude judgments, not nulls.
    sample = [c for c in candidates if c.get("english_confidence") in LEVELS][:40]
    print(f"Testing {len(sample)} candidates from {campaign_dir.name}\n")

    agree = 0
    disagree = []
    total_input_tokens = 0
    total_output_tokens = 0
    total_latency = 0.0

    for c in sample:
        expected = c["english_confidence"]

        t0 = time.monotonic()
        result = ask_typesafe(api_key, candidate_state(c))
        elapsed = time.monotonic() - t0
        total_latency += elapsed

        answer = result["answers"]["english_confidence"]
        probs = answer["probabilities"]
        got_idx = max(probs, key=lambda k: probs[k])
        got = LEVELS[int(got_idx)]
        usage = result.get("usage", {})
        total_input_tokens += usage.get("input_tokens", 0)
        total_output_tokens += usage.get("output_tokens", 0)

        status = "OK " if got == expected else "DIFF"
        print(
            f"[{status}] expected={expected:6} typesafe={got:6} "
            f"(score={answer['score']:.2f}, confidence={answer['confidence']:.2f}, {elapsed*1000:.0f}ms)"
        )

        if got == expected:
            agree += 1
        else:
            disagree.append({"expected": expected, "typesafe": got, "score": answer["score"], "url": c.get("url")})

    n = len(sample)
    if n == 0:
        print("No candidates with a set english_confidence found in this campaign.")
        return

    print(f"\n--- Summary ---")
    print(f"Agreement: {agree}/{n} ({100*agree/n:.0f}%)")
    print(f"Avg latency: {total_latency/n*1000:.0f}ms per call")
    est_cost = total_input_tokens / 1_000_000 * 0.042
    print(f"Tokens: {total_input_tokens} in / {total_output_tokens} out -- est. cost ${est_cost:.4f} for {n} calls")

    if disagree:
        print(f"\n--- Disagreements ({len(disagree)}) ---")
        for d in disagree:
            print(f"  expected={d['expected']}  typesafe={d['typesafe']} (score={d['score']:.2f})  {d['url']}")


if __name__ == "__main__":
    main()
