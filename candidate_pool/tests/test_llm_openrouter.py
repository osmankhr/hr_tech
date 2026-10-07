from __future__ import annotations

import io
import json
import os
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add candidate_pool/scripts to sys.path so we can import candidate_pool modules directly
CANDIDATE_POOL_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(CANDIDATE_POOL_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(CANDIDATE_POOL_SCRIPTS))

from llm_openrouter import (
    DEFAULT_OPENROUTER_MODEL,
    OPENROUTER_API_URL,
    OpenRouterClient,
)
import llm_provider


class TestOpenRouterClient(unittest.TestCase):
    def test_missing_api_key_raises(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError) as ctx:
                OpenRouterClient()
            self.assertIn("OPENROUTER_API_KEY", str(ctx.exception))

    def test_model_resolution_precedence(self):
        # 1. Environment variable override
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-test", "OPENROUTER_MODEL": "anthropic/claude-3.5-sonnet"}, clear=True):
            client = OpenRouterClient(model="anthropic/claude-3.7-sonnet")
            self.assertEqual(client.model, "anthropic/claude-3.5-sonnet")

        # 2. CANDIDATE_POOL_OPENROUTER_MODEL override
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-test", "CANDIDATE_POOL_OPENROUTER_MODEL": "anthropic/claude-3-opus"}, clear=True):
            client = OpenRouterClient()
            self.assertEqual(client.model, "anthropic/claude-3-opus")

        # 3. Explicit argument when no env var is set
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-test"}, clear=True):
            client = OpenRouterClient(model="custom-model-name")
            self.assertEqual(client.model, "custom-model-name")

        # 4. Default model fallback
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-test"}, clear=True):
            client = OpenRouterClient()
            self.assertEqual(client.model, DEFAULT_OPENROUTER_MODEL)

        # 5. Model without slash gets auto-prefixed with anthropic/
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-test"}, clear=True):
            client = OpenRouterClient(model="claude-sonnet-5")
            self.assertEqual(client.model, "anthropic/claude-sonnet-5")

    @patch("urllib.request.urlopen")
    def test_complete_success(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "id": "gen-123",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Candidate is highly qualified."
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 50,
                "completion_tokens": 15,
                "total_tokens": 65,
                "total_cost": 0.00045,
            }
        }).encode("utf-8")
        mock_response.__enter__.return_value = mock_response

        mock_urlopen.return_value = mock_response

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-test-key", "OPENROUTER_MODEL": "anthropic/claude-3.7-sonnet"}):
            client = OpenRouterClient()
            result = client.complete(system="You are a screener.", user="Evaluate candidate X.")

            self.assertEqual(result, "Candidate is highly qualified.")
            self.assertEqual(client.last_usage["prompt_tokens"], 50)
            self.assertEqual(client.last_usage["completion_tokens"], 15)
            self.assertEqual(client.last_usage["total_tokens"], 65)
            self.assertEqual(client.last_usage["total_cost"], 0.00045)

            # Check request details
            call_args = mock_urlopen.call_args
            req = call_args[0][0]
            self.assertEqual(req.full_url, OPENROUTER_API_URL)
            self.assertEqual(req.headers.get("Authorization"), "Bearer sk-test-key")
            self.assertEqual(req.headers.get("Content-type"), "application/json")

            payload = json.loads(req.data.decode("utf-8"))
            self.assertEqual(payload["model"], "anthropic/claude-3.7-sonnet")
            self.assertEqual(payload["messages"], [
                {"role": "system", "content": "You are a screener."},
                {"role": "user", "content": "Evaluate candidate X."}
            ])

    @patch("urllib.request.urlopen")
    def test_complete_http_error(self, mock_urlopen):
        from email.message import Message
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url=OPENROUTER_API_URL,
            code=429,
            msg="Rate limit exceeded",
            hdrs=Message(),
            fp=io.BytesIO(b'{"error": "rate limited"}')
        )

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-test-key"}), patch("llm_openrouter._sleep"):
            client = OpenRouterClient()
            with self.assertRaises(RuntimeError) as ctx:
                client.complete(user="Hello")
            self.assertIn("429", str(ctx.exception))


class TestLLMProviderOpenRouterIntegration(unittest.TestCase):
    def setUp(self):
        llm_provider.reset_usage_summary()

    def test_choose_provider_does_not_prefer_openrouter_just_because_key_present(self):
        # The key only enables OpenRouter as a fallback behind the Claude CLI profiles.
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-test", "CANDIDATE_POOL_LLM_PROVIDER": "auto"}):
            self.assertNotEqual(llm_provider.choose_provider(), "openrouter")

    def test_choose_provider_explicit_openrouter(self):
        with patch.dict(os.environ, {"CANDIDATE_POOL_LLM_PROVIDER": "openrouter"}):
            self.assertEqual(llm_provider.choose_provider(), "openrouter")

    @patch("llm_openrouter.OpenRouterClient.complete")
    def test_call_model_text_openrouter_success(self, mock_complete):
        mock_complete.return_value = '{"verdict": "keep"}'

        with patch.dict(os.environ, {
            "OPENROUTER_API_KEY": "sk-test",
            "OPENROUTER_MODEL": "anthropic/claude-3.7-sonnet",
            "CANDIDATE_POOL_LLM_PROVIDER": "openrouter",
        }):
            res = llm_provider.call_model_text(
                prompt="Evaluate CV",
                model="claude-sonnet-5",
                system="Screening prompt",
                timeout=30,
            )

            self.assertEqual(res, '{"verdict": "keep"}')
            usage = llm_provider.get_usage_summary()
            self.assertEqual(usage["calls"], 1)
            self.assertEqual(usage["errors"], 0)

    @patch("llm_openrouter.OpenRouterClient.complete")
    def test_call_model_text_openrouter_failure_fails_open(self, mock_complete):
        mock_complete.side_effect = RuntimeError("OpenRouter 500 error")

        with patch.dict(os.environ, {
            "OPENROUTER_API_KEY": "sk-test",
            "CANDIDATE_POOL_LLM_PROVIDER": "openrouter",
        }):
            res = llm_provider.call_model_text(
                prompt="Evaluate CV",
                model="claude-sonnet-5",
                system="Screening prompt",
                timeout=30,
            )

            # Never raises: returns None on failure so caller can fail open/continue batch
            self.assertIsNone(res)
            usage = llm_provider.get_usage_summary()
            self.assertEqual(usage["errors"], 1)


if __name__ == "__main__":
    unittest.main()
