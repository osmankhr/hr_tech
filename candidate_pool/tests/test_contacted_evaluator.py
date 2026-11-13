"""Tests for contacted candidates evaluation, comparison, and analysis store."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# Allow importing candidate_pool scripts
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from contacted_candidates import ContactedCandidatesStore
from contacted_evaluator import (
    ContactedCandidateEvaluator,
    determine_alignment,
    resolve_comparison_report_path,
    resolve_contacted_evaluations_path,
)
from search import ExaSearcher


class TestContactedStoreRecordExtraction:
    def test_extract_records_from_excel(self, tmp_path: Path):
        excel_path = tmp_path / "contacted.xlsx"
        df = pd.DataFrame(
            {
                "Candidate Name": ["Yiğit Can Özkaya", "Işıl Şen"],
                "URL": ["https://linkedin.com/in/yigitcan", "https://linkedin.com/in/isilsen"],
                "Status": ["Interviewed", "Rejected"],
                "Notes": ["Great background in PyTorch", "Junior level, insufficient NLP"],
                "Recruiter": ["Ayşe IK", "Mehmet IK"],
            }
        )
        with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
            df.to_excel(writer, index=False)

        store = ContactedCandidatesStore(excel_path)
        assert not store.is_empty()
        assert "yigit can ozkaya" in store.contacted_records_by_name
        assert "linkedin.com/in/isilsen" in store.contacted_records_by_url

        # Match by URL
        match_url = store.get_contacted_match({"url": "https://tr.linkedin.com/in/isilsen"})
        assert match_url is not None
        assert match_url["match_type"] == "url"
        assert match_url["recruiter_record"]["Status"] == "Rejected"
        assert "NLP" in match_url["recruiter_record"]["Notes"]

        # Match by Name
        match_name = store.get_contacted_match({
            "title": "Yiğit Can Özkaya - Lead AI Engineer",
            "url": "https://linkedin.com/in/different-slug",
        })
        assert match_name is not None
        assert match_name["match_type"] == "title_name"
        assert match_name["recruiter_record"]["Status"] == "Interviewed"
        assert match_name["recruiter_record"]["Recruiter"] == "Ayşe IK"


class TestAlignmentDetermination:
    def test_alignment_logic(self):
        # Both rejected
        assert determine_alignment("Rejected", "Candidate lacks experience", "REJECT") == "Aligned (Both Rejected)"
        assert determine_alignment("Elendi", "Yetersiz", "REJECT") == "Aligned (Both Rejected)"

        # Both accepted
        assert determine_alignment("Interviewed", "Strong candidate", "ACCEPT") == "Aligned (Both Accepted/Interested)"
        assert determine_alignment("Offered", "Hired for AI chapter", "ACCEPT") == "Aligned (Both Accepted/Interested)"

        # Discrepancies
        assert determine_alignment("Interviewed", "Good candidate", "REJECT") == "Discrepancy (HR Positive vs AI Rejected)"
        assert determine_alignment("Rejected", "Failed technical screen", "ACCEPT") == "Discrepancy (HR Rejected vs AI Accepted)"

        # AI Pending
        assert determine_alignment("Contacted", "Awaiting response", "PENDING") == "AI Marked Pending"

        # Missing HR
        assert determine_alignment("", "", "ACCEPT") == "No HR Feedback Recorded"


class TestContactedCandidateEvaluator:
    @pytest.fixture
    def setup_campaign(self, tmp_path: Path):
        campaign_dir = tmp_path / "campaign"
        campaign_dir.mkdir(parents=True)
        (campaign_dir / "input").mkdir(parents=True)
        (campaign_dir / "input" / "filter_criteria.md").write_text("# Filter Criteria", encoding="utf-8")
        data_dir = campaign_dir / "data" / "turkey"
        data_dir.mkdir(parents=True)

        config = {
            "name": "Senior AI Engineer Campaign",
            "ranking": {"enabled": True},
            "analysis": {
                "contacted_evaluations_path": str(tmp_path / "analysis" / "test_evals.jsonl"),
                "contacted_comparison_report_path": str(tmp_path / "analysis" / "test_comparison.xlsx"),
            },
        }

        # Simulated contacted hits
        hits = [
            {
                "title": "Yiğit Can - Senior Data Scientist",
                "url": "https://linkedin.com/in/yigitcan",
                "location": "Istanbul, Turkey",
                "search_bucket": "turkey",
                "text": "Extensive experience in NLP and LLMs.",
                "contacted_match": {
                    "match_type": "direct_name",
                    "matched_key": "yigit can",
                    "recruiter_record": {
                        "Candidate Name": "Yiğit Can",
                        "Status": "Interviewed",
                        "Notes": "Promising profile for chapter lead",
                        "Recruiter": "Zeynep HR",
                    },
                },
            },
            {
                "title": "Mehmet Demir - Junior Developer",
                "url": "https://linkedin.com/in/mehmetdemir",
                "location": "Ankara, Turkey",
                "search_bucket": "turkey",
                "text": "1 year internship experience.",
                "contacted_match": {
                    "match_type": "title_name",
                    "matched_key": "mehmet demir",
                    "recruiter_record": {
                        "Candidate Name": "Mehmet Demir",
                        "Status": "Rejected",
                        "Notes": "Too junior for this role",
                        "Recruiter": "Can HR",
                    },
                },
            },
        ]
        with open(data_dir / "contacted_search_hits.json", "w", encoding="utf-8") as f:
            json.dump(hits, f)

        return campaign_dir, config, hits

    def test_load_contacted_hits(self, setup_campaign):
        campaign_dir, config, hits = setup_campaign
        evaluator = ContactedCandidateEvaluator(campaign_dir, config)
        loaded = evaluator.load_contacted_hits()
        assert len(loaded) == 2
        assert loaded[0]["url"] == hits[0]["url"]
        assert loaded[1]["url"] == hits[1]["url"]

    def test_evaluate_and_record_workflow(self, setup_campaign, tmp_path: Path):
        campaign_dir, config, hits = setup_campaign
        evaluator = ContactedCandidateEvaluator(campaign_dir, config)

        # Mock CandidateFilter._review_candidate
        mock_filter_review = {
            "recommendation": "ACCEPT",
            "confidence": "HIGH",
            "key_strength": "Deep LLM and NLP mastery",
            "main_concern": "None",
            "reasoning": "Strong match against criteria",
        }

        with patch("filter.CandidateFilter._review_candidate", return_value={**hits[0], "ai_review": mock_filter_review}):
            evaluated = evaluator.evaluate_candidates(hits[:1])

        assert len(evaluated) == 1
        assert evaluated[0]["ai_review"]["recommendation"] == "ACCEPT"

        # Record evaluations
        count = evaluator.record_evaluations(evaluated)
        assert count == 1

        # Verify JSONL
        eval_path = Path(config["analysis"]["contacted_evaluations_path"])
        assert eval_path.exists()
        with open(eval_path, "r", encoding="utf-8") as f:
            lines = [json.loads(l) for l in f]
        assert len(lines) == 1
        record = lines[0]
        assert record["candidate_name"] == "Yiğit Can"
        assert record["ai_recommendation"] == "ACCEPT"
        assert record["hr_status"] == "Interviewed"
        assert record["alignment"] == "Aligned (Both Accepted/Interested)"

        # Verify Excel and CSV reports
        excel_path = Path(config["analysis"]["contacted_comparison_report_path"])
        assert excel_path.exists()
        df_excel = pd.read_excel(excel_path)
        assert len(df_excel) == 1
        assert "Candidate Name" in df_excel.columns
        assert "AI vs HR Alignment" in df_excel.columns
        assert df_excel.iloc[0]["Candidate Name"] == "Yiğit Can"

        csv_path = excel_path.with_suffix(".csv")
        assert csv_path.exists()
        df_csv = pd.read_csv(csv_path)
        assert len(df_csv) == 1
        assert df_csv.iloc[0]["AI Recommendation"] == "ACCEPT"

    def test_evaluate_candidates_with_ranking_scoring(self, setup_campaign):
        campaign_dir, config, hits = setup_campaign
        data_dir = campaign_dir / "data"

        # Write ranking artifacts
        schema = {
            "features": [
                {"id": "ml_experience", "name": "ML Experience", "max_points": 10},
            ]
        }
        policy = {
            "weights": {"ml_experience": 100},
            "hard_gates": [],
            "tiers": {"A": 85, "B": 70, "C": 55},
        }
        with open(data_dir / "ranking_feature_schema.json", "w", encoding="utf-8") as f:
            json.dump(schema, f)
        with open(data_dir / "ranking_scoring_policy.json", "w", encoding="utf-8") as f:
            json.dump(policy, f)

        evaluator = ContactedCandidateEvaluator(campaign_dir, config)

        mock_filter_review = {
            "recommendation": "ACCEPT",
            "confidence": "HIGH",
            "key_strength": "ML skills",
            "main_concern": "None",
            "reasoning": "Fits criteria",
        }
        mock_agent_score = {
            "feature_assessments": [
                {"feature_id": "ml_experience", "raw_points": 9, "max_points": 10}
            ],
            "gate_flags": [],
        }

        with patch("filter.CandidateFilter._review_candidate", return_value={**hits[0], "ai_review": mock_filter_review}):
            with patch("ranking.agents.candidate_scorer_agent.CandidateScorerAgent.score_candidate", return_value=mock_agent_score):
                evaluated = evaluator.evaluate_candidates(hits[:1])

        assert len(evaluated) == 1
        res = evaluated[0]
        assert res["ai_review"]["recommendation"] == "ACCEPT"
        assert res["total_score"] is not None
        # 9/10 * 100 = 90 + 3.0 (ACCEPT bonus) = 93.0
        assert res["total_score"] == 93.0
        assert res["grade"] == "A"



class TestSearchHitsIsolation:
    def test_search_saves_isolated_contacted_hits(self, tmp_path: Path):
        campaign_dir = tmp_path / "campaign"
        campaign_dir.mkdir(parents=True)
        (campaign_dir / "input").mkdir()

        excel_path = campaign_dir / "input" / "contacted_candidates.xlsx"
        df = pd.DataFrame({
            "Candidate Name": ["Yiğit Can"],
            "Status": ["Interviewed"],
            "Notes": ["Top candidate"],
        })
        with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
            df.to_excel(writer, index=False)

        config = {
            "name": "Search Isolation Test",
            "locations": [{"name": "turkey"}],
            "search": {"provider": "exa"},
            "dedup": {"contacted_candidates_path": "input/contacted_candidates.xlsx"},
        }

        searcher = ExaSearcher.__new__(ExaSearcher)
        searcher.campaign_dir = campaign_dir
        searcher.config = config
        searcher.search_cfg = config["search"]
        searcher.dedup_cfg = config["dedup"]
        searcher.provider = "exa"
        searcher.num_results = 10
        searcher.exa_category = "people"
        searcher.contents_cfg = {"text": True}
        searcher.exa = MagicMock()
        searcher._existing_urls = set()
        searcher._contacted_store = ContactedCandidatesStore(excel_path)
        searcher._query_generator = None

        searcher._load_queries_for_location = MagicMock(return_value=["mock query"])
        mock_results = [
            {"title": "Yiğit Can - Data Scientist | LinkedIn", "url": "https://linkedin.com/in/yigitcan"}, # Contacted
            {"title": "Ayşe Kaya - ML Engineer | LinkedIn", "url": "https://linkedin.com/in/aysekaya"},   # Retained
        ]
        searcher._execute_query_batch = MagicMock(return_value=mock_results)

        with patch("pipeline_status.write"):
            results = searcher.run()

        # Check results returned
        assert len(results["turkey"]) == 1
        assert results["turkey"][0]["url"] == "https://linkedin.com/in/aysekaya"

        # Check file outputs
        turkey_dir = campaign_dir / "data" / "turkey"
        raw_results_path = turkey_dir / "raw_results.json"
        hits_path = turkey_dir / "contacted_search_hits.json"

        assert raw_results_path.exists()
        with open(raw_results_path, encoding="utf-8") as f:
            raw_cands = json.load(f)
        assert len(raw_cands) == 1
        assert raw_cands[0]["url"] == "https://linkedin.com/in/aysekaya"

        # Check contacted hits were isolated into contacted_search_hits.json
        assert hits_path.exists()
        with open(hits_path, encoding="utf-8") as f:
            hits = json.load(f)
        assert len(hits) == 1
        assert hits[0]["url"] == "https://linkedin.com/in/yigitcan"
        assert hits[0]["contacted_match"]["recruiter_record"]["Status"] == "Interviewed"
