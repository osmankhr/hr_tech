"""Cross-campaign variant of typesafe_pilot_english_confidence.py.

Real data turned out to be heavily skewed HIGH within any single campaign (candidates applying
to Turkish tech roles are almost all English-fluent) -- there are zero LOW examples anywhere in
the system and only 22 MEDIUM examples total across all campaigns. Pool every MEDIUM example
system-wide plus a HIGH sample so the test actually has something to discriminate.
"""
from __future__ import annotations

import glob
import json
import os
import time

import requests
from dotenv import load_dotenv

from typesafe_pilot_english_confidence import CRITERIA, INSTRUCTIONS, LEVELS, ask_typesafe, candidate_state

load_dotenv()


def main() -> None:
    api_key = os.environ.get("TYPESAFE_API_KEY")
    if not api_key:
        raise SystemExit("TYPESAFE_API_KEY not set")

    medium = []
    high = []
    for f in glob.glob("campaigns/*/data/filtered_results.json"):
        for c in json.loads(open(f).read()):
            if c.get("english_confidence") == "MEDIUM":
                medium.append(c)
            elif c.get("english_confidence") == "HIGH" and len(high) < 20:
                high.append(c)

    sample = medium + high
    print(f"Testing {len(medium)} MEDIUM + {len(high)} HIGH = {len(sample)} candidates, pooled across all campaigns\n")

    agree = 0
    disagree = []
    total_latency = 0.0

    for c in sample:
        expected = c["english_confidence"]
        t0 = time.monotonic()
        result = ask_typesafe(api_key, candidate_state(c))
        elapsed = time.monotonic() - t0
        total_latency += elapsed

        answer = result["answers"]["english_confidence"]
        probs = answer["probabilities"]
        got = LEVELS[int(max(probs, key=lambda k: probs[k]))]

        status = "OK " if got == expected else "DIFF"
        print(f"[{status}] expected={expected:6} typesafe={got:6} (score={answer['score']:.2f}, probs={probs}, {elapsed*1000:.0f}ms)")

        if got == expected:
            agree += 1
        else:
            disagree.append({"expected": expected, "typesafe": got, "score": answer["score"], "url": c.get("url"), "text": (c.get("text") or "")[:150]})

    n = len(sample)
    print(f"\n--- Summary ---")
    print(f"Agreement: {agree}/{n} ({100*agree/n:.0f}%)")
    print(f"Avg latency: {total_latency/n*1000:.0f}ms per call")

    if disagree:
        print(f"\n--- Disagreements ({len(disagree)}) ---")
        for d in disagree:
            print(f"  expected={d['expected']}  typesafe={d['typesafe']} (score={d['score']:.2f})  {d['url']}")
            print(f"    text: {d['text']!r}")


if __name__ == "__main__":
    main()
