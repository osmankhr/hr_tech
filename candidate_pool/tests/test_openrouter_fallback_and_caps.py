"""OpenRouter retries, CLI-first fallback with spend guard, and the restored candidate caps."""
from __future__ import annotations

import io
import json
import subprocess
import sys
import urllib.error
from email.message import Message
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import llm_openrouter as orr  # noqa: E402
import llm_provider as lp  # noqa: E402
import prompt_trim  # noqa: E402


# ----------------------------------------------------------------------------- OpenRouter client
def _http_error(code: int, retry_after: str | None = None) -> urllib.error.HTTPError:
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError(orr.OPENROUTER_API_URL, code, "err", headers, io.BytesIO(b"{}"))


def _ok_response(cost: float | None = 0.0123) -> mock.MagicMock:
    usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    if cost is not None:
        usage["cost"] = cost
    body = json.dumps({"choices": [{"message": {"content": "hi"}}], "usage": usage}).encode()
    resp = mock.MagicMock()
    resp.read.return_value = body
    resp.__enter__.return_value = resp
    return resp


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    sleeps: list[float] = []
    monkeypatch.setattr(orr, "_sleep", sleeps.append)
    c = orr.OpenRouterClient(model="anthropic/claude-sonnet-5")
    c.sleeps = sleeps
    return c


def test_retries_rate_limit_then_succeeds_and_honours_retry_after(client):
    with mock.patch("urllib.request.urlopen", side_effect=[_http_error(429, "7"), _ok_response()]) as urlopen:
        assert client.complete(user="x") == "hi"
    assert urlopen.call_count == 2
    assert client.sleeps == [7.0]


def test_retry_after_is_capped(client):
    with mock.patch("urllib.request.urlopen", side_effect=[_http_error(503, "9999"), _ok_response()]):
        client.complete(user="x")
    assert client.sleeps == [orr.MAX_RETRY_WAIT_SECONDS]


def test_gives_up_after_max_attempts(client):
    with mock.patch("urllib.request.urlopen", side_effect=lambda *a, **k: (_ for _ in ()).throw(_http_error(502))) as urlopen:
        with pytest.raises(RuntimeError, match="502"):
            client.complete(user="x")
    assert urlopen.call_count == orr.DEFAULT_MAX_ATTEMPTS


@pytest.mark.parametrize("code", [400, 401, 402, 404])
def test_does_not_retry_client_errors(client, code):
    with mock.patch("urllib.request.urlopen", side_effect=[_http_error(code)]) as urlopen:
        with pytest.raises(RuntimeError, match=str(code)):
            client.complete(user="x")
    assert urlopen.call_count == 1 and client.sleeps == []


def test_retries_network_errors(client):
    with mock.patch("urllib.request.urlopen", side_effect=[urllib.error.URLError("reset"), _ok_response()]):
        assert client.complete(user="x") == "hi"
    assert len(client.sleeps) == 1


def test_cost_is_read_from_usage_cost(client):
    with mock.patch("urllib.request.urlopen", return_value=_ok_response(cost=0.0421)):
        client.complete(user="x")
    assert client.last_usage["total_cost"] == pytest.approx(0.0421)


# ----------------------------------------------------------------------------- CLI-first fallback
FAIL = subprocess.CompletedProcess(["claude"], 1, stdout=json.dumps({"is_error": True, "result": "usage limit"}), stderr="")
OK = subprocess.CompletedProcess(["claude"], 0, stdout=json.dumps({"is_error": False, "result": "from-cli", "usage": {}}), stderr="")


@pytest.fixture
def provider(monkeypatch):
    lp.reset_usage_summary()
    lp._profile_cooldowns.clear()
    monkeypatch.setattr(lp, "CLAUDE_PROFILE_CHAIN", ("only",))
    monkeypatch.setattr(lp, "choose_provider", lambda: "claude")
    for var in ("OPENROUTER_API_KEY", "CANDIDATE_POOL_OPENROUTER_FALLBACK", "CANDIDATE_POOL_OPENROUTER_MAX_USD"):
        monkeypatch.delenv(var, raising=False)
    yield monkeypatch
    lp.reset_usage_summary()


