import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import main


class CampaignVersionCandidatesTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_app.db"
        self.patcher_db = patch.object(main, "DB_PATH", self.db_path)
        self.patcher_db.start()

        conn = main.get_connection()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                full_name TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'hr'
            );
            CREATE TABLE IF NOT EXISTS campaigns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_code TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Active',
                created_by_user_id INTEGER
            );
            CREATE TABLE IF NOT EXISTS campaign_candidates (
                campaign_id INTEGER NOT NULL,
                candidate_id INTEGER NOT NULL,
                PRIMARY KEY (campaign_id, candidate_id)
            );
            CREATE TABLE IF NOT EXISTS candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_code TEXT UNIQUE,
                full_name TEXT,
                email TEXT,
                current_title TEXT,
                location TEXT,
                source TEXT,
                profile_url TEXT,
                score INTEGER,
                status TEXT,
                years_experience REAL,
                english_confidence TEXT,
                english_confidence_reason TEXT,
                last_updated TEXT,
                notes TEXT
            );
            CREATE TABLE IF NOT EXISTS skills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE
            );
            CREATE TABLE IF NOT EXISTS candidate_skills (
                candidate_id INTEGER NOT NULL,
                skill_id INTEGER NOT NULL,
                PRIMARY KEY (candidate_id, skill_id)
            );
        """)
        conn.commit()
        conn.close()

        main.ensure_pipeline_tables()
        conn = main.get_connection()

        conn.execute("INSERT INTO users (id, email, full_name, role) VALUES (1, 'test@example.com', 'Test User', 'hr')")
        conn.execute("INSERT INTO campaigns (id, campaign_code, name, status, created_by_user_id) VALUES (10, 'CMP-001', 'Test Campaign', 'Active', 1)")
        conn.commit()
        conn.close()

        self.user = {"id": 1, "email": "test@example.com", "full_name": "Test User", "role": "hr"}

    def tearDown(self):
        self.patcher_db.stop()
        self.temp_dir.cleanup()

    def test_list_candidates_for_specific_version(self):
        v1_dir = Path(self.temp_dir.name) / "v1_pipeline"
        v1_data = v1_dir / "data"
        v1_data.mkdir(parents=True, exist_ok=True)

        ranked_candidates_v1 = [
            {
                "title": "Alice Smith",
                "url": "https://linkedin.com/in/alicesmith",
                "email": "alice@example.com",
                "extracted_title": "Senior NLP Engineer",
                "location": "Istanbul, Turkey",
                "score": 92.4,
                "ai_review": {"recommendation": "ACCEPT"},
                "skills": ["NLP", "Python", "PyTorch"],
                "text": "Total Experience: 8 years",
                "ranking": {
                    "rank": 1,
                    "manual": {"manual_score": 95},
                    "agent": {"summary": "Strong NLP background"},
                    "feature_contributions": {"nlp": 0.8},
                },
            },
            {
                "title": "Bob Jones",
                "url": "https://linkedin.com/in/bobjones",
                "email": "bob@example.com",
                "extracted_title": "ML Engineer",
                "location": "Ankara, Turkey",
                "score": 78.0,
                "ai_review": {"recommendation": "PENDING"},
                "skills": ["Python"],
                "text": "Total Experience: 4 years",
                "ranking": {
                    "rank": 2,
                    "manual": {"manual_score": 78},
                    "agent": {},
                    "feature_contributions": {},
                },
            },
        ]
        (v1_data / "ranked_results.json").write_text(json.dumps(ranked_candidates_v1), encoding="utf-8")

        conn = main.get_connection()
        conn.execute("""
            INSERT INTO pipeline_config_versions (campaign_id, version_number, pipeline_dir, campaign_yaml_path, job_description_path, filter_criteria_path, created_at)
            VALUES (10, 1, ?, 'campaign.yaml', 'job.md', 'filter.md', '2026-09-24T12:00:00')
        """, (str(v1_dir),))
        conn.commit()
        conn.close()

        res = main.list_campaign_candidates(
            campaign_id=10,
            page=1,
            page_size=10,
            version_number=1,
            current_user=self.user,
        )

        self.assertEqual(res["pagination"]["total_items"], 2)
        self.assertEqual(res["version_number"], 1)
        self.assertEqual(len(res["items"]), 2)
        self.assertEqual(res["items"][0]["full_name"], "Alice Smith")
        self.assertEqual(res["items"][0]["status"], "Shortlisted")
        self.assertEqual(res["items"][0]["score"], 95)
        self.assertEqual(res["items"][0]["years_experience"], 8.0)
        self.assertEqual(res["items"][1]["full_name"], "Bob Jones")
        self.assertEqual(res["items"][1]["status"], "Reviewed")


if __name__ == "__main__":
    unittest.main()
