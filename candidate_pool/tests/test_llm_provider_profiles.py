"""Claude CLI profile chain: error text is logged, logged-out profiles get skipped."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import llm_provider as lp  # noqa: E402


def _completed(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["claude"], returncode=returncode, stdout=stdout, stderr=stderr)


AUTH_ERR = json.dumps({"is_error": True, "result": "Failed to authenticate: OAuth session expired"})
OK = json.dumps({"is_error": False, "result": "pong", "usage": {}, "total_cost_usd": 0.0})


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    lp._profile_cooldowns.clear()
    lp.reset_usage_summary()
    monkeypatch.setattr(lp, "CLAUDE_PROFILE_CHAIN", ("dead", "live"))
    monkeypatch.setattr(lp, "choose_provider", lambda: "claude")
    yield
    lp._profile_cooldowns.clear()


def _fake_run(calls):
    def run(cmd, *, env, **kwargs):
        home = env["HOME"].rsplit("/", 1)[-1]
        calls.append(home)
        return _completed(1, AUTH_ERR) if home == "dead" else _completed(0, OK)

    return run


def test_error_text_comes_from_stdout_json_when_stderr_empty(caplog):
    caplog.set_level("WARNING")
    text, retry = None, None
    import unittest.mock as m

    with m.patch.object(lp.subprocess, "run", return_value=_completed(1, AUTH_ERR, "")):
        text, retry = lp._call_claude_cli(
            ["claude"], prompt="x", timeout=5, home=Path("/tmp/dead"), profile_label="dead"
        )
    assert text is None and retry is True
    assert "OAuth session expired" in caplog.text


def test_logged_out_profile_is_skipped_after_first_failure(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(lp.subprocess, "run", _fake_run(calls))
    for _ in range(3):
        assert lp.call_model_text(prompt="p", model="m", system=None, timeout=5) == "pong"
    # first call tries dead then live; later calls go straight to live
    assert calls == ["dead", "live", "live", "live"]


def test_all_profiles_cooling_down_still_tries_the_chain(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(lp.subprocess, "run", _fake_run(calls))
    lp._note_cli_failure("dead", "Failed to authenticate")
    lp._note_cli_failure("live", "Failed to authenticate")
    assert lp.call_model_text(prompt="p", model="m", system=None, timeout=5) == "pong"
    assert calls == ["dead", "live"]


def test_non_auth_errors_do_not_cool_down(monkeypatch):
    lp._note_cli_failure("live", "You've hit your usage limit")
    assert "live" not in lp._profile_cooldowns