def _fake_client(cost: float, text: str = "from-openrouter"):
    class Fake:
        last_usage: dict = {}

        def __init__(self, **kwargs):
            pass

        def complete(self, *, system, user):
            Fake.last_usage = {"prompt_tokens": 1, "completion_tokens": 1, "total_cost": cost}
            return text

    return Fake


def _call():
    return lp.call_model_text(prompt="p", model="claude-sonnet-5", system=None, timeout=5)


def test_cli_success_never_touches_openrouter(provider):
    provider.setenv("OPENROUTER_API_KEY", "sk")
    provider.setattr(lp.subprocess, "run", lambda *a, **k: OK)
    with mock.patch.object(lp, "_call_openrouter") as orc:
        assert _call() == "from-cli"
    orc.assert_not_called()


def test_falls_back_to_openrouter_only_when_cli_fails(provider):
    provider.setenv("OPENROUTER_API_KEY", "sk")
    provider.setattr(lp.subprocess, "run", lambda *a, **k: FAIL)
    with mock.patch.object(lp, "_call_openrouter", return_value="from-openrouter") as orc:
        assert _call() == "from-openrouter"
    orc.assert_called_once()
    assert lp.get_usage_summary()["openrouter_fallback_calls"] == 1


def test_no_key_means_no_fallback(provider):
    provider.setattr(lp.subprocess, "run", lambda *a, **k: FAIL)
    with mock.patch.object(lp, "_call_openrouter") as orc:
        assert _call() is None
    orc.assert_not_called()


def test_fallback_can_be_switched_off(provider):
    provider.setenv("OPENROUTER_API_KEY", "sk")
    provider.setenv("CANDIDATE_POOL_OPENROUTER_FALLBACK", "off")
    provider.setattr(lp.subprocess, "run", lambda *a, **k: FAIL)
    with mock.patch.object(lp, "_call_openrouter") as orc:
        assert _call() is None
    orc.assert_not_called()


def test_spend_guard_stops_openrouter_calls(provider):
    provider.setenv("OPENROUTER_API_KEY", "sk")
    provider.setenv("CANDIDATE_POOL_OPENROUTER_MAX_USD", "0.05")
    provider.setattr(lp.subprocess, "run", lambda *a, **k: FAIL)
    import llm_openrouter

    provider.setattr(llm_openrouter, "OpenRouterClient", _fake_client(cost=0.03))
    assert [_call() for _ in range(4)] == ["from-openrouter", "from-openrouter", None, None]
    assert lp._openrouter_state["spent_usd"] == pytest.approx(0.06)


def test_explicit_openrouter_provider_skips_the_cli(provider):
    provider.setattr(lp, "choose_provider", lambda: "openrouter")
    with mock.patch.object(lp, "_call_openrouter", return_value="x") as orc, mock.patch.object(lp.subprocess, "run") as run:
        assert _call() == "x"
    orc.assert_called_once()
    run.assert_not_called()


# ----------------------------------------------------------------------------- caps
@pytest.mark.parametrize(
    "raw,expected",
    [(None, 100), ("", 100), (50, 50), ("25", 25), (0, None), (-1, None), ("0", None), (250, 250)],
)
def test_resolve_max_candidates(raw, expected):
    assert prompt_trim.resolve_max_candidates(raw) == expected


def test_default_cap_is_configurable(monkeypatch):
    monkeypatch.setenv("CANDIDATE_POOL_DEFAULT_MAX_CANDIDATES", "40")
    assert prompt_trim.resolve_max_candidates(None) == 40
    assert prompt_trim.resolve_max_candidates(0) is None


def test_filter_caps_by_default_and_uncaps_only_on_explicit_zero(tmp_path):
    import filter as f

    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "filter_criteria.md").write_text("criteria")
    assert f.CandidateFilter(tmp_path, {"filter": {}}).max_candidates == 100
    assert f.CandidateFilter(tmp_path, {"filter": {"max_candidates": 30}}).max_candidates == 30
    assert f.CandidateFilter(tmp_path, {"filter": {"max_candidates": 0}}).max_candidates is None


