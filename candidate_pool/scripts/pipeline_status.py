"""Cross-process progress reporting for an in-flight campaign run.

The web backend launches `run_campaign.py` as an opaque subprocess and only learns the outcome
once it exits, so while a run is in flight the filesystem is the only channel back to the UI.
Each phase writes `data/pipeline_status.json`; the backend's SSE endpoint reads it so the
recruiter sees the stage that's actually running instead of an unqualified "this can take a few
minutes".

Nothing here may raise: progress reporting is cosmetic and must never take a run down with it.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

STATUS_FILENAME = "pipeline_status.json"

# Phase key -> what a recruiter (not an engineer) should see.
PHASE_LABELS = {
    "queries": "Generating search queries",
    "search": "Searching for candidate profiles",
    "filter": "AI reviewing candidates",
    "ranking": "Scoring and ranking candidates",
    "report": "Building shortlist report",
}


# The orchestrator declares the phase plan once; the per-item progress writes inside filter and
# ranking then carry it forward, so the UI's stepper doesn't blink out mid-phase. Same process
# throughout a run, so a module global is enough -- no need to re-read the file on every write.
_planned_phases: list[str] | None = None


def _status_path(campaign_dir: Path) -> Path:
    return Path(campaign_dir) / "data" / STATUS_FILENAME


def write(
    campaign_dir: Path,
    phase: str,
    *,
    current: int | None = None,
    total: int | None = None,
    detail: str | None = None,
    phases: list[str] | None = None,
) -> None:
    """Record the phase now running, optionally with an item count within it."""
    global _planned_phases
    if phases:
        _planned_phases = list(phases)

    payload: dict[str, Any] = {
        "phase": phase,
        "label": PHASE_LABELS.get(phase, phase),
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if current is not None:
        payload["current"] = int(current)
    if total is not None:
        payload["total"] = int(total)
    if detail:
        payload["detail"] = detail
    if _planned_phases:
        payload["phases"] = list(_planned_phases)

    path = _status_path(campaign_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Written via a temp file + atomic replace so the backend, which polls this on its own
        # schedule, can never read a half-written file.
        tmp_path = path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp_path, path)
    except Exception:
        logger.debug("Could not write pipeline status", exc_info=True)


def clear(campaign_dir: Path) -> None:
    """Drop the status file once the run is over, so a finished run reports no active phase."""
    global _planned_phases
    _planned_phases = None
    try:
        _status_path(campaign_dir).unlink(missing_ok=True)
    except Exception:
        logger.debug("Could not clear pipeline status", exc_info=True)
