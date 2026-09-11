"""Shared LLM provider selection for candidate_pool scripts.

Defaults to Claude CLI (what the deployed server uses). Auto-switches to a developer-local CLI
when the machine's git/GitHub identity matches a known developer account, so local pipeline runs
don't bill the production Claude profiles. Any choice can be forced with
CANDIDATE_POOL_LLM_PROVIDER.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

COPILOT_FIXED_MODEL = "openai/gpt-5.3-codex"

# campaign.yaml's `model` keys name Claude models, so they're meaningless to Codex. ChatGPT-account
# login (as opposed to an API key) cannot use the `*-codex` model IDs the old CLI defaulted to —
# those 400 with "not supported when using Codex with a ChatGPT account." gpt-5.6-luna is the
# cheapest current ChatGPT-login model; override with CANDIDATE_POOL_CODEX_MODEL if needed.
CODEX_MODEL = os.environ.get("CANDIDATE_POOL_CODEX_MODEL", "gpt-5.6-luna").strip() or None

VALID_PROVIDERS = {"claude", "copilot", "codex"}

# Claude CLI profile fallback chain. Each profile is an isolated $HOME under
# n8n-data/claude-profiles/<name>/ (same profiles the n8n workflows use), each
# with its own `claude login` and subscription. Without a HOME override, the
# claude subprocess inherits this process's own ambient $HOME instead, which
# for hr-tech.service is Osman's personal login -- keeping ranking/filtering
# calls off that account and onto a dedicated profile is the point here.
# Tried in order; the first profile whose call succeeds wins.
CLAUDE_PROFILES_DIR = Path("/home/osman/n8n-data/claude-profiles")
CLAUDE_PROFILE_CHAIN = tuple(
    part.strip()
    for part in os.environ.get(
        "CANDIDATE_POOL_CLAUDE_PROFILES", "aiworkspacetr,richard"
    ).split(",")
    if part.strip()
)

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


@lru_cache(maxsize=1)
def _detect_local_identities() -> set[str]:
    """Every name that plausibly identifies whoever owns this checkout.

    Three sources because no single one is reliable: `user.name` is often unset (commits then
    get their author from a global config or the commit-time environment), `gh` isn't installed
    everywhere, and the last commit's author is the only signal that survives a machine with
    neither configured.
    """
    repo_root = Path(__file__).resolve().parent.parent

    identities = {
        _run_text(["git", "config", "--get", "user.name"], cwd=repo_root),
        _run_text(["git", "log", "-1", "--format=%an"], cwd=repo_root),
    }
    identities |= _detect_logged_gh_users()

    return {name for name in identities if name}


def _env_user_set(var_name: str, default: str) -> set[str]:
    return {
        part.strip()
        for part in os.environ.get(var_name, default).split(",")
        if part.strip()
    }


def choose_provider() -> str:
    """Return one of: claude, copilot, codex.

    Claude is the default because that's what the deployed server is set up for; a developer's
    own machine is detected by account name and routed to their local CLI instead.
    """
    mode = os.environ.get("CANDIDATE_POOL_LLM_PROVIDER", "auto").strip().lower()
    if mode in VALID_PROVIDERS:
        return mode

    if mode not in {"", "auto"}:
        logger.warning(
            "Unknown CANDIDATE_POOL_LLM_PROVIDER=%r, falling back to auto",
            mode,
        )

    identities = _detect_local_identities()

    codex_users = _env_user_set("CANDIDATE_POOL_CODEX_USERS", "yigit-can-ozkaya")
    if identities & codex_users:
        return "codex"

    # Copilot is no longer auto-selected for anyone (the ING account it was keyed to is out of
    # use); it stays reachable via CANDIDATE_POOL_LLM_PROVIDER=copilot, or by listing an account
    # in CANDIDATE_POOL_COPILOT_USERS.
    copilot_users = _env_user_set("CANDIDATE_POOL_COPILOT_USERS", "")
    if identities & copilot_users:
        return "copilot"

    return "claude"


def call_model_text(*, prompt: str, model: str, system: str | None, timeout: int) -> str | None:
    """Call selected LLM provider and return raw text output.

    Never raises: every caller (filter.py, generate_queries.py, the ranking agents) treats None
    as "this one candidate failed" and keeps the batch going.
    """
    provider = choose_provider()

    if provider == "codex":
        try:
            from llm_codex import CodexClient  # type: ignore
        except Exception:
            logger.error(
                "Codex provider selected but llm_codex.CodexClient is unavailable. "
                "Restore candidate_pool/scripts/llm_codex.py or set CANDIDATE_POOL_LLM_PROVIDER=claude."
            )
            return None

        started = time.monotonic()
        try:
            # Local Codex runs ignore campaign.yaml's Claude model name (see CODEX_MODEL).
            client = CodexClient(model=CODEX_MODEL, timeout=timeout)
            text = client.complete(system=system, user=prompt)
        except ValueError as e:
            logger.error("Codex CLI config error: %s", e)
            with _usage_lock:
                _usage_totals["errors"] += 1
            return None
        except Exception:
            logger.exception("Codex CLI call failed")
            with _usage_lock:
                _usage_totals["errors"] += 1
            return None

        usage = client.last_usage or {}
        _record_usage({
            "usage": {
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
                "cache_creation_input_tokens": usage.get("cached_input_tokens", 0),
            },
            # Codex bills against a subscription rather than per call, so there's no per-call
            # cost to accumulate here.
            "duration_ms": int((time.monotonic() - started) * 1000),
        })
        return text

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

    profiles = CLAUDE_PROFILE_CHAIN or (None,)
    for i, profile in enumerate(profiles):
        is_last = i == len(profiles) - 1
        profile_home = CLAUDE_PROFILES_DIR / profile if profile else None
        text_result, should_retry = _call_claude_cli(
            cmd, prompt=prompt, timeout=timeout, home=profile_home, profile_label=profile
        )
        if text_result is not None:
            return text_result
        if not should_retry or is_last:
            return None
        logger.warning(
            "claude profile %r failed, falling back to next profile in chain", profile
        )
    return None


def _call_claude_cli(
    cmd: list[str], *, prompt: str, timeout: int, home: Path | None, profile_label: str | None
) -> tuple[str | None, bool]:
    """Run one claude CLI attempt under an optional profile HOME.

    Returns (text_result, should_retry_next_profile). should_retry is True for
    failures worth falling back on (missing/broken profile, CLI error, non-zero
    exit, timeout) and False for the CLI simply not being installed at all,
    since switching HOME won't fix a missing binary.
    """
    env = dict(os.environ)
    if home is not None:
        env["HOME"] = str(home)

    try:
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except FileNotFoundError:
        logger.error("claude CLI not found — ensure Claude Code is installed and on PATH")
        return None, False
    except subprocess.TimeoutExpired:
        logger.warning("claude CLI timed out (profile=%s)", profile_label)
        with _usage_lock:
            _usage_totals["errors"] += 1
        return None, True

    if result.returncode != 0:
        logger.warning(
            "claude CLI returned non-zero (profile=%s): %s", profile_label, result.stderr[:200]
        )
        with _usage_lock:
            _usage_totals["errors"] += 1
        return None, True

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        # Unexpected CLI output shape (e.g. version mismatch) -- degrade to the raw stdout
        # rather than failing the whole call, but we lose usage data for this one call.
        logger.warning("claude CLI --output-format json did not return valid JSON; using raw stdout")
        return result.stdout, False

    if payload.get("is_error"):
        logger.warning(
            "claude CLI reported an error result (profile=%s): %s",
            profile_label,
            str(payload.get("result"))[:200],
        )
        with _usage_lock:
            _usage_totals["errors"] += 1
        return None, True

    _record_usage(payload)
    usage = payload.get("usage") or {}
    logger.debug(
        "claude call (profile=%s): %.3fs, $%.4f, in=%d out=%d cache=%d",
        profile_label,
        (payload.get("duration_ms") or 0) / 1000,
        payload.get("total_cost_usd") or 0.0,
        usage.get("input_tokens") or 0,
        usage.get("output_tokens") or 0,
        usage.get("cache_creation_input_tokens") or 0,
    )

    text_result = payload.get("result")
    return (text_result if isinstance(text_result, str) else None), False
