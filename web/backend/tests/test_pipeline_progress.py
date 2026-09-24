import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from pipeline_progress import (
    attach_pipeline_progress,
    clear_pipeline_progress,
    read_pipeline_progress,
)


class PipelineProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "campaigns"
        self.campaign_dir = self.root / "campaign-one"
        (self.campaign_dir / "data").mkdir(parents=True)
        self.status_path = self.campaign_dir / "data" / "pipeline_status.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_status(self, payload):
        self.status_path.write_text(json.dumps(payload), encoding="utf-8")

    def test_reads_and_normalizes_fresh_progress(self):
        self.write_status(
            {
                "phase": "filter",
                "label": "AI reviewing candidates",
                "phases": ["queries", "search", "filter", "ranking", "report"],
                "current": "24",
                "total": 100,
                "detail": "Reviewing profiles",
                "found": 137,
                "updated_at": "2026-09-24T12:00:05+00:00",
                "ignored": "not exposed",
            }
        )

        progress = read_pipeline_progress(
            self.campaign_dir,
            campaigns_root=self.root,
            run_started_at="2026-09-24T12:00:00",
            now=datetime(2026, 9, 24, 12, 1, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(
            progress,
            {
                "phase": "filter",
                "label": "AI reviewing candidates",
                "phases": ["queries", "search", "filter", "ranking", "report"],
                "current": 24,
                "total": 100,
                "detail": "Reviewing profiles",
                "found": 137,
                "updated_at": "2026-09-24T12:00:05+00:00",
            },
        )

    def test_rejects_status_older_than_the_current_run(self):
        self.write_status(
            {
                "phase": "search",
                "label": "Searching for candidate profiles",
                "updated_at": "2026-09-24T11:59:59+00:00",
            }
        )

        progress = read_pipeline_progress(
            self.campaign_dir,
            campaigns_root=self.root,
            run_started_at="2026-09-24T12:00:00",
        )

        self.assertIsNone(progress)

    def test_rejects_progress_that_is_too_old_or_too_far_in_the_future(self):
        self.write_status(
            {
                "phase": "filter",
                "label": "AI reviewing candidates",
                "updated_at": "2026-09-24T11:54:59+00:00",
            }
        )
        now = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)
        self.assertIsNone(
            read_pipeline_progress(
                self.campaign_dir,
                campaigns_root=self.root,
                run_started_at="2026-09-24T11:00:00",
                now=now,
            )
        )

        self.write_status(
            {
                "phase": "filter",
                "label": "AI reviewing candidates",
                "updated_at": "2026-09-24T12:01:01+00:00",
            }
        )
        self.assertIsNone(
            read_pipeline_progress(
                self.campaign_dir,
                campaigns_root=self.root,
                run_started_at="2026-09-24T11:00:00",
                now=now,
            )
        )

    def test_returns_none_for_missing_malformed_or_outside_root_status(self):
        self.assertIsNone(
            read_pipeline_progress(self.campaign_dir, campaigns_root=self.root)
        )

        self.status_path.write_text("{not-json", encoding="utf-8")
        self.assertIsNone(
            read_pipeline_progress(self.campaign_dir, campaigns_root=self.root)
        )

        outside = Path(self.temp_dir.name) / "outside"
        (outside / "data").mkdir(parents=True)
        (outside / "data" / "pipeline_status.json").write_text(
            json.dumps({"phase": "filter", "updated_at": "2026-09-24T12:00:00+00:00"}),
            encoding="utf-8",
        )
        self.assertIsNone(read_pipeline_progress(outside, campaigns_root=self.root))

    def test_attaches_progress_only_to_running_pipeline_runs(self):
        self.write_status(
            {
                "phase": "ranking",
                "label": "Scoring and ranking candidates",
                "current": 7,
                "total": 20,
                "updated_at": "2026-09-24T12:00:01+00:00",
            }
        )
        running = {
            "id": 8,
            "status": "Running",
            "campaign_dir": str(self.campaign_dir),
            "started_at": "2026-09-24T12:00:00",
        }
        completed = {**running, "status": "Completed"}

        attached = attach_pipeline_progress(
            running,
            campaigns_root=self.root,
            now=datetime(2026, 9, 24, 12, 1, 0, tzinfo=timezone.utc),
        )
        finished = attach_pipeline_progress(
            completed,
            campaigns_root=self.root,
            now=datetime(2026, 9, 24, 12, 1, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(attached["progress"]["current"], 7)
        self.assertEqual(attached["progress"]["total"], 20)
        self.assertIsNone(finished["progress"])
        self.assertNotIn("progress", running)

    def test_clear_removes_only_status_files_inside_campaign_root(self):
        self.write_status(
            {"phase": "filter", "updated_at": "2026-09-24T12:00:01+00:00"}
        )
        clear_pipeline_progress(self.campaign_dir, campaigns_root=self.root)
        self.assertFalse(self.status_path.exists())

        outside = Path(self.temp_dir.name) / "outside"
        outside_status = outside / "data" / "pipeline_status.json"
        outside_status.parent.mkdir(parents=True)
        outside_status.write_text("{}", encoding="utf-8")
        clear_pipeline_progress(outside, campaigns_root=self.root)
        self.assertTrue(outside_status.exists())

    def test_handles_numeric_and_timestamp_overflow_gracefully(self):
        self.write_status(
            {
                "phase": "filter",
                "label": "AI reviewing candidates",
                "current": 1e309,
                "total": float("nan"),
                "updated_at": "0001-01-01T00:00:00+23:59",
            }
        )
        self.assertIsNone(
            read_pipeline_progress(
                self.campaign_dir,
                campaigns_root=self.root,
                run_started_at="2026-09-24T12:00:00",
                now=datetime(2026, 9, 24, 12, 1, 0, tzinfo=timezone.utc),
            )
        )

    def test_rejects_symlinked_data_directory_without_reading_or_deleting_target(self):
        external = Path(self.temp_dir.name) / "external"
        external.mkdir()
        external_status = external / "pipeline_status.json"
        external_status.write_text(
            json.dumps(
                {
                    "phase": "filter",
                    "updated_at": "2026-09-24T12:00:01+00:00",
                }
            ),
            encoding="utf-8",
        )

        real_data = self.campaign_dir / "data"
        real_data.rmdir()
        real_data.symlink_to(external, target_is_directory=True)

        self.assertIsNone(
            read_pipeline_progress(
                self.campaign_dir,
                campaigns_root=self.root,
                now=datetime(2026, 9, 24, 12, 1, 0, tzinfo=timezone.utc),
            )
        )
        clear_pipeline_progress(self.campaign_dir, campaigns_root=self.root)
        self.assertTrue(external_status.exists())

    def test_rejects_symlinked_oversized_and_non_regular_status_files(self):
        external_status = Path(self.temp_dir.name) / "external-status.json"
        external_status.write_text(
            json.dumps(
                {
                    "phase": "search",
                    "updated_at": "2026-09-24T12:00:01+00:00",
                }
            ),
            encoding="utf-8",
        )
        self.status_path.symlink_to(external_status)
        self.assertIsNone(
            read_pipeline_progress(
                self.campaign_dir,
                campaigns_root=self.root,
                now=datetime(2026, 9, 24, 12, 1, 0, tzinfo=timezone.utc),
            )
        )
        clear_pipeline_progress(self.campaign_dir, campaigns_root=self.root)
        self.assertTrue(external_status.exists())
        self.assertTrue(self.status_path.is_symlink())

        self.status_path.unlink()
        self.status_path.write_bytes(b"x" * (64 * 1024 + 1))
        self.assertIsNone(
            read_pipeline_progress(
                self.campaign_dir,
                campaigns_root=self.root,
                now=datetime(2026, 9, 24, 12, 1, 0, tzinfo=timezone.utc),
            )
        )

        self.status_path.unlink()
        os.mkfifo(self.status_path)
        self.assertIsNone(
            read_pipeline_progress(
                self.campaign_dir,
                campaigns_root=self.root,
                now=datetime(2026, 9, 24, 12, 1, 0, tzinfo=timezone.utc),
            )
        )


if __name__ == "__main__":
    unittest.main()
