"""Tests for multi-platform candidate searchers (GitHub, Hugging Face, Kaggle).

Covers:
1. Security guards (SSRF host/scheme allowlisting, path-traversal identifier checks,
   ING employee exclusion without false positives on words ending in 'ing').
2. Activity recency verification (`is_recently_active` and `activity_days` filtering).
3. GitHubCandidateSearcher: active vs. dormant developer filtering, repo aggregation.
4. HuggingFaceCandidateSearcher: active model/dataset author discovery and enrichment.
5. KaggleCandidateSearcher: both official Kaggle REST API and Exa domain-scoped channels.
6. End-to-end integration with `ExaSearcher`, contacted-candidate elimination, and replenishment.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# Allow importing candidate_pool scripts
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from contacted_candidates import ContactedCandidatesStore
from platform_searchers import (
    GitHubCandidateSearcher,
    HuggingFaceCandidateSearcher,
    KaggleCandidateSearcher,
    MultiPlatformCandidateSearcher,
    extract_search_keywords,
    is_ing_affiliated,
    is_recently_active,
    is_valid_identifier,
    validate_safe_https_url,
)
from search import ExaSearcher

FIXED_NOW = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)


class TestSecurityAndValidationHelpers:
    """Verify SSRF prevention, identifier sanitization, and ING employer detection."""

    def test_validate_safe_https_url_allows_trusted_hosts(self):
        assert (
            validate_safe_https_url("https://api.github.com/search/users?q=ml")
            == "https://api.github.com/search/users?q=ml"
        )
        assert (
            validate_safe_https_url("https://huggingface.co/api/models")
            == "https://huggingface.co/api/models"
        )
        assert (
            validate_safe_https_url("https://www.kaggle.com/api/v1/kernels/list")
            == "https://www.kaggle.com/api/v1/kernels/list"
        )

    def test_validate_safe_https_url_blocks_ssrf_and_insecure_schemes(self):
        # Block plain HTTP
        with pytest.raises(ValueError, match="only 'https' is allowed"):
            validate_safe_https_url("http://api.github.com/users/octocat")

        # Block file:// scheme
        with pytest.raises(ValueError, match="only 'https' is allowed"):
            validate_safe_https_url("file:///etc/passwd")

        # Block untrusted hosts / internal metadata endpoints
        with pytest.raises(ValueError, match="not in ALLOWED_HTTPS_HOSTS"):
            validate_safe_https_url("https://169.254.169.254/latest/meta-data/")

        with pytest.raises(ValueError, match="not in ALLOWED_HTTPS_HOSTS"):
            validate_safe_https_url("https://evil.example.com/api")

    def test_is_valid_identifier_blocks_traversal_and_injection(self):
        assert is_valid_identifier("ahmet-yilmaz_99") is True
        assert is_valid_identifier("turkish.nlp") is True
        assert is_valid_identifier("../admin") is False
        assert is_valid_identifier("user/../../etc") is False
        assert is_valid_identifier("user?admin=true") is False
        assert is_valid_identifier("user name") is False
        assert is_valid_identifier("") is False

    def test_is_ing_affiliated_detects_ing_without_false_positives(self):
        assert is_ing_affiliated("ING Bank Turkey") is True
        assert is_ing_affiliated("Senior Data Scientist at ING Hubs Türkiye") is True
        assert is_ing_affiliated("Staff Engineer @ING") is True
        # Must NOT trigger on words containing 'ing' as a substring
        assert is_ing_affiliated("Machine Learning Engineering Lead") is False
        assert is_ing_affiliated("Boston Consulting Group") is False
        assert is_ing_affiliated("Turing AI Institute") is False

    def test_extract_search_keywords_strips_negative_clauses(self):
        raw = "Senior Machine Learning Engineer NLP PyTorch Turkey excluding ING employees"
        keywords = extract_search_keywords(raw, location_name="turkey", max_terms=6)
        tokens_lower = keywords.lower().split()
        assert "excluding" not in tokens_lower
        assert "ing" not in tokens_lower
        assert "Machine" in keywords
        assert "NLP" in keywords
        assert "PyTorch" in keywords


class TestActivityRecencyCheck:
    """Verify activity_days cutoff enforcement."""

    def test_is_recently_active_within_and_outside_window(self):
        # 20 days before FIXED_NOW (2026-11-01) -> active within 180 days
        assert is_recently_active("2026-10-12T10:00:00Z", 180, now=FIXED_NOW) is True
        # 150 days before FIXED_NOW -> active within 180 days
        assert is_recently_active("2026-06-15T00:00:00Z", 180, now=FIXED_NOW) is True
        # 250 days before FIXED_NOW -> inactive (> 180 days)
        assert is_recently_active("2026-01-15T00:00:00Z", 180, now=FIXED_NOW) is False
        # Invalid or missing timestamp -> False
        assert is_recently_active(None, 180, now=FIXED_NOW) is False
        assert is_recently_active("not-a-date", 180, now=FIXED_NOW) is False


class TestGitHubCandidateSearcher:
    """Verify GitHub candidate discovery, activity verification, and ING exclusion."""

    def test_github_search_retains_active_and_filters_dormant_and_ing(self):
        searcher = GitHubCandidateSearcher(
            api_token="test-token",
            activity_days=180,
            num_results=10,
            require_recent_activity=True,
        )

        def fake_json_get(url: str, **kwargs):
            if "/search/users?" in url:
                return {
                    "items": [
                        {"login": "active-ml-dev"},
                        {"login": "dormant-dev"},
                        {"login": "ing-internal-dev"},
                    ]
                }
            if url.endswith("/users/active-ml-dev"):
                return {
                    "login": "active-ml-dev",
                    "name": "Deniz Kaya",
                    "bio": "Staff ML & NLP Engineer",
                    "company": "Trendyol",
                    "location": "Istanbul, Turkey",
                    "blog": "https://denizkaya.dev",
                    "followers": 140,
                    "public_repos": 24,
                    "updated_at": "2026-10-20T12:00:00Z",
                }
            if "/users/active-ml-dev/repos?" in url:
                return [
                    {
                        "name": "turkish-llm-rag",
                        "description": "Production RAG pipeline for Turkish LLMs",
                        "language": "Python",
                        "stargazers_count": 85,
                        "pushed_at": "2026-10-25T09:30:00Z",
                    },
                    {
                        "name": "bert-ner-tr",
                        "description": "Named Entity Recognition with Transformers",
                        "language": "Python",
                        "stargazers_count": 42,
                        "pushed_at": "2026-08-10T14:00:00Z",
                    },
                ]
            if url.endswith("/users/dormant-dev"):
                return {
                    "login": "dormant-dev",
                    "name": "Eski Hesap",
                    "bio": "Data Scientist",
                    "company": "Acme",
                    "location": "Ankara, Turkey",
                    "followers": 10,
                    "public_repos": 2,
                    "updated_at": "2023-01-01T00:00:00Z",
                }
            if "/users/dormant-dev/repos?" in url:
                return [
                    {
                        "name": "old-project",
                        "description": "Old repo",
                        "language": "Python",
                        "stargazers_count": 1,
                        "pushed_at": "2023-05-01T10:00:00Z",
                    }
                ]
            if url.endswith("/users/ing-internal-dev"):
                return {
                    "login": "ing-internal-dev",
                    "name": "Internal Employee",
                    "bio": "ML Engineer at ING Hubs Türkiye",
                    "company": "ING Bank",
                    "location": "Istanbul",
                }
            return None

        seen: set[str] = set()
        with patch("platform_searchers.safe_json_get", side_effect=fake_json_get):
            results = searcher.search_query(
                "Senior ML Engineer NLP PyTorch Turkey excluding ING",
                "turkey",
                seen,
                now=FIXED_NOW,
            )

        # Only 'active-ml-dev' should be returned (dormant-dev is inactive, ing-internal-dev works at ING)
        assert len(results) == 1
        cand = results[0]
        assert cand["url"] == "https://github.com/active-ml-dev"
        assert cand["name"] == "Deniz Kaya"
        assert cand["source"] == "github"
        assert cand["info"]["active_repos_count"] == 2
        assert cand["info"]["total_stars"] == 127
        assert "Python" in cand["info"]["top_languages"]
        assert "turkish-llm-rag" in cand["text"]


class TestHuggingFaceCandidateSearcher:
    """Verify Hugging Face active model/dataset contributor discovery."""

    def test_huggingface_search_discovers_active_authors(self):
        searcher = HuggingFaceCandidateSearcher(
            activity_days=180,
            num_results=10,
            require_recent_activity=True,
        )

        def fake_json_get(url: str, **kwargs):
            if "/api/models?" in url:
                return [
                    {
                        "id": "selim-nlp/turkish-llama-3-8b",
                        "author": "selim-nlp",
                        "pipeline_tag": "text-generation",
                        "downloads": 4200,
                        "likes": 65,
                        "lastModified": "2026-10-18T15:20:00Z",
                    },
                    {
                        "id": "inactive-user/old-bert-2021",
                        "author": "inactive-user",
                        "pipeline_tag": "fill-mask",
                        "downloads": 50,
                        "likes": 2,
                        "lastModified": "2021-04-10T00:00:00Z",
                    },
                ]
            if "/api/datasets?" in url:
                return [
                    {
                        "id": "selim-nlp/tr-instruct-dataset",
                        "author": "selim-nlp",
                        "downloads": 1800,
                        "likes": 30,
                        "lastModified": "2026-09-12T11:00:00Z",
                    }
                ]
            if url.endswith("/api/users/selim-nlp/overview"):
                return {
                    "fullname": "Selim Arslan",
                    "bio": "NLP Researcher building Turkish LLMs and instruction datasets",
                }
            return {}

        seen: set[str] = set()
        with patch("platform_searchers.safe_json_get", side_effect=fake_json_get):
            results = searcher.search_query(
                "Senior NLP Engineer LLM Transformers Turkey excluding ING",
                "turkey",
                seen,
                now=FIXED_NOW,
            )

        assert len(results) == 1
        cand = results[0]
        assert cand["url"] == "https://huggingface.co/selim-nlp"
        assert cand["name"] == "Selim Arslan"
        assert cand["source"] == "huggingface"
        assert cand["info"]["active_artifacts_count"] == 2
        assert cand["info"]["total_downloads"] == 6000
        assert cand["info"]["total_likes"] == 95
        assert "turkish-llama-3-8b" in cand["text"]


class TestKaggleCandidateSearcher:
    """Verify Kaggle candidate discovery via official API and Exa domain fallback."""

    def test_kaggle_api_channel_filters_by_recent_kernel_execution(self):
        searcher = KaggleCandidateSearcher(
            kaggle_api_token="",
            kaggle_username="test_user",
            kaggle_key="test_secret_key",
            activity_days=180,
            num_results=10,
            require_recent_activity=True,
        )

        def fake_json_get(url: str, **kwargs):
            if "/api/v1/kernels/list?" in url:
                return [
                    {
                        "ref": "merve-ds/llm-fine-tuning-guide",
                        "title": "LLM Fine-Tuning Guide with LoRA",
                        "author": "Merve Özkan",
                        "lastRunTime": "2026-10-05T18:00:00Z",
                        "totalVotes": 48,
                    },
                    {
                        "ref": "stale-user/titanic-2019",
                        "title": "Titanic Starter",
                        "author": "Stale User",
                        "lastRunTime": "2019-03-11T00:00:00Z",
                        "totalVotes": 5,
                    },
                ]
            return []

        seen: set[str] = set()
        with patch("platform_searchers.safe_json_get", side_effect=fake_json_get):
            results = searcher.search_query(
                "Senior Data Scientist LLM Turkey",
                "turkey",
                seen,
                now=FIXED_NOW,
            )

        assert len(results) == 1
        cand = results[0]
        assert cand["url"] == "https://www.kaggle.com/merve-ds"
        assert cand["name"] == "Merve Özkan"
        assert cand["source"] == "kaggle"
        assert cand["info"]["votes"] == 48

    def test_kaggle_api_token_bearer_auth_without_username(self):
        searcher = KaggleCandidateSearcher(
            kaggle_api_token="KGAT_test_bearer_token_1234",
            kaggle_username="",
            kaggle_key="",
            activity_days=180,
            num_results=10,
            require_recent_activity=True,
        )
        assert searcher._has_kaggle_api_credentials() is True
        headers = searcher._kaggle_auth_headers()
        assert headers["Authorization"] == "Bearer KGAT_test_bearer_token_1234"

    def test_kaggle_exa_domain_channel(self):
        mock_exa = MagicMock()
        mock_hit = MagicMock()
        mock_hit.url = "https://www.kaggle.com/baris-grandmaster"
        mock_hit.title = "Barış Yıldırım - Kaggle Competitions Grandmaster"
        mock_hit.score = 0.88
        mock_hit.published_date = "2026-09-20"
        mock_hit.text = "Kaggle Competitions Grandmaster (#14 Globally). Senior ML Engineer in Istanbul."
        mock_hit.highlights = ["Kaggle Competitions Grandmaster with 5 gold medals in NLP challenges."]
        mock_hit.highlight_scores = [0.9]
        mock_exa.search.return_value = MagicMock(results=[mock_hit])

        searcher = KaggleCandidateSearcher(
            exa_client=mock_exa,
            kaggle_api_token="",
            kaggle_username="",
            kaggle_key="",
            activity_days=180,
            num_results=5,
        )

        seen: set[str] = set()
        results = searcher.search_query(
            "Senior ML Engineer NLP Turkey",
            "turkey",
            seen,
            now=FIXED_NOW,
        )

        assert len(results) == 1
        assert results[0]["url"] == "https://www.kaggle.com/baris-grandmaster"
        assert results[0]["source"] == "kaggle"
        mock_exa.search.assert_called_once()
        _, call_kwargs = mock_exa.search.call_args
        assert call_kwargs["include_domains"] == ["kaggle.com", "www.kaggle.com"]


class TestEndToEndMultiPlatformAndContactedIntegration:
    """Verify ExaSearcher integration with community platforms and contacted deduplication."""

    def test_exasearcher_multi_platform_and_contacted_filtering(self, tmp_path: Path):
        campaign_dir = tmp_path / "campaign"
        campaign_dir.mkdir(parents=True)
        (campaign_dir / "input").mkdir()
        (campaign_dir / "data").mkdir()

        # Contacted spreadsheet includes a candidate who will appear on GitHub
        excel_path = campaign_dir / "input" / "contacted_candidates.xlsx"
        df = pd.DataFrame(
            {
                "Candidate Name": ["Yiğit Can Özkaya"],
                "GitHub": ["https://github.com/yigit-can-ozkaya"],
            }
        )
        with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
            df.to_excel(writer, index=False)

        config = {
            "name": "Multi Platform Test",
            "locations": [{"name": "turkey", "queries": ["Senior ML Engineer NLP Turkey"]}],
            "search": {
                "provider": "multi",
                "platforms": ["github", "huggingface", "kaggle"],
                "activity_days": 180,
                "num_results_per_platform": 5,
            },
            "dedup": {
                "contacted_candidates_path": "input/contacted_candidates.xlsx",
            },
        }

        searcher = ExaSearcher(campaign_dir, config)
        assert searcher.platform_searcher is not None

        mock_platform_results = [
            {
                "url": "https://github.com/yigit-can-ozkaya",
                "title": "Yiğit Can Özkaya - ML Engineer",
                "name": "Yiğit Can Özkaya",
                "source": "github",
            },
            {
                "url": "https://github.com/deniz-kaya",
                "title": "Deniz Kaya - Staff ML Engineer",
                "name": "Deniz Kaya",
                "source": "github",
            },
            {
                "url": "https://huggingface.co/selim-nlp",
                "title": "Selim Arslan - Hugging Face Contributor",
                "name": "Selim Arslan",
                "source": "huggingface",
            },
            {
                "url": "https://www.kaggle.com/merve-ds",
                "title": "Merve Özkan - Kaggle Competitor",
                "name": "Merve Özkan",
                "source": "kaggle",
            },
        ]

        searcher.platform_searcher.search_query = MagicMock(return_value=mock_platform_results)
        # Disable replenishment query gen for this check
        searcher._query_generator = None

        with patch("pipeline_status.write"):
            candidates, _ = searcher.search_location(
                {"name": "turkey"},
                queries=["Senior ML Engineer NLP Turkey"],
            )

        # Yiğit Can Özkaya was in contacted_candidates.xlsx and must be eliminated!
        urls = [c["url"] for c in candidates]
        assert "https://github.com/yigit-can-ozkaya" not in urls
        assert "https://github.com/deniz-kaya" in urls
        assert "https://huggingface.co/selim-nlp" in urls
        assert "https://www.kaggle.com/merve-ds" in urls
        assert len(candidates) == 3
