"""Thin client for TypeSafe AI's System One (Jev) API.

Used as a cheap, structured-decision alternative to full LLM calls for specific sub-questions
inside the pipeline (currently: the ING-employer check and english_confidence rating in
filter.py -- see typesafe_pilot_ing_check.py and typesafe_pilot_english_confidence.py for how
each was validated against production data before being wired in).

Never raises -- callers get None on any failure (missing key, network error, timeout, bad
response) and are expected to fall back to their pre-TypeSafe behavior, same convention as
llm_provider.call_model_text.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

API_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"


def ask_noul(state: Any, instructions: str, *, timeout: int = 15) -> float | None:
    """Ask a single yes/no (Noul) question. Returns the probability of "yes" in [0, 1], or None
    if the call couldn't be made or failed for any reason.
    """
    api_key = os.environ.get("TYPESAFE_API_KEY")
    if not api_key:
        return None

    try:
        resp = requests.post(
            API_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "state": state,
                "model": DEFAULT_MODEL,
                "questions": {"q": {"type": "noul", "instructions": instructions}},
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        return float(resp.json()["answers"]["q"]["noul"])
    except Exception:
        logger.warning("TypeSafe API call failed", exc_info=True)
        return None


def ask_score(state: Any, instructions: str, criteria: list[str], *, timeout: int = 15) -> int | None:
    """Ask a single Score question against an ordered list of level descriptions. Returns the
    index (0-based) of the highest-probability level, or None if the call couldn't be made or
    failed for any reason.
    """
    api_key = os.environ.get("TYPESAFE_API_KEY")
    if not api_key:
        return None

    try:
        resp = requests.post(
            API_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "state": state,
                "model": DEFAULT_MODEL,
                "questions": {"q": {"type": "score", "instructions": instructions, "criteria": criteria}},
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        probabilities = resp.json()["answers"]["q"]["probabilities"]
        return int(max(probabilities, key=lambda level: probabilities[level]))
    except Exception:
        logger.warning("TypeSafe API call failed", exc_info=True)
        return None
