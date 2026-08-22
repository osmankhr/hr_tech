"""Shared LLM client backed by Copilot CLI."""
from __future__ import annotations

import json
import os
import shutil
import subprocess


class CopilotClient:
    """Thin wrapper around Copilot CLI prompt mode."""

    def __init__(self, model: str, timeout: int = 120) -> None:
        self.model = model
        self.timeout = timeout

    def _resolve_cli_path(self) -> str:
        found = shutil.which("copilot")
        if found:
            return found

        vscode_bundle = os.path.expanduser(
            "~/Library/Application Support/Code/User/globalStorage/github.copilot-chat/copilotCli/copilot"
        )
        if os.path.exists(vscode_bundle):
            return vscode_bundle

        raise ValueError("Copilot CLI not found. Install/sign in to Copilot CLI first.")

    def _parse_output_content(self, stdout: str) -> str:
        content = ""
        delta_parts: list[str] = []

        for line in (stdout or "").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            event_type = obj.get("type")
            data = obj.get("data") or {}

            if event_type == "assistant.message":
                content = (data.get("content") or "").strip()
            elif event_type == "assistant.message_delta":
                piece = data.get("deltaContent")
                if isinstance(piece, str) and piece:
                    delta_parts.append(piece)
            elif event_type == "result":
                nested = data.get("result") if isinstance(data, dict) else None
                if isinstance(nested, dict):
                    maybe = nested.get("content")
                    if isinstance(maybe, str) and maybe.strip():
                        content = maybe.strip()

        if content:
            return content

        if delta_parts:
            return "".join(delta_parts).strip()

        return ""

    def _complete_via_cli(self, *, system: str | None, user: str) -> str:
        cli_path = self._resolve_cli_path()
        prompt = user if not system else f"{system}\n\n{user}"
        cli_model = self.model.removeprefix("openai/")

        base_cmd = [
            cli_path,
            "-p",
            prompt,
            "--output-format",
            "json",
            "--stream",
            "off",
            "--allow-all-tools",
            "--allow-all-paths",
            "--allow-all-urls",
        ]

        cmd_with_model = [*base_cmd, "--model", cli_model]

        env = os.environ.copy()
        # Prevent PAT variables from overriding Copilot CLI session auth.
        env.pop("GITHUB_TOKEN", None)
        env.pop("GH_TOKEN", None)
        env.pop("COPILOT_GITHUB_TOKEN", None)

        def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
            try:
                return subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                    check=False,
                    env=env,
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(f"Copilot CLI timed out after {self.timeout}s") from exc

        result = _run(cmd_with_model)
        content = self._parse_output_content(result.stdout or "")

        # If the requested model is not available or content is empty, retry with CLI default model.
        if result.returncode != 0 or not content:
            fallback = _run(base_cmd)
            fallback_content = self._parse_output_content(fallback.stdout or "")
            if fallback.returncode == 0 and fallback_content:
                return fallback_content

            stderr = (result.stderr or fallback.stderr or "").strip()
            raise RuntimeError(
                "Copilot CLI call failed. Re-authenticate with `copilot` -> /login if needed. "
                f"Details: {stderr or 'no stderr output'}"
            )

        return content

    def complete(self, *, system: str | None, user: str) -> str:
        """Return assistant text from a single completion call."""
        return self._complete_via_cli(system=system, user=user)
