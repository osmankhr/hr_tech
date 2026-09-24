"""Read transient candidate-pipeline progress without trusting campaign paths or payloads."""
from __future__ import annotations

import json
import os
import stat
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

STATUS_FILENAME = "pipeline_status.json"
MAX_STATUS_BYTES = 64 * 1024
PROGRESS_STALE_AFTER = timedelta(minutes=5)
PROGRESS_FUTURE_SKEW = timedelta(minutes=1)
_ALLOWED_FIELDS = (
    "phase",
    "label",
    "phases",
    "current",
    "total",
    "detail",
    "found",
    "updated_at",
)


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except (ValueError, OverflowError):
        return None
    try:
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def _non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if 0 <= parsed <= 1_000_000_000 else None


@contextmanager
def _open_campaign_data_dir(
    campaign_dir: str | Path,
    *,
    campaigns_root: str | Path,
):
    """Open the campaign's real data directory without following nested symlinks."""
    campaign_fd = None
    data_fd = None
    try:
        root = Path(campaigns_root).expanduser().resolve()
        campaign = Path(campaign_dir).expanduser().resolve()
        campaign.relative_to(root)
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        campaign_fd = os.open(campaign, directory_flags)
        data_fd = os.open("data", directory_flags, dir_fd=campaign_fd)
        yield data_fd
    finally:
        if data_fd is not None:
            os.close(data_fd)
        if campaign_fd is not None:
            os.close(campaign_fd)


def _read_status_bytes(data_fd: int) -> bytes | None:
    status_fd = None
    try:
        status_fd = os.open(
            STATUS_FILENAME,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=data_fd,
        )
        file_stat = os.fstat(status_fd)
        if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_size > MAX_STATUS_BYTES:
            return None

        chunks = []
        remaining = MAX_STATUS_BYTES + 1
        while remaining > 0:
            chunk = os.read(status_fd, min(8192, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        return content if len(content) <= MAX_STATUS_BYTES else None
    finally:
        if status_fd is not None:
            os.close(status_fd)


def read_pipeline_progress(
    campaign_dir: str | Path,
    *,
    campaigns_root: str | Path,
    run_started_at: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Return a safe, normalized status payload for the current run, if one exists."""
    try:
        with _open_campaign_data_dir(
            campaign_dir,
            campaigns_root=campaigns_root,
        ) as data_fd:
            content = _read_status_bytes(data_fd)
        if content is None:
            return None
        payload = json.loads(content.decode("utf-8"))
    except (OSError, ValueError, json.JSONDecodeError, TypeError, UnicodeDecodeError):
        return None

    if not isinstance(payload, dict):
        return None

    phase = payload.get("phase")
    updated_at = payload.get("updated_at")
    if not isinstance(phase, str) or not phase.strip() or len(phase) > 64:
        return None
    if not isinstance(updated_at, str) or _parse_timestamp(updated_at) is None:
        return None

    run_started = _parse_timestamp(run_started_at)
    status_updated = _parse_timestamp(updated_at)
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    else:
        current_time = current_time.astimezone(timezone.utc)

    if run_started and status_updated and status_updated < run_started:
        return None
    if status_updated and current_time - status_updated > PROGRESS_STALE_AFTER:
        return None
    if status_updated and status_updated - current_time > PROGRESS_FUTURE_SKEW:
        return None

    progress: dict[str, Any] = {
        "phase": phase.strip(),
        "updated_at": updated_at,
    }

    for field in ("label", "detail"):
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            progress[field] = value.strip()

    phases = payload.get("phases")
    if isinstance(phases, list):
        normalized_phases = [
            item.strip() for item in phases if isinstance(item, str) and item.strip()
        ]
        if normalized_phases:
            progress["phases"] = normalized_phases

    for field in ("current", "total", "found"):
        value = _non_negative_int(payload.get(field))
        if value is not None:
            progress[field] = value

    return {field: progress[field] for field in _ALLOWED_FIELDS if field in progress}


def clear_pipeline_progress(
    campaign_dir: str | Path,
    *,
    campaigns_root: str | Path,
) -> None:
    """Best-effort removal of a status file, restricted to the configured campaign root."""
    try:
        with _open_campaign_data_dir(
            campaign_dir,
            campaigns_root=campaigns_root,
        ) as data_fd:
            file_stat = os.stat(
                STATUS_FILENAME,
                dir_fd=data_fd,
                follow_symlinks=False,
            )
            if not stat.S_ISREG(file_stat.st_mode):
                return
            os.unlink(STATUS_FILENAME, dir_fd=data_fd)
    except (OSError, ValueError, TypeError):
        return


def attach_pipeline_progress(
    run: Mapping[str, Any],
    *,
    campaigns_root: str | Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Copy a serialized pipeline run and attach transient progress while it is running."""
    serialized = dict(run)
    serialized["progress"] = None
    if serialized.get("status") != "Running" or not serialized.get("campaign_dir"):
        return serialized

    serialized["progress"] = read_pipeline_progress(
        serialized["campaign_dir"],
        campaigns_root=campaigns_root,
        run_started_at=serialized.get("started_at"),
        now=now,
    )
    return serialized
