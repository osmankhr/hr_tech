"""Shared LLM provider selection for candidate_pool scripts.

Defaults to Claude CLI. Can switch to Copilot with environment variables or
auto-select based on known local git/GitHub account names.
"""
from __future__ import annotations

import logging
import os
import subprocess
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

COPILOT_FIXED_MODEL = "openai/gpt-5.3-codex"


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

    cmd = ["claude", "--print", "--model", model, "--tools", ""]
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
        return None

    if result.returncode != 0:
        logger.warning("claude CLI returned non-zero: %s", result.stderr[:200])

    return result.stdout
