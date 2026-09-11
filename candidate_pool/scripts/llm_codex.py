"""One-shot LLM client backed by the Codex CLI (`codex exec`).

Same contract as llm_client.CopilotClient: a single prompt in, assistant text out, no agent
loop. `codex exec` is an agent runner rather than a completion endpoint, so this locks it down
as far as the CLI allows — read-only sandbox, no approvals, a scratch working directory — and
reads the final message from `--output-last-message` instead of trying to scrape the stream.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


class CodexClient:
    """Thin wrapper around Codex CLI non-interactive mode."""

    def __init__(self, model: str | None = None, timeout: int = 120) -> None:
        self.model = model
        self.timeout = timeout
        self.last_usage: dict[str, int] = {}

    def _resolve_cli_path(self) -> str:
        found = shutil.which("codex")
        if found:
            return found

        for candidate in (
            "/opt/homebrew/bin/codex",
            "/usr/local/bin/codex",
            os.path.expanduser("~/.local/bin/codex"),
        ):
            if os.path.exists(candidate):
                return candidate

        raise ValueError("Codex CLI not found. Install it and run `codex login` first.")

    @staticmethod
    def _parse_stream(stdout: str) -> tuple[str, dict[str, int]]:
        """Pull the failure reason and token usage out of the JSONL event stream.

        Event names have shifted between Codex CLI versions, so this matches on shape (any
        event carrying a usage dict, any event carrying an error message) rather than on exact
        `type` values, and treats everything it doesn't recognise as noise.
        """
        error_message = ""
        usage: dict[str, int] = {}

        for line in (stdout or "").splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue

            maybe_usage = event.get("usage")
            if isinstance(maybe_usage, dict):
                for key in ("input_tokens", "output_tokens", "cached_input_tokens"):
                    value = maybe_usage.get(key)
                    if isinstance(value, int):
                        usage[key] = value

            # Keep the last error seen: the CLI logs transient retries before the fatal one.
            nested_error = event.get("error")
            if isinstance(nested_error, dict) and nested_error.get("message"):
                error_message = str(nested_error["message"])
            elif event.get("type") == "error" and event.get("message"):
                error_message = str(event["message"])

        return error_message, usage

    def _complete_via_cli(self, *, system: str | None, user: str) -> str:
        cli_path = self._resolve_cli_path()
        # No --system-prompt equivalent in `codex exec`, so the system text is folded in.
        prompt = user if not system else f"{system}\n\n{user}"

        with tempfile.TemporaryDirectory(prefix="candidate-pool-codex-") as scratch:
            last_message_path = Path(scratch) / "last_message.txt"

            cmd = [
                cli_path,
                "exec",
                # The scratch cwd isn't a repo, and the agent has no business reading this one.
                "--skip-git-repo-check",
                "-C",
                scratch,
                "-s",
                "read-only",
                "-c",
                'approval_policy="never"',
                "--color",
                "never",
                "--json",
                # One rollout file per call would otherwise pile up in ~/.codex/sessions
                # forever -- a single campaign makes one call per candidate.
                "--ephemeral",
                "-o",
                str(last_message_path),
            ]
            if self.model:
                cmd += ["-m", self.model]
            # Trailing "-" makes the CLI read the prompt from stdin, so prompt size isn't
            # bounded by the shell's argument limit.
            cmd.append("-")

            env = os.environ.copy()
            # Codex reads its own session credentials from ~/.codex; ambient PATs confuse it.
            env.pop("OPENAI_API_KEY", None)

            try:
                result = subprocess.run(
                    cmd,
                    input=prompt,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                    check=False,
                    env=env,
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(f"Codex CLI timed out after {self.timeout}s") from exc

            error_message, usage = self._parse_stream(result.stdout or "")
            self.last_usage = usage

            content = ""
            if last_message_path.exists():
                content = last_message_path.read_text(encoding="utf-8").strip()

        if content:
            return content

        detail = error_message or (result.stderr or "").strip() or "no output"
        if "401" in detail or "unauthorized" in detail.lower():
            raise RuntimeError(
                f"Codex CLI is not authenticated — run `codex login`. Details: {detail}"
            )
        if "not supported when using Codex with a ChatGPT account" in detail:
            raise RuntimeError(
                "Codex ChatGPT login cannot use this model (the *-codex IDs are API-key only). "
                "Set CANDIDATE_POOL_CODEX_MODEL to a ChatGPT-login model such as gpt-5.6-luna. "
                f"Details: {detail}"
            )
        if "requires a newer version of Codex" in detail:
            raise RuntimeError(
                "Codex CLI is too old for this model — upgrade with "
                "`npm install -g @openai/codex@latest`. "
                f"Details: {detail}"
            )
        raise RuntimeError(f"Codex CLI call failed. Details: {detail}")

    def complete(self, *, system: str | None, user: str) -> str:
        """Return assistant text from a single completion call.

        Deliberately no retry on timeout: run wall-clock time matters more here than rescuing
        the occasional stalled call, and the filter stage already rejects candidates whose
        review fails.
        """
        return self._complete_via_cli(system=system, user=user)
