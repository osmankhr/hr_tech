from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import filter as candidate_filter
import ranking.pipeline as ranking_pipeline


class CandidateLimitsTests(unittest.TestCase):
    def test_filter_reviews_all_candidates_only_when_max_candidates_is_explicitly_zero(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            campaign_dir = Path(temp_dir)
            input_dir = campaign_dir / "input"
            input_dir.mkdir(parents=True, exist_ok=True)
            (input_dir / "filter_criteria.md").write_text("Must know Python", encoding="utf-8")

            data_dir = campaign_dir / "data" / "turkey"
            data_dir.mkdir(parents=True, exist_ok=True)
            candidates = [
                {"title": f"Candidate {i}", "url": f"https://example.com/{i}", "search_bucket": "turkey", "score": float(i)}
                for i in range(15)
            ]
            (data_dir / "raw_results.json").write_text(json.dumps(candidates), encoding="utf-8")

            cf = candidate_filter.CandidateFilter(campaign_dir, {"filter": {"max_candidates": 0, "max_workers": 1}})
            self.assertIsNone(cf.max_candidates)

            with patch.object(cf, "_review_candidate", return_value={"ai_review": {"recommendation": "ACCEPT"}}):
                results = cf.run()

            # All 15 should be reviewed, 0 skipped
            self.assertEqual(len(results), 15)
            self.assertTrue(all(c.get("ai_review", {}).get("recommendation") == "ACCEPT" for c in results))

    def test_filter_caps_when_max_candidates_is_set(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            campaign_dir = Path(temp_dir)
            input_dir = campaign_dir / "input"
            input_dir.mkdir(parents=True, exist_ok=True)
            (input_dir / "filter_criteria.md").write_text("Must know Python", encoding="utf-8")

            data_dir = campaign_dir / "data" / "turkey"
            data_dir.mkdir(parents=True, exist_ok=True)
            candidates = [
                {"title": f"Candidate {i}", "url": f"https://example.com/{i}", "search_bucket": "turkey", "score": float(i)}
                for i in range(10)
            ]
            (data_dir / "raw_results.json").write_text(json.dumps(candidates), encoding="utf-8")

            cf = candidate_filter.CandidateFilter(campaign_dir, {"filter": {"max_candidates": 3, "max_workers": 1}})
            self.assertEqual(cf.max_candidates, 3)

            with patch.object(cf, "_review_candidate", return_value={"ai_review": {"recommendation": "ACCEPT"}}):
                results = cf.run()

            self.assertEqual(len(results), 10)
            accepted = sum(1 for c in results if c.get("ai_review", {}).get("recommendation") == "ACCEPT")
            pending = sum(1 for c in results if c.get("ai_review", {}).get("recommendation") == "PENDING")
            self.assertEqual(accepted, 3)
            self.assertEqual(pending, 7)

    def test_missing_max_candidates_uses_the_default_cap_not_unlimited(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            campaign_dir = Path(temp_dir)
            (campaign_dir / "input").mkdir(parents=True, exist_ok=True)
            (campaign_dir / "input" / "filter_criteria.md").write_text("Must know Python", encoding="utf-8")
            cf = candidate_filter.CandidateFilter(campaign_dir, {"filter": {"max_candidates": None}})
            self.assertEqual(cf.max_candidates, 100)
            rp = ranking_pipeline.RankingPipeline(campaign_dir, {"ranking": {"max_candidates": None}})
            self.assertEqual(rp.max_candidates, 100)

    def test_ranking_ranks_all_candidates_only_when_max_candidates_is_explicitly_zero(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            campaign_dir = Path(temp_dir)
            rp = ranking_pipeline.RankingPipeline(campaign_dir, {"ranking": {"max_candidates": 0}})
            self.assertIsNone(rp.max_candidates)


if __name__ == "__main__":
    unittest.main()
