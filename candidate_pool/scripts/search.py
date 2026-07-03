"""Parameterized Exa.ai candidate search."""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from exa_py import Exa

load_dotenv()

logger = logging.getLogger(__name__)


class ExaSearcher:
    def __init__(self, campaign_dir: Path, config: dict[str, Any]) -> None:
        self.campaign_dir = campaign_dir
        self.config = config
        self.search_cfg = config.get("search", {})
        self.dedup_cfg = config.get("dedup", {})
        self.provider = str(
            self.search_cfg.get("provider")
            or self.search_cfg.get("search_api")
            or self.search_cfg.get("api")
            or "exa"
        ).strip().lower()
        self.num_results = self.search_cfg.get("num_results_per_query", 30)
        self.exa_category = self.search_cfg.get("category", "people")
        self.contents_cfg = self.search_cfg.get("contents", {"text": True})

        self.exa: Exa | None = None
        self.pdl_api_key: str | None = None
        self.apollo_api_key: str | None = None

        if self.provider == "exa":
            api_key = os.environ.get("EXA_API_KEY")
            if not api_key:
                raise ValueError("EXA_API_KEY not set in environment")
            self.exa = Exa(api_key)
        elif self.provider == "peopledatalabs":
            self.pdl_api_key = os.environ.get("DATALABS_API_KEY")
            if not self.pdl_api_key:
                raise ValueError("DATALABS_API_KEY not set in environment")
        elif self.provider == "apollo":
            self.apollo_api_key = os.environ.get("APOLLO_API_KEY")
            if not self.apollo_api_key:
                raise ValueError("APOLLO_API_KEY not set in environment")
        else:
            raise ValueError(
                "search.provider must be one of: exa, peopledatalabs, apollo"
            )

        self._existing_urls: set[str] = self._load_existing_pool()

    def _load_existing_pool(self) -> set[str]:
        pool_path_str = self.dedup_cfg.get("existing_pool_path")
        if not pool_path_str:
            return set()
        pool_path = self.campaign_dir / pool_path_str
        if not pool_path.exists():
            logger.warning("Existing pool not found: %s", pool_path)
            return set()
        with open(pool_path) as f:
            pool = json.load(f)
        urls = set()
        for item in pool:
            url = item.get("url") if isinstance(item, dict) else item
            if url:
                urls.add(url)
        logger.info("Loaded %d existing candidates for dedup", len(urls))
        return urls

    def _build_pdl_sql_queries(self, location: str) -> list[str]:
        location_clauses = []
        loc = location.replace("'", "''").strip()
        if loc:
            location_clauses.append(f"location_country = '{loc.lower()}'")
            location_clauses.append(f"location_locality LIKE '%{loc}%'")
            location_clauses.append(f"location_name LIKE '%{loc}%'")

        location_sql = ""
        if location_clauses:
            location_sql = "(" + " OR ".join(location_clauses) + ") AND "

        return [
            (
                "SELECT * FROM person WHERE "
                f"{location_sql}"
                "(job_title LIKE '%senior data scientist%' OR job_title LIKE '%staff data scientist%' OR job_title LIKE '%principal data scientist%')"
            ),
            (
                "SELECT * FROM person WHERE "
                f"{location_sql}"
                "(job_title LIKE '%senior machine learning engineer%' OR job_title LIKE '%staff machine learning engineer%' OR job_title LIKE '%principal machine learning engineer%')"
            ),
            (
                "SELECT * FROM person WHERE "
                f"{location_sql}"
                "(job_title LIKE '%senior ai engineer%' OR job_title LIKE '%lead ai engineer%' OR job_title LIKE '%principal ai engineer%')"
            ),
            (
                "SELECT * FROM person WHERE "
                f"{location_sql}"
                "(job_title LIKE '%nlp%' OR job_title LIKE '%natural language processing%') "
                "AND (job_title LIKE '%senior%' OR job_title LIKE '%staff%' OR job_title LIKE '%principal%' OR job_title LIKE '%lead%')"
            ),
            (
                "SELECT * FROM person WHERE "
                f"{location_sql}"
                "(job_title LIKE '%research scientist%' OR job_title LIKE '%applied scientist%') "
                "AND (job_title LIKE '%machine learning%' OR job_title LIKE '%ai%' OR job_title LIKE '%nlp%')"
            ),
            (
                "SELECT * FROM person WHERE "
                f"{location_sql}"
                "(job_title LIKE '%data scientist%' OR job_title LIKE '%machine learning engineer%' OR job_title LIKE '%ai engineer%') "
                "AND (job_title LIKE '%senior%' OR job_title LIKE '%staff%' OR job_title LIKE '%principal%' OR job_title LIKE '%lead%')"
            ),
            (
                "SELECT * FROM person WHERE "
                f"{location_sql}"
                "(job_title LIKE '%llm%' OR job_title LIKE '%genai%' OR job_title LIKE '%generative ai%' OR job_title LIKE '%language model%') "
                "AND (job_title LIKE '%engineer%' OR job_title LIKE '%scientist%')"
            ),
        ]

    def _build_apollo_query_params(self, location: str) -> list[dict[str, Any]]:
        common_seniorities = ["senior", "director", "vp", "head"]
        queries: list[dict[str, Any]] = [
            {
                "person_titles": [
                    "senior data scientist",
                    "staff data scientist",
                    "principal data scientist",
                    "lead data scientist",
                ],
                "person_seniorities": common_seniorities,
                "include_similar_titles": True,
            },
            {
                "person_titles": [
                    "senior machine learning engineer",
                    "staff machine learning engineer",
                    "principal machine learning engineer",
                    "lead machine learning engineer",
                ],
                "person_seniorities": common_seniorities,
                "include_similar_titles": True,
            },
            {
                "person_titles": [
                    "senior ai engineer",
                    "lead ai engineer",
                    "principal ai engineer",
                    "senior artificial intelligence engineer",
                ],
                "person_seniorities": common_seniorities,
                "include_similar_titles": True,
            },
            {
                "person_titles": [
                    "senior nlp engineer",
                    "senior natural language processing engineer",
                    "nlp scientist",
                    "nlp researcher",
                ],
                "person_seniorities": common_seniorities,
                "include_similar_titles": True,
            },
            {
                "person_titles": [
                    "research scientist",
                    "applied scientist",
                    "principal scientist",
                ],
                "person_seniorities": common_seniorities,
                "q_keywords": "machine learning OR ai OR llm OR deep learning",
                "include_similar_titles": True,
            },
            {
                "person_titles": [
                    "llm engineer",
                    "generative ai engineer",
                    "foundation model engineer",
                    "prompt engineer",
                    "ai engineer",
                ],
                "person_seniorities": common_seniorities,
                "include_similar_titles": True,
            },
            {
                "person_titles": [
                    "senior engineer",
                    "staff engineer",
                    "principal engineer",
                    "lead engineer",
                ],
                "person_seniorities": common_seniorities,
                "q_keywords": "machine learning OR ai OR deep learning OR neural networks",
                "include_similar_titles": True,
            },
        ]

        if not location:
            return queries

        for q in queries:
            q["person_locations"] = [location]
        return queries

    def _pdl_search_request(self, sql_query: str) -> dict[str, Any]:
        if not self.pdl_api_key:
            raise RuntimeError("DATALABS_API_KEY not configured")

        payload = {
            "sql": sql_query,
            "size": self.num_results,
            "pretty": True,
        }
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            "https://api.peopledatalabs.com/v5/person/search",
            data=data,
            headers={
                "Content-Type": "application/json",
                "X-Api-Key": self.pdl_api_key,
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = response.read()
                return json.loads(body.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            logger.error("PDL API HTTP %s: %s", exc.code, body[:500])
        except urllib.error.URLError:
            logger.exception("PDL API network error")
        return {}

    def _apollo_search_request(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self.apollo_api_key:
            raise RuntimeError("APOLLO_API_KEY not configured")

        request_params = {
            "page": 1,
            "per_page": self.num_results,
            **params,
        }

        query_parts: list[str] = []
        for key, value in request_params.items():
            if isinstance(value, list):
                for item in value:
                    query_parts.append(
                        f"{key}[]={urllib.parse.quote(str(item), safe='')}"
                    )
            else:
                query_parts.append(
                    f"{key}={urllib.parse.quote(str(value), safe='')}"
                )

        full_url = (
            "https://api.apollo.io/api/v1/mixed_people/api_search?"
            + "&".join(query_parts)
        )
        request = urllib.request.Request(
            full_url,
            headers={
                "Content-Type": "application/json",
                "Cache-Control": "no-cache",
                "Accept": "application/json",
                "X-Api-Key": self.apollo_api_key,
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = response.read()
                return json.loads(body.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            logger.error("Apollo API HTTP %s: %s", exc.code, body[:500])
        except urllib.error.URLError:
            logger.exception("Apollo API network error")
        return {}

    def _convert_pdl_record(self, record: dict[str, Any], query: str, loc_name: str) -> dict[str, Any]:
        def safe_str(value: Any) -> str:
            if value is None:
                return ""
            if isinstance(value, str):
                return value
            return str(value)

        url = ""
        for key in ["linkedin_url", "url", "twitter_url", "github_url"]:
            val = safe_str(record.get(key)).strip()
            if val:
                url = val
                break
        if not url:
            record_id = safe_str(record.get("id")).strip()
            url = f"pdl://person/{record_id}" if record_id else ""

        full_name = safe_str(record.get("full_name")).strip()
        if not full_name:
            first = safe_str(record.get("first_name")).strip()
            last = safe_str(record.get("last_name")).strip()
            full_name = " ".join(part for part in [first, last] if part).strip()

        job_title = safe_str(record.get("job_title")).strip()
        title = (
            f"{full_name} - {job_title}"
            if full_name and job_title
            else (full_name or job_title or "Unknown")
        )

        location_parts = [
            safe_str(record.get("location_locality")),
            safe_str(record.get("location_region")),
            safe_str(record.get("location_country")),
        ]
        location_text = ", ".join(part for part in location_parts if part)

        highlights: list[str] = []
        if job_title:
            highlights.append(f"Current title: {job_title}")
        company = safe_str(record.get("job_company_name") or record.get("job_company_website"))
        if company:
            highlights.append(f"Company: {company}")
        if location_text:
            highlights.append(f"Location: {location_text}")
        skills = record.get("skills") or []
        if isinstance(skills, list) and skills:
            highlights.append("Skills: " + ", ".join(safe_str(s) for s in skills[:8]))

        return {
            "url": url,
            "title": title,
            "score": record.get("search_score", 0) or 0,
            "published_date": None,
            "text": record.get("summary") or None,
            "highlights": highlights[:5],
            "highlight_scores": None,
            "query": query,
            "location": loc_name,
            "source": "peopledatalabs",
            "info": {
                "job_title": record.get("job_title"),
                "job_title_role": record.get("job_title_role"),
                "job_title_sub_role": record.get("job_title_sub_role"),
                "industry": record.get("industry_v2") or record.get("industry"),
                "location": {
                    "name": record.get("location_name"),
                    "locality": record.get("location_locality"),
                    "region": record.get("location_region"),
                    "country": record.get("location_country"),
                },
                "linkedin_url": record.get("linkedin_url"),
                "github_url": record.get("github_url"),
                "twitter_url": record.get("twitter_url"),
                "work_email": record.get("work_email"),
                "skills": record.get("skills") or [],
            },
            "scraped_at": datetime.now(timezone.utc).isoformat(),
        }

    def _convert_apollo_record(
        self, record: dict[str, Any], query: dict[str, Any], loc_name: str
    ) -> dict[str, Any]:
        first_name = str(record.get("first_name") or "").strip()
        last_name_obfuscated = str(record.get("last_name_obfuscated") or "").strip()
        job_title = str(record.get("title") or "").strip()

        full_name = " ".join(part for part in [first_name, last_name_obfuscated] if part).strip()
        title = (
            f"{full_name} - {job_title}"
            if full_name and job_title
            else (full_name or job_title or "Unknown")
        )

        org = record.get("organization") or {}
        org_name = str(org.get("name") or "").strip()

        highlights: list[str] = []
        if job_title:
            highlights.append(f"Title: {job_title}")
        if org_name:
            highlights.append(f"Company: {org_name}")
        if record.get("has_email"):
            highlights.append("Email: Available")
        if record.get("has_direct_phone"):
            highlights.append("Phone: Available")

        apollo_id = str(record.get("id") or "").strip()
        url = f"apollo://person/{apollo_id}" if apollo_id else ""

        return {
            "url": url,
            "title": title,
            "score": 0,
            "published_date": record.get("last_refreshed_at"),
            "text": None,
            "highlights": highlights[:5],
            "highlight_scores": None,
            "query": query,
            "location": loc_name,
            "source": "apollo",
            "info": {
                "apollo_id": record.get("id"),
                "first_name": record.get("first_name"),
                "last_name_obfuscated": record.get("last_name_obfuscated"),
                "job_title": record.get("title"),
                "last_refreshed_at": record.get("last_refreshed_at"),
                "has_email": record.get("has_email"),
                "has_city": record.get("has_city"),
                "has_state": record.get("has_state"),
                "has_country": record.get("has_country"),
                "has_direct_phone": record.get("has_direct_phone"),
                "organization": {
                    "name": org.get("name"),
                    "has_industry": org.get("has_industry"),
                    "has_phone": org.get("has_phone"),
                    "has_city": org.get("has_city"),
                    "has_state": org.get("has_state"),
                    "has_country": org.get("has_country"),
                    "has_zip_code": org.get("has_zip_code"),
                    "has_revenue": org.get("has_revenue"),
                    "has_employee_count": org.get("has_employee_count"),
                },
            },
            "scraped_at": datetime.now(timezone.utc).isoformat(),
        }

    def _search_query(
        self, query: str, loc_name: str, seen_urls: set[str]
    ) -> list[dict[str, Any]]:
        if not self.exa:
            return []

        contents: dict[str, Any] = {}
        if self.contents_cfg.get("text"):
            contents["text"] = True
        if "highlights" in self.contents_cfg:
            contents["highlights"] = self.contents_cfg["highlights"]

        try:
            response = self.exa.search(
                query=query,
                category=self.exa_category,
                type="auto",
                num_results=self.num_results,
                contents=contents,
            )
        except Exception:
            logger.exception("Exa search failed for query %r", query)
            return []

        candidates = []
        for r in response.results:
            if r.url in seen_urls or r.url in self._existing_urls:
                continue
            seen_urls.add(r.url)
            candidates.append(
                {
                    "url": r.url,
                    "title": r.title,
                    "score": r.score,
                    "published_date": r.published_date,
                    "text": getattr(r, "text", None),
                    "highlights": getattr(r, "highlights", None),
                    "highlight_scores": getattr(r, "highlight_scores", None),
                    "query": query,
                    "location": loc_name,
                    "source": "exa",
                    "scraped_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        return candidates

    def _search_pdl_query(
        self, sql_query: str, loc_name: str, seen_urls: set[str]
    ) -> list[dict[str, Any]]:
        response = self._pdl_search_request(sql_query)
        records = response.get("data", []) if isinstance(response, dict) else []

        candidates = []
        for record in records:
            if not isinstance(record, dict):
                continue
            candidate = self._convert_pdl_record(record, sql_query, loc_name)
            url = candidate.get("url")
            if not url or url in seen_urls or url in self._existing_urls:
                continue
            seen_urls.add(url)
            candidates.append(candidate)
        return candidates

    def _search_apollo_query(
        self, params: dict[str, Any], loc_name: str, seen_urls: set[str]
    ) -> list[dict[str, Any]]:
        response = self._apollo_search_request(params)
        records = response.get("people", []) if isinstance(response, dict) else []

        candidates = []
        for record in records:
            if not isinstance(record, dict):
                continue
            candidate = self._convert_apollo_record(record, params, loc_name)
            url = candidate.get("url")
            if not url or url in seen_urls or url in self._existing_urls:
                continue
            seen_urls.add(url)
            candidates.append(candidate)
        return candidates

    def _load_generated_queries(self, loc_name: str) -> list[str]:
        path = self.campaign_dir / "data" / "generated_queries.yaml"
        if not path.exists():
            raise FileNotFoundError(
                f"No queries in campaign.yaml and no generated_queries.yaml found. "
                f"Run with --queries-only first, or add queries: to campaign.yaml."
            )
        with open(path) as f:
            data = yaml.safe_load(f)
        queries = data.get(loc_name, [])
        if not queries:
            raise ValueError(f"No generated queries found for location: {loc_name!r}")
        return queries

    def _load_queries_for_location(self, location: dict[str, Any]) -> list[Any]:
        loc_name = location["name"]

        if self.provider == "exa":
            return location.get("queries") or self._load_generated_queries(loc_name)

        if self.provider == "peopledatalabs":
            return location.get("pdl_queries") or self._build_pdl_sql_queries(loc_name)

        return location.get("apollo_queries") or self._build_apollo_query_params(loc_name)

    def search_location(self, location: dict[str, Any]) -> tuple[list[dict[str, Any]], list[Any]]:
        loc_name = location["name"]
        queries = self._load_queries_for_location(location)
        seen_urls: set[str] = set()
        candidates: list[dict[str, Any]] = []

        for query in queries:
            logger.info("[%s][%s] Searching: %r", loc_name, self.provider, query)
            if self.provider == "exa":
                batch = self._search_query(str(query), loc_name, seen_urls)
            elif self.provider == "peopledatalabs":
                batch = self._search_pdl_query(str(query), loc_name, seen_urls)
            else:
                if not isinstance(query, dict):
                    logger.warning("[%s][apollo] Skipping non-dict query: %r", loc_name, query)
                    continue
                batch = self._search_apollo_query(query, loc_name, seen_urls)
            candidates.extend(batch)
            logger.info("[%s] +%d new (total %d)", loc_name, len(batch), len(candidates))

        return candidates, queries

    def run(self) -> dict[str, list[dict[str, Any]]]:
        results: dict[str, list[dict[str, Any]]] = {}

        for location in self.config.get("locations", []):
            loc_name = location["name"]
            candidates, queries_used = self.search_location(location)
            results[loc_name] = candidates

            loc_dir = self.campaign_dir / "data" / loc_name
            loc_dir.mkdir(parents=True, exist_ok=True)

            with open(loc_dir / "raw_results.json", "w") as f:
                json.dump(candidates, f, indent=2, ensure_ascii=False)

            with open(loc_dir / "search_metadata.json", "w") as f:
                json.dump(
                    {
                        "location": loc_name,
                        "provider": self.provider,
                        "total_found": len(candidates),
                        "queries": queries_used,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                    f,
                    indent=2,
                )

            logger.info("[%s] Saved %d candidates", loc_name, len(candidates))

        return results
