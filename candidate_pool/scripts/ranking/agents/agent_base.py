"""Shared agent wrapper for Claude-powered JSON responses."""
from __future__ import annotations

import logging
import subprocess
from typing import Any

from ..utils.json_utils import extract_first_json_object

logger = logging.getLogger(__name__)


class JsonAgent:
    """Base class for ranker agents that must return a JSON object."""

    def __init__(self, model: str, timeout: int = 120) -> None:
        self.model = model
        self.timeout = timeout

    def call_json(self, *, system: str, user: str) -> dict[str, Any] | None:
        cmd = ["claude", "--print", "--model", self.model, "--tools", ""]
        if system:
            cmd += ["--system-prompt", system]

        try:
            result = subprocess.run(
                cmd,
                input=user,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except FileNotFoundError:
            logger.error("claude CLI not found — ensure Claude Code is installed and on PATH")
            return None
        except subprocess.TimeoutExpired:
            logger.warning("claude CLI timed out")
            return None

        if result.returncode != 0:
            logger.warning("claude CLI returned non-zero: %s", result.stderr[:200])

        parsed = extract_first_json_object(result.stdout)
        if parsed is None:
            logger.warning("Agent returned non-JSON output")
        return parsed
