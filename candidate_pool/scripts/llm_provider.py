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

VALID_PROVIDERS = {"openrouter", "claude", "copilot", "codex"}

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
        "CANDIDATE_POOL_CLAUDE_PROFILES", "richard"
    ).split(",")
    if part.strip()
)

# A profile whose login has expired fails every call, and each failed attempt burns ~6s before the
# chain falls through to the next profile. Once a call fails with an auth-looking error, skip that
# profile for a while instead of retrying it for every candidate in the run. Other failures
# (timeouts, rate/usage limits, bad output) are not cooled down: they may be transient per call.
_AUTH_COOLDOWN_SECONDS = 600
_AUTH_ERROR_MARKERS = (
    "failed to authenticate",
    "oauth session expired",
    "not logged in",
    "please run /login",
    "invalid api key",
)
_profile_cooldowns: dict[str, float] = {}
_cooldown_lock = threading.Lock()


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
    "openrouter_fallback_calls": 0,
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
        _openrouter_state.update(spent_usd=0.0, fallback_logged=False, budget_logged=False)


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
    """Return one of: openrouter, claude, copilot, codex.

    OpenRouter is only the primary provider when explicitly forced with
    CANDIDATE_POOL_LLM_PROVIDER=openrouter. With OPENROUTER_API_KEY set but no override it is just
    the fallback behind the Claude CLI profiles (see call_model_text), because the CLI profiles are
    flat-rate logins while OpenRouter bills per token. Otherwise a developer's own machine is
    detected by account name and routed to their local CLI.
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


# --- OpenRouter (pay-per-token) ------------------------------------------------------------------
# Used either as the explicit primary provider, or as a safety net when every Claude CLI profile
# fails (logged out, usage limit, ...), so a campaign degrades to "costs some dollars" instead of
# "every candidate silently lands in PENDING". A per-run spend guard keeps a prolonged CLI outage
# from turning into an unbounded bill.
_OPENROUTER_DEFAULT_BUDGET_USD = 5.0
_openrouter_state = {"spent_usd": 0.0, "fallback_logged": False, "budget_logged": False}


def _openrouter_fallback_enabled() -> bool:
    if os.environ.get("CANDIDATE_POOL_OPENROUTER_FALLBACK", "on").strip().lower() in {"0", "false", "off", "no"}:
        return False
    return bool((os.environ.get("OPENROUTER_API_KEY") or "").strip())


def _openrouter_budget_usd() -> float | None:
    """Max OpenRouter spend per process (one pipeline run). None = unlimited ("off")."""
    raw = os.environ.get("CANDIDATE_POOL_OPENROUTER_MAX_USD", "").strip().lower()
    if raw in {"off", "none", "unlimited"}:
        return None
    try:
        return float(raw) if raw else _OPENROUTER_DEFAULT_BUDGET_USD
    except ValueError:
        return _OPENROUTER_DEFAULT_BUDGET_USD


def _call_openrouter(*, prompt: str, model: str, system: str | None, timeout: int) -> str | None:
    budget = _openrouter_budget_usd()
    with _usage_lock:
        over_budget = budget is not None and _openrouter_state["spent_usd"] >= budget
        first_budget_log = over_budget and not _openrouter_state["budget_logged"]
        if first_budget_log:
            _openrouter_state["budget_logged"] = True
        if over_budget:
            _usage_totals["errors"] += 1
    if over_budget:
        if first_budget_log:
            logger.error(
                "OpenRouter spend guard: $%.2f spent this run (limit $%.2f, "
                "CANDIDATE_POOL_OPENROUTER_MAX_USD); further OpenRouter calls are skipped.",
                _openrouter_state["spent_usd"],
                budget,
            )
        return None

    try:
        from llm_openrouter import OpenRouterClient  # type: ignore
    except Exception:
        logger.error("OpenRouter requested but llm_openrouter.OpenRouterClient is unavailable.")
        return None

    started = time.monotonic()
    try:
        target_model = (
            os.environ.get("OPENROUTER_MODEL")
            or os.environ.get("CANDIDATE_POOL_OPENROUTER_MODEL")
            or model
        )
        client = OpenRouterClient(model=target_model, timeout=timeout)
        text = client.complete(system=system, user=prompt)
    except ValueError as e:
        logger.error("OpenRouter config error: %s", e)
        with _usage_lock:
            _usage_totals["errors"] += 1
        return None
    except Exception:
        logger.exception("OpenRouter call failed")
        with _usage_lock:
            _usage_totals["errors"] += 1
        return None

    usage = client.last_usage or {}
    cost = float(usage.get("total_cost", 0.0) or 0.0)
    with _usage_lock:
        _openrouter_state["spent_usd"] += cost
    _record_usage({
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
            "cache_creation_input_tokens": usage.get("cached_tokens", 0),
        },
        "total_cost_usd": cost,
        "duration_ms": int((time.monotonic() - started) * 1000),
    })
    return text


def _claude_with_openrouter_fallback(
    cmd: list[str], *, prompt: str, model: str, system: str | None, timeout: int
) -> str | None:
    text = _call_claude_chain(cmd, prompt=prompt, timeout=timeout)
    if text is not None or not _openrouter_fallback_enabled():
        return text
    with _usage_lock:
        _usage_totals["openrouter_fallback_calls"] = _usage_totals.get("openrouter_fallback_calls", 0) + 1
        first = not _openrouter_state["fallback_logged"]
        _openrouter_state["fallback_logged"] = True
    if first:
        logger.warning(
            "All Claude CLI profiles failed; falling back to OpenRouter (billed per token, "
            "run limit $%s). Further fallbacks this run are not logged individually.",
            _openrouter_budget_usd(),
        )
    return _call_openrouter(prompt=prompt, model=model, system=system, timeout=timeout)


def _call_claude_chain(cmd: list[str], *, prompt: str, timeout: int) -> str | None:
    profiles = _active_profiles(CLAUDE_PROFILE_CHAIN or (None,))
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


def call_model_text(
    *, prompt: str, model: str, system: str | None, timeout: int, effort: str | None = None
) -> str | None:
    """Call selected LLM provider and return raw text output.

    Never raises: every caller (filter.py, generate_queries.py, the ranking agents) treats None
    as "this one candidate failed" and keeps the batch going.

    `effort` is passed to `claude --effort` (Claude CLI provider only; other providers ignore it).
    """
    provider = choose_provider()

    if provider == "openrouter":
        return _call_openrouter(prompt=prompt, model=model, system=system, timeout=timeout)

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
    if effort:
        cmd += ["--effort", effort]

    return _claude_with_openrouter_fallback(
        cmd, prompt=prompt, model=model, system=system, timeout=timeout
    )


def _active_profiles(profiles: tuple[str | None, ...]) -> tuple[str | None, ...]:
    """Drop profiles currently cooling down after an auth failure.

    If every profile is cooling down, return the full chain unchanged so a call still gets tried
    (e.g. someone just re-ran `claude login` and the cooldown hasn't expired yet).
    """
    now = time.monotonic()
    with _cooldown_lock:
        live = tuple(p for p in profiles if _profile_cooldowns.get(p or "", 0.0) <= now)
    return live or profiles


def _cli_error_text(result: subprocess.CompletedProcess) -> str:
    """Best available error text from a failed `claude --print --output-format json` run.

    The CLI reports failures as a JSON payload on *stdout* (is_error/result) and usually leaves
    stderr empty, so logging stderr alone produced blank warnings.
    """
    try:
        payload = json.loads(result.stdout)
        if isinstance(payload, dict) and payload.get("result"):
            return str(payload["result"])
    except (json.JSONDecodeError, TypeError):
        pass
    return (result.stderr or result.stdout or "").strip()


def _note_cli_failure(profile_label: str | None, error_text: str) -> None:
    """Count the error and cool the profile down if the failure looks like an expired login."""
    with _usage_lock:
        _usage_totals["errors"] += 1
    lowered = error_text.lower()
    if profile_label and any(marker in lowered for marker in _AUTH_ERROR_MARKERS):
        with _cooldown_lock:
            already = _profile_cooldowns.get(profile_label, 0.0) > time.monotonic()
            _profile_cooldowns[profile_label] = time.monotonic() + _AUTH_COOLDOWN_SECONDS
        if not already:
            logger.error(
                "claude profile %r looks logged out (%s); skipping it for %d min. "
                "Re-run `claude login` with HOME=%s",
                profile_label,
                error_text[:120],
                _AUTH_COOLDOWN_SECONDS // 60,
                CLAUDE_PROFILES_DIR / profile_label,
            )


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
        error_text = _cli_error_text(result)
        logger.warning(
            "claude CLI returned non-zero (profile=%s): %s", profile_label, error_text[:300]
        )
        _note_cli_failure(profile_label, error_text)
        return None, True

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        # Unexpected CLI output shape (e.g. version mismatch) -- degrade to the raw stdout
        # rather than failing the whole call, but we lose usage data for this one call.
        logger.warning("claude CLI --output-format json did not return valid JSON; using raw stdout")
        return result.stdout, False

    if payload.get("is_error"):
        error_text = str(payload.get("result"))
        logger.warning(
            "claude CLI reported an error result (profile=%s): %s", profile_label, error_text[:300]
        )
        _note_cli_failure(profile_label, error_text)
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
