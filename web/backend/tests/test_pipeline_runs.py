import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from pipeline_runs import PipelineRunAlreadyRunning, reserve_pipeline_run


SCHEMA = """
CREATE TABLE pipeline_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    run_type TEXT NOT NULL,
    status TEXT NOT NULL,
    command TEXT,
    campaign_dir TEXT,
    artifact_path TEXT,
    started_at TEXT,
    created_by_user_id INTEGER
)
"""


class PipelineRunReservationTests(unittest.TestCase):
    def test_concurrent_requests_reserve_only_one_running_run(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "runs.db"
            conn = sqlite3.connect(db_path)
            conn.execute(SCHEMA)
            conn.commit()
            conn.close()

            barrier = threading.Barrier(2)
            results = []
            result_lock = threading.Lock()

            def reserve():
                worker_conn = sqlite3.connect(db_path, timeout=5)
                barrier.wait()
                try:
                    run_id = reserve_pipeline_run(
                        worker_conn,
                        campaign_id=1,
                        run_type="full",
                        command="python run_campaign.py",
                        campaign_dir="/campaigns/one",
                        artifact_path="/campaigns/one/data/ranked_results.json",
                        started_at="2026-09-24T12:00:00",
                        created_by_user_id=9,
                    )
                    outcome = ("reserved", run_id)
                except PipelineRunAlreadyRunning:
                    outcome = ("already-running", None)
                finally:
                    worker_conn.close()
                with result_lock:
                    results.append(outcome)

            threads = [threading.Thread(target=reserve) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)

            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertEqual(sorted(result[0] for result in results), [
                "already-running",
                "reserved",
            ])

            conn = sqlite3.connect(db_path)
            count = conn.execute(
                "SELECT COUNT(*) FROM pipeline_runs WHERE campaign_id = 1 AND status = 'Running'"
            ).fetchone()[0]
            conn.close()
            self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