# ----------------------------------------------------------------------------- model slugs
@pytest.mark.parametrize(
    "given,expected",
    [
        ("claude-sonnet-5", "anthropic/claude-sonnet-5"),
        ("claude-sonnet-5-5", "anthropic/claude-sonnet-5.5"),
        ("claude-opus-5-5", "anthropic/claude-opus-5.5"),
        ("claude-haiku-5-5", "anthropic/claude-haiku-5.5"),
        ("anthropic/claude-sonnet-5.5", "anthropic/claude-sonnet-5.5"),
        ("openai/gpt-5", "openai/gpt-5"),
    ],
)
def test_openrouter_model_slug_normalisation(monkeypatch, given, expected):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    monkeypatch.delenv("CANDIDATE_POOL_OPENROUTER_MODEL", raising=False)
    assert orr.OpenRouterClient(model=given).model == expected


# ----------------------------------------------------------------------------- per-stage models
@pytest.fixture
def clean_model_env(monkeypatch):
    for var in ("OPENROUTER_MODEL", "CANDIDATE_POOL_OPENROUTER_MODEL", "CANDIDATE_POOL_OPENROUTER_MODEL_FILTER"):
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


def test_filter_stage_defaults_to_haiku_other_stages_keep_requested_model(clean_model_env):
    assert lp._openrouter_model_for("filter", "claude-sonnet-5") == "anthropic/claude-haiku-5.5"
    assert lp._openrouter_model_for("ranking", "claude-sonnet-5") == "claude-sonnet-5"
    assert lp._openrouter_model_for(None, "claude-sonnet-5") == "claude-sonnet-5"


def test_model_precedence_stage_env_over_global_env_over_stage_default(clean_model_env):
    clean_model_env.setenv("OPENROUTER_MODEL", "anthropic/claude-opus-5.5")
    assert lp._openrouter_model_for("filter", "x") == "anthropic/claude-opus-5.5"  # global beats stage default
    assert lp._openrouter_model_for("ranking", "x") == "anthropic/claude-opus-5.5"
    clean_model_env.setenv("CANDIDATE_POOL_OPENROUTER_MODEL_FILTER", "anthropic/claude-sonnet-5.5")
    assert lp._openrouter_model_for("filter", "x") == "anthropic/claude-sonnet-5.5"  # stage env beats global
    assert lp._openrouter_model_for("ranking", "x") == "anthropic/claude-opus-5.5"


def test_stage_model_reaches_the_client_even_when_global_env_is_set(clean_model_env):
    clean_model_env.setenv("OPENROUTER_API_KEY", "sk")
    clean_model_env.setenv("OPENROUTER_MODEL", "anthropic/claude-opus-5.5")
    clean_model_env.setenv("CANDIDATE_POOL_OPENROUTER_MODEL_FILTER", "anthropic/claude-haiku-5.5")
    seen = {}

    class Fake(orr.OpenRouterClient):
        def complete(self, *, system=None, user):
            seen["model"] = self.model
            self.last_usage = {"total_cost": 0.0}
            return "ok"

    clean_model_env.setattr(orr, "OpenRouterClient", Fake)
    lp.reset_usage_summary()
    assert lp._call_openrouter(prompt="p", model="claude-sonnet-5", system=None, timeout=5, stage="filter") == "ok"
    assert seen["model"] == "anthropic/claude-haiku-5.5"
    assert lp._call_openrouter(prompt="p", model="claude-sonnet-5", system=None, timeout=5, stage="ranking") == "ok"
    assert seen["model"] == "anthropic/claude-opus-5.5"


def test_filter_passes_its_stage_to_call_model_text(tmp_path, monkeypatch):
    import filter as f

    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "filter_criteria.md").write_text("c")
    captured = {}
    monkeypatch.setattr(f, "call_model_text", lambda **kw: captured.update(kw) or '{"recommendation": "ACCEPT"}')
    f.CandidateFilter(tmp_path, {"filter": {}})._call_model("prompt")
    assert captured["stage"] == "filter"
