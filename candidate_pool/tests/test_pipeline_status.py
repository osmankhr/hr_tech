import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import pipeline_status
import filter as candidate_filter
import ranking.pipeline as ranking_pipeline
import search


class PipelineStatusTests(unittest.TestCase):
    def tearDown(self):
        pipeline_status._planned_phases = None

    def test_write_records_item_and_discovery_progress_atomically(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            campaign_dir = Path(temp_dir)

            pipeline_status.write(
                campaign_dir,
                "search",
                current=3,
                total=8,
                found=42,
                detail="Ankara · query 3 of 8",
                phases=["queries", "search", "filter"],
            )

            status_path = campaign_dir / "data" / "pipeline_status.json"
            payload = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["phase"], "search")
            self.assertEqual(payload["current"], 3)
            self.assertEqual(payload["total"], 8)
            self.assertEqual(payload["found"], 42)
            self.assertEqual(payload["detail"], "Ankara · query 3 of 8")
            self.assertEqual(payload["phases"], ["queries", "search", "filter"])
            self.assertFalse(status_path.with_suffix(".json.tmp").exists())

    def test_follow_up_writes_keep_the_declared_phase_plan(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            campaign_dir = Path(temp_dir)
            pipeline_status.write(
                campaign_dir,
                "filter",
                phases=["filter", "ranking"],
            )
            pipeline_status.write(campaign_dir, "filter", current=1, total=5)

            payload = json.loads(
                (campaign_dir / "data" / "pipeline_status.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(payload["phases"], ["filter", "ranking"])

    def test_search_reports_completed_queries_and_candidates_found(self):
        searcher = search.ExaSearcher.__new__(search.ExaSearcher)
        searcher.campaign_dir = Path("/campaign")
        searcher.provider = "exa"
        searcher._load_queries_for_location = lambda _location: ["query one", "query two"]
        searcher._search_query = lambda query, _location, _seen: (
            [{"url": "one"}] if query == "query one" else [{"url": "two"}, {"url": "three"}]
        )

        with patch.object(search.pipeline_status, "write") as write_progress:
            candidates, queries = searcher.search_location(
                {"name": "Ankara"},
                progress_offset=0,
                progress_total=2,
                found_offset=0,
            )

        self.assertEqual(queries, ["query one", "query two"])
        self.assertEqual(len(candidates), 3)
        self.assertEqual(write_progress.call_count, 2)
        self.assertEqual(write_progress.call_args_list[0].kwargs["current"], 1)
        self.assertEqual(write_progress.call_args_list[0].kwargs["total"], 2)
        self.assertEqual(write_progress.call_args_list[0].kwargs["found"], 1)
        self.assertEqual(write_progress.call_args_list[1].kwargs["current"], 2)
        self.assertEqual(write_progress.call_args_list[1].kwargs["found"], 3)
        self.assertEqual(
            write_progress.call_args_list[1].kwargs["detail"],
            "Ankara · query 2 of 2",
        )

    def test_search_counts_skipped_malformed_queries_as_processed(self):
        searcher = search.ExaSearcher.__new__(search.ExaSearcher)
        searcher.campaign_dir = Path("/campaign")
        searcher.provider = "apollo"
        searcher._load_queries_for_location = lambda _location: [
            {"person_titles": ["engineer"]},
            "malformed",
        ]
        searcher._search_apollo_query = lambda _query, _location, _seen: [
            {"url": "one"}
        ]

        with patch.object(search.pipeline_status, "write") as write_progress:
            candidates, _queries = searcher.search_location(
                {"name": "Istanbul"},
                progress_total=2,
            )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(write_progress.call_count, 2)
        self.assertEqual(write_progress.call_args_list[-1].kwargs["current"], 2)
        self.assertEqual(write_progress.call_args_list[-1].kwargs["total"], 2)
        self.assertEqual(write_progress.call_args_list[-1].kwargs["found"], 1)

    def test_filter_reports_zero_before_candidate_reviews_start(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            campaign_dir = Path(temp_dir)
            input_dir = campaign_dir / "input"
            input_dir.mkdir()
            (campaign_dir / "data").mkdir()
            (input_dir / "filter_criteria.md").write_text("criteria", encoding="utf-8")
            filterer = candidate_filter.CandidateFilter(
                campaign_dir,
                {"filter": {"max_candidates": 5, "max_workers": 1}},
            )
            filterer._load_all_candidates = lambda: [
                {"url": "candidate", "search_bucket": "Ankara", "score": 1}
            ]
            filterer._review_candidate = lambda candidate: {
                **candidate,
                "ai_review": {"recommendation": "ACCEPT"},
            }

            with patch.object(candidate_filter.pipeline_status, "write") as write_progress:
                filterer.run()

        first_progress = write_progress.call_args_list[0].kwargs
        self.assertEqual(first_progress["current"], 0)
        self.assertEqual(first_progress["total"], 1)

    def test_ranking_reports_zero_before_candidate_scoring_starts(self):
        class FakeGrader:
            def __init__(self, **_kwargs):
                pass

            def grade(self, **_kwargs):
                return {"manual_score": 50}

        with tempfile.TemporaryDirectory() as temp_dir:
            campaign_dir = Path(temp_dir)
            ranker = ranking_pipeline.RankingPipeline(
                campaign_dir,
                {"ranking": {"batch_size": 1, "max_workers": 1}},
            )
            ranker._load_candidates = lambda: [{"url": "candidate", "score": 1}]
            ranker._load_inputs = lambda: ("job", "criteria")
            ranker._load_or_build_feature_schema = lambda **_kwargs: {"features": []}
            ranker._load_or_build_scoring_policy = lambda **_kwargs: {}
            ranker.candidate_agent.score_candidate = lambda **_kwargs: {
                "feature_assessments": [],
                "gate_flags": [],
                "summary": "",
            }

            with (
                patch.object(ranking_pipeline, "ManualGrader", FakeGrader),
                patch.object(ranking_pipeline.pipeline_status, "write") as write_progress,
            ):
                ranker.run()

        first_progress = write_progress.call_args_list[0].kwargs
        self.assertEqual(first_progress["current"], 0)
        self.assertEqual(first_progress["total"], 1)


if __name__ == "__main__":
    unittest.main()
