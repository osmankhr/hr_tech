"""Shared LLM client backed by OpenRouter HTTP API."""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_OPENROUTER_MODEL = "anthropic/claude-sonnet-5"


class OpenRouterClient:
    """Thin wrapper around OpenRouter chat completions API."""

    def __init__(
        self,
        model: str | None = None,
        timeout: int = 120,
        api_key: str | None = None,
    ) -> None:
        self.api_key = (
            api_key
            or os.environ.get("OPENROUTER_API_KEY")
            or ""
        ).strip()
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY environment variable is not set.")

        env_model = (
            os.environ.get("OPENROUTER_MODEL")
            or os.environ.get("CANDIDATE_POOL_OPENROUTER_MODEL")
            or ""
        ).strip()

        chosen_model = env_model or model or DEFAULT_OPENROUTER_MODEL
        if "/" not in chosen_model and chosen_model.startswith("claude-"):
            chosen_model = f"anthropic/{chosen_model}"

        self.model = chosen_model
        self.timeout = timeout
        self.last_usage: dict[str, Any] = {}

    def complete(self, *, system: str | None = None, user: str) -> str:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})

        payload = {
            "model": self.model,
            "messages": messages,
        }
        body_bytes = json.dumps(payload).encode("utf-8")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/osmankhr/hr_tech",
            "X-Title": "Candidate Pool HR Tech",
            "User-Agent": "CandidatePool/1.0",
        }

        req = urllib.request.Request(
            OPENROUTER_API_URL,
            data=body_bytes,
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                raw_response = response.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            logger.error(
                "OpenRouter API HTTP %d: %s (body: %s)",
                e.code,
                e.reason,
                err_body[:300],
            )
            raise RuntimeError(
                f"OpenRouter API HTTP {e.code}: {e.reason} - {err_body[:200]}"
            ) from e
        except urllib.error.URLError as e:
            logger.error("OpenRouter network error: %s", e.reason)
            raise RuntimeError(f"OpenRouter network error: {e.reason}") from e

        try:
            data = json.loads(raw_response)
        except json.JSONDecodeError as e:
            logger.error("OpenRouter returned invalid JSON: %s", raw_response[:200])
            raise RuntimeError("OpenRouter response was not valid JSON") from e

        if not isinstance(data, dict):
            raise RuntimeError(f"OpenRouter response is not a dict: {type(data)}")

        if "error" in data and data["error"]:
            err_msg = str(data["error"])
            logger.error("OpenRouter returned error payload: %s", err_msg)
            raise RuntimeError(f"OpenRouter error: {err_msg}")

        choices = data.get("choices") or []
        if not choices or not isinstance(choices, list):
            raise RuntimeError("OpenRouter response missing 'choices'")

        first_choice = choices[0]
        message = first_choice.get("message") or {}
        content = message.get("content")

        if content is None:
            raise RuntimeError("OpenRouter response message content is None")

        usage = data.get("usage") or {}
        self.last_usage = {
            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
            "completion_tokens": int(usage.get("completion_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or 0),
            "cached_tokens": int(
                usage.get("prompt_tokens_details", {}).get("cached_tokens")
                or usage.get("cached_tokens")
                or 0
            ),
            "total_cost": float(usage.get("total_cost") or data.get("total_cost") or 0.0),
        }

        return content if isinstance(content, str) else str(content)
