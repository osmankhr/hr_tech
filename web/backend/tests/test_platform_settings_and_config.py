import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import HTTPException

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import main


class PlatformSettingsAndConfigTests(unittest.TestCase):
    """Unit tests for campaign platform selection and integration credential settings."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env_path = Path(self.temp_dir.name) / ".env"
        self.patcher_env = patch.object(main, "CANDIDATE_POOL_ENV_PATH", self.env_path)
        self.patcher_env.start()
        self.user = {"id": 1, "email": "hr@example.com", "full_name": "HR User", "role": "hr"}

    def tearDown(self):
        self.patcher_env.stop()
        self.temp_dir.cleanup()

    def test_build_and_read_campaign_yaml_with_platforms(self):
        pipeline_dir = Path(self.temp_dir.name) / "campaign_1"
        (pipeline_dir / "input").mkdir(parents=True, exist_ok=True)

        yaml_text = main._build_campaign_yaml(
            name="Senior AI Engineer",
            description="Sourcing across Exa and community platforms",
            locations=[{"name": "turkey", "hint": "Istanbul, Ankara"}],
            platforms=["github", "huggingface", "kaggle"],
            activity_days=120,
        )
        (pipeline_dir / "campaign.yaml").write_text(yaml_text, encoding="utf-8")
        (pipeline_dir / "input" / "job_description.md").write_text("# JD", encoding="utf-8")
        (pipeline_dir / "input" / "filter_criteria_raw.md").write_text("# Criteria", encoding="utf-8")

        read_back = main._read_pipeline_config_files(pipeline_dir)
        self.assertEqual(read_back["pipeline_name"], "Senior AI Engineer")
        self.assertEqual(read_back["platforms"], ["github", "huggingface", "kaggle"])
        self.assertEqual(read_back["activity_days"], 120)

    def test_parse_platforms_json_rejects_disallowed_platforms(self):
        valid = main._parse_platforms_json('["github", "kaggle", "github"]')
        self.assertEqual(valid, ["github", "kaggle"])

        with self.assertRaises(HTTPException) as ctx:
            main._parse_platforms_json('["github", "malicious_platform"]')
        self.assertEqual(ctx.exception.status_code, 400)

    def test_integration_settings_masks_secrets_and_blocks_injection(self):
        # Initial state with unrelated variable in .env
        self.env_path.write_text("UNRELATED_VAR=keep_me\n", encoding="utf-8")

        with patch.dict(os.environ, {}, clear=False):
            res = main.update_integration_settings(
                payload={
                    "credentials": {
                        "KAGGLE_USERNAME": "mustafa_kaggle",
                        "KAGGLE_KEY": "KGAT_secret1234567890",
                        "GITHUB_TOKEN": "ghp_abcdefghijklmnop1234",
                        "EXA_API_KEY": "79de4afd-a50f-43bd-801a-70ec5cc65040",
                    },
                    "clear_keys": [],
                },
                current_user=self.user,
            )

            self.assertTrue(res["success"])
            self.assertEqual(res["keys"]["KAGGLE_USERNAME"]["masked"], "mustafa_kaggle")
            # Raw secret must NEVER be present in masked output
            self.assertNotIn("KGAT_secret", res["keys"]["KAGGLE_KEY"]["masked"])
            self.assertTrue(res["keys"]["KAGGLE_KEY"]["masked"].endswith("7890"))
            self.assertTrue(res["platforms"]["kaggle"]["official_api_configured"])
            self.assertTrue(res["platforms"]["github"]["token_configured"])

            # Verify unrelated .env lines are preserved
            env_text = self.env_path.read_text(encoding="utf-8")
            self.assertIn("UNRELATED_VAR=keep_me", env_text)
            self.assertIn("KAGGLE_USERNAME=mustafa_kaggle", env_text)

            # Verify newline injection is blocked with 400
            with self.assertRaises(HTTPException) as ctx:
                main.update_integration_settings(
                    payload={
                        "credentials": {
                            "KAGGLE_KEY": "bad_value\nLD_PRELOAD=/tmp/evil.so",
                        }
                    },
                    current_user=self.user,
                )
            self.assertEqual(ctx.exception.status_code, 400)

            # Verify unknown keys are rejected with 400
            with self.assertRaises(HTTPException) as ctx2:
                main.update_integration_settings(
                    payload={
                        "credentials": {
                            "PATH": "/malicious",
                        }
                    },
                    current_user=self.user,
                )
            self.assertEqual(ctx2.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
