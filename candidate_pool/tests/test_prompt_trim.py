"""Prompt/output trimming: smaller prompts, same content, and every switch turns it back off."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import prompt_trim  # noqa: E402
from ranking.agents.candidate_scorer_agent import CandidateScorerAgent  # noqa: E402

TEXT = "# Ada\nSenior Data Analyst, SQL and Python for six years. " * 20
SCHEMA = {"features": [{"id": "sql"}], "notes": "n", "raw_response": {"big": "x" * 500}, "capabilities": {"a": 1}}
POLICY = {"weights": {"sql": 1}, "raw_response": {"big": "y" * 500}}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for var in ("CANDIDATE_POOL_TRIM_PROMPTS", "CANDIDATE_POOL_TERSE_OUTPUT", "CANDIDATE_POOL_CLAUDE_EFFORT"):
        monkeypatch.delenv(var, raising=False)


def test_dedupe_drops_highlights_already_in_excerpt_and_caps_the_rest():
    inside = TEXT[:200]
    outside = "A passage that only appears late in the page. " * 100
    got = prompt_trim.dedupe_highlights([inside, outside, outside + "2", outside + "3", ""], TEXT)
    assert inside not in got
    assert len(got) == prompt_trim.HIGHLIGHT_MAX_ITEMS
    assert all(len(h) <= prompt_trim.HIGHLIGHT_MAX_CHARS for h in got)


def test_strip_bookkeeping_only_removes_designer_keys():
    out = prompt_trim.strip_bookkeeping(SCHEMA)
    assert set(out) == {"features", "notes"}
    assert "raw_response" in SCHEMA  # input not mutated


def test_dumps_is_compact_when_trimming_and_pretty_when_not(monkeypatch):
    assert "\n" not in prompt_trim.dumps({"a": [1, 2]})
    monkeypatch.setenv("CANDIDATE_POOL_TRIM_PROMPTS", "0")
    assert prompt_trim.dumps({"a": 1}) == json.dumps({"a": 1}, indent=2)
    assert prompt_trim.strip_bookkeeping(SCHEMA) is SCHEMA
    assert prompt_trim.dedupe_highlights([TEXT[:100]], TEXT) == [TEXT[:100]]


@pytest.mark.parametrize("value,expected", [(None, "low"), ("high", "high"), ("off", None), ("0", None), ("", None)])
def test_effort_env(monkeypatch, value, expected):
    if value is not None:
        monkeypatch.setenv("CANDIDATE_POOL_CLAUDE_EFFORT", value)
    assert prompt_trim.candidate_effort() == expected


def _score(monkeypatch):
    from ranking.prompt_store import PromptStore

    agent = CandidateScorerAgent(model="m", prompt_store=PromptStore(Path("/nonexistent")))
    seen = {}

    def fake_call_json(*, system, user, retries=1, effort=None):
        seen.update(user=user, effort=effort)
        return {"feature_assessments": [], "summary": "ok"}

    monkeypatch.setattr(agent, "call_json", fake_call_json)
    agent.score_candidate(
        candidate={"url": "u", "text": TEXT, "highlights": [TEXT[:150]]},
        feature_schema=SCHEMA,
        scoring_policy=POLICY,
        text_chars=5000,
    )
    return seen


def test_scorer_prompt_is_trimmed_by_default(monkeypatch):
    seen = _score(monkeypatch)
    assert "raw_response" not in seen["user"] and "capabilities" not in seen["user"]
    assert prompt_trim.TERSE_OUTPUT_SUFFIX in seen["user"]
    assert seen["effort"] == "low"
    assert TEXT[:150] not in seen["user"].split("text_excerpt")[0]  # highlight deduped


def test_scorer_prompt_is_original_when_switches_are_off(monkeypatch):
    monkeypatch.setenv("CANDIDATE_POOL_TRIM_PROMPTS", "off")
    monkeypatch.setenv("CANDIDATE_POOL_TERSE_OUTPUT", "off")
    monkeypatch.setenv("CANDIDATE_POOL_CLAUDE_EFFORT", "off")
    seen = _score(monkeypatch)
    assert "raw_response" in seen["user"] and "capabilities" in seen["user"]
    assert prompt_trim.TERSE_OUTPUT_SUFFIX not in seen["user"]
    assert seen["effort"] is None
