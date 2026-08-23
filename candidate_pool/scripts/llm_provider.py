"""Shared LLM provider selection for candidate_pool scripts.

Defaults to Claude CLI. Can switch to Copilot with environment variables or
auto-select based on known local git/GitHub account names.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

COPILOT_FIXED_MODEL = "openai/gpt-5.3-codex"

# Cost/token usage was previously not captured at all -- `claude --print` was called without
# --output-format json, so the CLI's cost/usage data was thrown away, not just unlogged. This
# accumulates it across every Claude CLI call in a pipeline run (filter.py, generate_queries.py,
# and the ranking agents all funnel through call_model_text). Thread-safe since filter.py and
# the ranking pipeline call this concurrently via ThreadPoolExecutor.
_usage_lock = threading.Lock()
_usage_totals: dict[str, Any] = {
    "calls": 0,
    "errors": 0,
    "input_tokens": 0,
    "output_tokens": 0,
    "cache_creation_input_tokens": 0,
    "cost_usd": 0.0,
    "duration_ms": 0,
}


def get_usage_summary() -> dict[str, Any]:
    """Return a snapshot of accumulated usage since the last reset_usage_summary()."""
    with _usage_lock:
        return dict(_usage_totals)


def reset_usage_summary() -> None:
    """Clear accumulated usage -- call at the start of a pipeline run for a clean per-run total."""
    with _usage_lock:
        for key in _usage_totals:
            _usage_totals[key] = 0 if not isinstance(_usage_totals[key], float) else 0.0


def _record_usage(usage_json: dict[str, Any]) -> None:
    usage = usage_json.get("usage") or {}
    with _usage_lock:
        _usage_totals["calls"] += 1
        _usage_totals["input_tokens"] += int(usage.get("input_tokens") or 0)
        _usage_totals["output_tokens"] += int(usage.get("output_tokens") or 0)
        _usage_totals["cache_creation_input_tokens"] += int(usage.get("cache_creation_input_tokens") or 0)
        _usage_totals["cost_usd"] += float(usage_json.get("total_cost_usd") or 0.0)
        _usage_totals["duration_ms"] += int(usage_json.get("duration_ms") or 0)


def _run_text(cmd: list[str], cwd: Path | None = None) -> str:
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=8,
            cwd=str(cwd) if cwd else None,
        )
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    return (result.stdout or "").strip()


@lru_cache(maxsize=1)
def _detect_git_user() -> str:
    """Detect current repo git user.name, if available."""
    here = Path(__file__).resolve().parent
    repo_root = here.parent
    return _run_text(["git", "config", "--get", "user.name"], cwd=repo_root)


@lru_cache(maxsize=1)
def _detect_logged_gh_users() -> set[str]:
    """Detect all gh accounts listed by `gh auth status -h github.com`."""
    out = _run_text(["gh", "auth", "status", "-h", "github.com"])
    if not out:
        return set()

    users: set[str] = set()
    lines = out.splitlines()
    for line in lines:
        marker = "Logged in to github.com account "
        if marker not in line:
            continue
        username = line.split(marker, 1)[1].split(" ", 1)[0].strip()
        if username:
            users.add(username)

    return users


def choose_provider() -> str:
    """Return one of: claude, copilot."""
    mode = os.environ.get("CANDIDATE_POOL_LLM_PROVIDER", "auto").strip().lower()
    if mode in {"claude", "copilot"}:
        return mode

    if mode not in {"", "auto"}:
        logger.warning(
            "Unknown CANDIDATE_POOL_LLM_PROVIDER=%r, falling back to auto",
            mode,
        )

    preferred_users = {
        part.strip()
        for part in os.environ.get(
            "CANDIDATE_POOL_COPILOT_USERS",
            "MG77XN_ingcp",
        ).split(",")
        if part.strip()
    }

    git_user = _detect_git_user()
    gh_users = _detect_logged_gh_users()

    if git_user in preferred_users or (preferred_users & gh_users):
        return "copilot"
    return "claude"


def call_model_text(*, prompt: str, model: str, system: str | None, timeout: int) -> str | None:
    """Call selected LLM provider and return raw text output."""
    provider = choose_provider()

    if provider == "copilot":
        try:
            from llm_client import CopilotClient  # type: ignore
        except Exception:
            logger.error(
                "Copilot provider selected but llm_client.CopilotClient is unavailable. "
                "Restore candidate_pool/scripts/llm_client.py or set CANDIDATE_POOL_LLM_PROVIDER=claude."
            )
            return None

        try:
            # Local Copilot runs always use a fixed model; campaign.yaml model stays unchanged.
            client = CopilotClient(model=COPILOT_FIXED_MODEL, timeout=timeout)
            return client.complete(system=system, user=prompt)
        except ValueError as e:
            logger.error("Copilot/GitHub Models config error: %s", e)
            return None
        except Exception:
            logger.exception("Copilot/GitHub Models call failed")
            return None

    cmd = ["claude", "--print", "--model", model, "--tools", "", "--output-format", "json"]
    if system:
        cmd += ["--system-prompt", system]

    try:
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        logger.error("claude CLI not found — ensure Claude Code is installed and on PATH")
        return None
    except subprocess.TimeoutExpired:
        logger.warning("claude CLI timed out")
        with _usage_lock:
            _usage_totals["errors"] += 1
        return None

    if result.returncode != 0:
        logger.warning("claude CLI returned non-zero: %s", result.stderr[:200])
        with _usage_lock:
            _usage_totals["errors"] += 1
        return None

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        # Unexpected CLI output shape (e.g. version mismatch) -- degrade to the raw stdout
        # rather than failing the whole call, but we lose usage data for this one call.
        logger.warning("claude CLI --output-format json did not return valid JSON; using raw stdout")
        return result.stdout

    if payload.get("is_error"):
        logger.warning("claude CLI reported an error result: %s", str(payload.get("result"))[:200])
        with _usage_lock:
            _usage_totals["errors"] += 1
        return None

    _record_usage(payload)
    usage = payload.get("usage") or {}
    logger.debug(
        "claude call: %.3fs, $%.4f, in=%d out=%d cache=%d",
        (payload.get("duration_ms") or 0) / 1000,
        payload.get("total_cost_usd") or 0.0,
        usage.get("input_tokens") or 0,
        usage.get("output_tokens") or 0,
        usage.get("cache_creation_input_tokens") or 0,
    )

    text_result = payload.get("result")
    return text_result if isinstance(text_result, str) else None
