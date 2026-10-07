"""Shared LLM client backed by OpenRouter HTTP API."""
from __future__ import annotations

import json
import logging
import os
import random
import re
import time
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_OPENROUTER_MODEL = "anthropic/claude-sonnet-5"

# Transient failures worth retrying: request timeout, rate limit, and upstream/server errors.
# Everything else (400/401/402/403/404...) is a config or request problem; retrying only wastes time.
RETRYABLE_HTTP_CODES = {408, 429, 500, 502, 503, 504}
DEFAULT_MAX_ATTEMPTS = 3
MAX_RETRY_WAIT_SECONDS = 30.0
_BASE_BACKOFF_SECONDS = 2.0

_sleep = time.sleep  # indirection so tests don't really wait


def _max_attempts() -> int:
    try:
        return max(1, int(os.environ.get("CANDIDATE_POOL_OPENROUTER_ATTEMPTS", DEFAULT_MAX_ATTEMPTS)))
    except ValueError:
        return DEFAULT_MAX_ATTEMPTS


def _retry_wait(attempt: int, retry_after: str | None) -> float:
    """Seconds to wait before attempt `attempt + 1`: honour Retry-After, else exponential + jitter."""
    if retry_after:
        try:
            return min(max(float(retry_after), 0.0), MAX_RETRY_WAIT_SECONDS)
        except ValueError:
            pass
    return min(_BASE_BACKOFF_SECONDS * (2 ** (attempt - 1)) + random.uniform(0, 1), MAX_RETRY_WAIT_SECONDS)


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
            # Anthropic API ids use dashes (claude-sonnet-5-5); OpenRouter slugs use a dot for the
            # minor version (anthropic/claude-sonnet-5.5).
            chosen_model = "anthropic/" + re.sub(r"^(claude-(?:opus|sonnet|haiku)-\d+)-(\d+)$", r"\1.\2", chosen_model)

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

        attempts = _max_attempts()
        raw_response = ""
        for attempt in range(1, attempts + 1):
            req = urllib.request.Request(
                OPENROUTER_API_URL,
                data=body_bytes,
                headers=headers,
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as response:
                    raw_response = response.read().decode("utf-8")
                break
            except urllib.error.HTTPError as e:
                err_body = ""
                try:
                    err_body = e.read().decode("utf-8", errors="replace")
                except Exception:
                    pass
                retryable = e.code in RETRYABLE_HTTP_CODES and attempt < attempts
                logger.log(
                    logging.WARNING if retryable else logging.ERROR,
                    "OpenRouter API HTTP %d: %s (attempt %d/%d, body: %s)",
                    e.code,
                    e.reason,
                    attempt,
                    attempts,
                    err_body[:300],
                )
                if not retryable:
                    raise RuntimeError(
                        f"OpenRouter API HTTP {e.code}: {e.reason} - {err_body[:200]}"
                    ) from e
                _sleep(_retry_wait(attempt, e.headers.get("Retry-After") if e.headers else None))
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                reason = getattr(e, "reason", e)
                logger.log(
                    logging.WARNING if attempt < attempts else logging.ERROR,
                    "OpenRouter network error: %s (attempt %d/%d)",
                    reason,
                    attempt,
                    attempts,
                )
                if attempt >= attempts:
                    raise RuntimeError(f"OpenRouter network error: {reason}") from e
                _sleep(_retry_wait(attempt, None))

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
            # OpenRouter reports credits spent as `usage.cost`; `total_cost` is kept as a fallback.
            "total_cost": float(
                usage.get("cost") or usage.get("total_cost") or data.get("total_cost") or 0.0
            ),
        }

        return content if isinstance(content, str) else str(content)
