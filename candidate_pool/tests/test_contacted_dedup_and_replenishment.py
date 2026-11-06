"""Tests for contacted candidates filtering (Excel/CSV) and dynamic replenishment."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import yaml

# Allow importing candidate_pool scripts
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from contacted_candidates import (
    ContactedCandidatesStore,
    clean_candidate_name,
    extract_name_from_title,
    normalize_turkish_text,
    resolve_contacted_candidates_path,
)
from search import ExaSearcher


class TestTurkishTextNormalization:
    def test_turkish_char_transliteration(self):
        assert normalize_turkish_text("Yiğit Can Özkaya") == "yigit can ozkaya"
        assert normalize_turkish_text("yigit can ozkaya") == "yigit can ozkaya"
        assert normalize_turkish_text("YİĞİT CAN ÖZKAYA") == "yigit can ozkaya"
        assert normalize_turkish_text("Işıl Şen") == "isil sen"
        assert normalize_turkish_text("ISIL SEN") == "isil sen"
        assert normalize_turkish_text("İsmail Çetin") == "ismail cetin"
        assert normalize_turkish_text("Şaban Gül") == "saban gul"

    def test_clean_candidate_name_strips_honorifics(self):
        assert clean_candidate_name("Dr. Yiğit Can Özkaya") == "yigit can ozkaya"
        assert clean_candidate_name("Prof. Dr. Yiğit Can, PhD") == "yigit can"
        assert clean_candidate_name("Yiğit Can Özkaya MSc") == "yigit can ozkaya"

    def test_extract_name_from_title(self):
        assert extract_name_from_title("Yiğit Can Özkaya - Senior Data Scientist | LinkedIn") == "yigit can ozkaya"
        assert extract_name_from_title("Dr. Yiğit Can - Istanbul, Turkey | Professional Profile") == "yigit can"
        assert extract_name_from_title("Yigit Can | LinkedIn") == "yigit can"
        assert extract_name_from_title("Yiğit Can Özkaya: Lead AI Engineer") == "yigit can ozkaya"


class TestContactedCandidatesStore:
    def test_load_from_excel(self, tmp_path: Path):
        excel_path = tmp_path / "contacted.xlsx"
        df = pd.DataFrame(
            {
                "Candidate Name": ["Yiğit Can Özkaya", "Işıl Şen", "Ayşe Yılmaz"],
                "Status": ["Interviewed", "Contacted", "Rejected"],
            }
        )
        with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Sheet1", index=False)

        store = ContactedCandidatesStore(excel_path)
        assert not store.is_empty()
        assert "yigit can ozkaya" in store.contacted_names
        assert "isil sen" in store.contacted_names
        assert "ayse yilmaz" in store.contacted_names

    def test_matching_with_turkish_english_variations(self, tmp_path: Path):
        excel_path = tmp_path / "contacted.xlsx"
        df = pd.DataFrame({"Candidate Name": ["Yiğit Can"]})
        with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
            df.to_excel(writer, index=False)

        store = ContactedCandidatesStore(excel_path)

        # English variant in title
        cand1 = {
            "title": "Yigit Can - Data Scientist - TechCorp | LinkedIn",
            "url": "https://www.linkedin.com/in/yigitcan",
        }
        assert store.is_contacted(cand1) is True

        # Turkish variant in title
        cand2 = {
            "title": "Yiğit Can - Senior ML Engineer | LinkedIn",
            "url": "https://tr.linkedin.com/in/yigit-can-12345",
        }
        assert store.is_contacted(cand2) is True

        # Non-contacted candidate
        cand3 = {
            "title": "Can Yiğit - Software Engineer | LinkedIn",
            "url": "https://www.linkedin.com/in/canyigit",
        }
        assert store.is_contacted(cand3) is False

        # Partial word should not match
        cand4 = {
            "title": "Yigit Caner - Data Scientist | LinkedIn",
            "url": "https://www.linkedin.com/in/yigitcaner",
        }
        assert store.is_contacted(cand4) is False

    def test_matching_by_linkedin_slug(self, tmp_path: Path):
        excel_path = tmp_path / "contacted.xlsx"
        df = pd.DataFrame({"Candidate Name": ["Yiğit Can Özkaya"]})
        with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
            df.to_excel(writer, index=False)

        store = ContactedCandidatesStore(excel_path)

        # Title doesn't have standard format, but URL contains the slug
        cand = {
            "title": "Staff Member Profile Overview",
            "url": "https://www.linkedin.com/in/yigit-can-ozkaya-84729/",
        }
        assert store.is_contacted(cand) is True


class TestReplenishmentWorkflow:
    def test_replenishment_loop_reaches_target_count(self, tmp_path: Path):
        campaign_dir = tmp_path / "campaign"
        campaign_dir.mkdir(parents=True)
        (campaign_dir / "input").mkdir()
        (campaign_dir / "data").mkdir()

        # Write contacted Excel file with 2 candidates
        excel_path = campaign_dir / "input" / "contacted_candidates.xlsx"
        df = pd.DataFrame({"Candidate Name": ["Yiğit Can", "Ayşe Demir"]})
        with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
            df.to_excel(writer, index=False)

        config = {
            "name": "Test Campaign",
            "locations": [{"name": "turkey"}],
            "search": {
                "provider": "exa",
                "max_replenish_queries": 10,
            },
            "dedup": {
                "contacted_candidates_path": "input/contacted_candidates.xlsx",
            },
        }

        # Mock QueryGenerator
        mock_qgen = MagicMock()
        # Returns replenishment query
        mock_qgen.generate_single_query.side_effect = [
            "replenish query 1",
            "replenish query 2",
        ]

        searcher = ExaSearcher.__new__(ExaSearcher)
        searcher.campaign_dir = campaign_dir
        searcher.config = config
        searcher.search_cfg = config["search"]
        searcher.dedup_cfg = config["dedup"]
        searcher.provider = "exa"
        searcher.num_results = 30
        searcher.exa_category = "people"
        searcher.contents_cfg = {"text": True}
        searcher.exa = MagicMock()
        searcher._existing_urls = set()
        searcher._contacted_store = ContactedCandidatesStore(excel_path)
        searcher._query_generator = mock_qgen

        # Initial candidates returned by initial queries: 5 candidates, 2 are in contacted list
        initial_pool = [
            {"title": "Yigit Can - Data Scientist | LinkedIn", "url": "https://linkedin.com/in/yigitcan"}, # Contacted
            {"title": "Ayşe Demir - ML Engineer | LinkedIn", "url": "https://linkedin.com/in/aysedemir"}, # Contacted
            {"title": "Cem Yılmaz - Senior AI Engineer | LinkedIn", "url": "https://linkedin.com/in/cemyilmaz"},
            {"title": "Zeynep Kaya - Lead Data Scientist | LinkedIn", "url": "https://linkedin.com/in/zeynepkaya"},
            {"title": "Ahmet Ak - NLP Researcher | LinkedIn", "url": "https://linkedin.com/in/ahmetak"},
        ]
        # Total initial = 5. After eliminating 2, retained = 3.
        # Target count to replenish = 5.

        # Single replenishment search query results:
        # Round 1 returns 2 candidates (1 new valid, 1 contacted):
        replenish_batch_1 = [
            {"title": "Yigit Can - Lead Engineer", "url": "https://linkedin.com/in/yigitcan2"}, # Contacted again
            {"title": "Mehmet Oz - Data Scientist | LinkedIn", "url": "https://linkedin.com/in/mehmetoz"}, # Valid (now 4)
        ]
        # Round 2 returns 2 new valid candidates:
        replenish_batch_2 = [
            {"title": "Burak Demir - AI Engineer | LinkedIn", "url": "https://linkedin.com/in/burakdemir"}, # Valid (now 5)
            {"title": "Elif Koc - ML Specialist | LinkedIn", "url": "https://linkedin.com/in/elifkoc"}, # Valid (now 6)
        ]

        def fake_search_query(query: str, loc_name: str, seen: set):
            if query == "initial query":
                for c in initial_pool:
                    seen.add(c["url"])
                return list(initial_pool)
            elif query == "replenish query 1":
                for c in replenish_batch_1:
                    seen.add(c["url"])
                return list(replenish_batch_1)
            elif query == "replenish query 2":
                for c in replenish_batch_2:
                    seen.add(c["url"])
                return list(replenish_batch_2)
            return []

        searcher._search_query = fake_search_query

        with patch("pipeline_status.write"):
            candidates, queries_used = searcher.search_location(
                {"name": "turkey"},
                queries=["initial query"],
            )

        # Initial was 5. Contacted candidates (Yigit Can, Ayse Demir) eliminated.
        # Round 1 added 1 valid (total 4 < 5).
        # Round 2 added 2 valid (total 6 >= 5).
        # Final candidate count must be >= initial count (5).
        assert len(candidates) == 6
        assert len(candidates) >= 5

        # Verify none of the retained candidates match the contacted list
        for c in candidates:
            assert searcher.contacted_store.is_contacted(c) is False

        # Verify all queries used includes the replenishment queries
        assert queries_used == ["initial query", "replenish query 1", "replenish query 2"]
        assert mock_qgen.generate_single_query.call_count == 2

    def test_replenishment_respects_max_queries_safeguard(self, tmp_path: Path):
        campaign_dir = tmp_path / "campaign"
        campaign_dir.mkdir(parents=True)
        (campaign_dir / "input").mkdir()

        excel_path = campaign_dir / "input" / "contacted_candidates.xlsx"
        df = pd.DataFrame({"Candidate Name": ["Yiğit Can"]})
        with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
            df.to_excel(writer, index=False)

        config = {
            "name": "Test Campaign",
            "locations": [{"name": "turkey"}],
            "search": {
                "provider": "exa",
                "max_replenish_queries": 3,  # Cap at 3
            },
            "dedup": {
                "contacted_candidates_path": "input/contacted_candidates.xlsx",
            },
        }

        mock_qgen = MagicMock()
        mock_qgen.generate_single_query.return_value = "query"

        searcher = ExaSearcher.__new__(ExaSearcher)
        searcher.campaign_dir = campaign_dir
        searcher.config = config
        searcher.search_cfg = config["search"]
        searcher.dedup_cfg = config["dedup"]
        searcher.provider = "exa"
        searcher.num_results = 30
        searcher.exa_category = "people"
        searcher.contents_cfg = {"text": True}
        searcher.exa = MagicMock()
        searcher._existing_urls = set()
        searcher._contacted_store = ContactedCandidatesStore(excel_path)
        searcher._query_generator = mock_qgen

        # 2 initial candidates, 1 contacted -> retained 1, target 2
        initial_pool = [
            {"title": "Yigit Can - Data Scientist", "url": "https://linkedin.com/in/yigitcan"},
            {"title": "Valid Candidate", "url": "https://linkedin.com/in/valid"},
        ]

        # Replenishment queries yield nothing new
        def fake_search_query(query: str, loc_name: str, seen: set):
            if query == "initial":
                return list(initial_pool)
            return []

        searcher._search_query = fake_search_query

        with patch("pipeline_status.write"):
            candidates, queries_used = searcher.search_location(
                {"name": "turkey"},
                queries=["initial"],
            )

        # Loop must stop when consecutive empty queries safeguard hits or max_replenish hit
        assert len(candidates) == 1
        assert len(queries_used) <= 4  # initial + at most 3 replenishment queries

    def test_load_from_csv(self, tmp_path: Path):
        csv_path = tmp_path / "contacted.csv"
        df = pd.DataFrame({"candidate_name": ["Mehmet Ali", "Ayşe Gök"]})
        df.to_csv(csv_path, index=False)

        store = ContactedCandidatesStore(csv_path)
        assert not store.is_empty()
        assert "mehmet ali" in store.contacted_names
        assert "ayse gok" in store.contacted_names

    def test_load_from_multisheet_excel(self, tmp_path: Path):
        excel_path = tmp_path / "contacted.xlsx"
        df1 = pd.DataFrame({"Candidate Name": ["Yiğit Can"]})
        df2 = pd.DataFrame({"Candidate Name": ["Ahmet Can"]})
        with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
            df1.to_excel(writer, sheet_name="October", index=False)
            df2.to_excel(writer, sheet_name="November", index=False)

        store = ContactedCandidatesStore(excel_path)
        assert "yigit can" in store.contacted_names
        assert "ahmet can" in store.contacted_names

    def test_resolve_contacted_candidates_path(self, tmp_path: Path):
        campaign_dir = tmp_path / "camp"
        campaign_dir.mkdir(parents=True)
        input_dir = campaign_dir / "input"
        input_dir.mkdir()

        # 1. Configured path
        config = {"dedup": {"contacted_candidates_path": "input/custom.xlsx"}}
        (input_dir / "custom.xlsx").touch()
        assert resolve_contacted_candidates_path(campaign_dir, config) == input_dir / "custom.xlsx"

        # 2. Fallback to default input/contacted_candidates.xlsx
        config_empty = {}
        (input_dir / "contacted_candidates.xlsx").touch()
        assert resolve_contacted_candidates_path(campaign_dir, config_empty) == input_dir / "contacted_candidates.xlsx"

    def test_single_query_generation(self, tmp_path: Path):
        from generate_queries import QueryGenerator

        campaign_dir = tmp_path / "camp"
        campaign_dir.mkdir(parents=True)
        input_dir = campaign_dir / "input"
        input_dir.mkdir()
        (input_dir / "job_description.md").write_text("Senior Data Scientist NLP role")
        (input_dir / "filter_criteria.md").write_text("Must have Python and NLP experience")

        config = {
            "query_generation": {"model": "claude-sonnet-5"},
            "locations": [{"name": "turkey"}],
        }

        with patch("generate_queries.call_model_text") as mock_call:
            mock_call.return_value = '["senior data scientist NLP Turkey not working at ING"]'
            qgen = QueryGenerator(campaign_dir, config)
            query = qgen.generate_single_query(
                "turkey",
                existing_queries=["data scientist Turkey not working at ING"],
            )

        assert query == "senior data scientist NLP Turkey not working at ING"
        mock_call.assert_called_once()
        prompt_arg = mock_call.call_args[1]["prompt"]
        assert "data scientist Turkey not working at ING" in prompt_arg
        assert "Previous Queries Already Used" in prompt_arg

