"""Claude-based relevance filter for new-author candidates.

The keyword search casts a wide net ("yapay zeka", "veri bilimi", etc.) and also catches theses
that apply AI/ML/statistical methods inside an unrelated field -- biology, medicine, education/
learning sciences, agriculture, and so on -- rather than theses by an actual ML/DS/AI
practitioner. This classifies each new author's thesis title(s) with Claude so those false
positives don't show up in the weekly email digest.

Fails open: if the Claude CLI call fails or its output can't be parsed, every author is kept
rather than silently dropped. A classifier outage should never look like "no false positives
today" -- worst case you review a few extra names by hand, same as before this filter existed.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-5"
TIMEOUT_SEC = 120

_SYSTEM_PROMPT = (
    "You screen Turkish university thesis authors for a data science / ML recruiting pipeline. "
    "Their titles were matched by AI/ML/data-science keywords, but many are false positives: AI "
    "or statistical methods applied within an unrelated field (biology, medicine, education / "
    "learning sciences, agriculture, social sciences, literature, etc.), not theses by an actual "
    "ML/DS/AI practitioner. Keep only authors whose thesis work centers on building or "
    "researching ML/DL/AI/data-science methods themselves -- not domain theses that merely use "
    "an off-the-shelf AI tool or model as an instrument."
)

_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.S)


def classify_new_authors(groups: list[dict]) -> dict[int, bool]:
    """Return {index: keep} for each entry in `groups` (each needs 'author' and 'titles').

    On any failure (CLI missing/timeout/non-zero exit, unparseable output), every index maps to
    True -- see module docstring for why this fails open rather than closed.
    """
    keep_all = {i: True for i in range(len(groups))}
    if not groups:
        return keep_all

    items = [
        {"index": i, "author": g["author"], "titles": g["titles"]}
        for i, g in enumerate(groups)
    ]
    prompt = (
        "Classify each of these authors as a genuine ML/DS/AI candidate (keep=true) or a false "
        "positive from an unrelated field (keep=false), based only on their thesis title(s).\n\n"
        + json.dumps(items, ensure_ascii=False, indent=2)
        + '\n\nRespond with ONLY a JSON array like '
        '[{"index": 0, "keep": true}, {"index": 1, "keep": false}], one entry per author, no prose.'
    )

    cmd = ["claude", "--print", "--model", MODEL, "--tools", "", "--output-format", "json",
           "--system-prompt", _SYSTEM_PROMPT]

    try:
        result = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True, timeout=TIMEOUT_SEC,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning("relevance filter: claude CLI unavailable (%s); keeping all authors", e)
        return keep_all

    if result.returncode != 0:
        logger.warning(
            "relevance filter: claude CLI failed (%s); keeping all authors",
            (result.stderr or "")[:200],
        )
        return keep_all

    try:
        payload = json.loads(result.stdout)
        text = payload.get("result", "") if isinstance(payload, dict) else result.stdout
    except json.JSONDecodeError:
        text = result.stdout

    m = _JSON_ARRAY_RE.search(text or "")
    if not m:
        logger.warning("relevance filter: no JSON array in claude output; keeping all authors")
        return keep_all

    try:
        decisions = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        logger.warning("relevance filter: could not parse claude output (%s); keeping all authors", e)
        return keep_all

    out = dict(keep_all)
    for d in decisions:
        idx = d.get("index") if isinstance(d, dict) else None
        if isinstance(idx, int) and idx in out:
            out[idx] = bool(d.get("keep", True))
    return out
