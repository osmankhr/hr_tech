"""Shared agent wrapper for Claude-powered JSON responses."""
from __future__ import annotations

import logging
from typing import Any

from llm_provider import call_model_text
from ..utils.json_utils import extract_first_json_object

logger = logging.getLogger(__name__)


class JsonAgent:
    """Base class for ranker agents that must return a JSON object."""

    def __init__(self, model: str, timeout: int = 120) -> None:
        self.model = model
        self.timeout = timeout

    def call_json(self, *, system: str, user: str) -> dict[str, Any] | None:
        output = call_model_text(
            prompt=user,
            model=self.model,
            system=system,
            timeout=self.timeout,
        )
        if not output:
            return None

        parsed = extract_first_json_object(output)
        if parsed is None:
            logger.warning("Agent returned non-JSON output")
        return parsed
