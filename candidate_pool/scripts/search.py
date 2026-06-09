"""Parameterized Exa.ai candidate search."""
from __future__ import annotations

import json
import logging
import os
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

        api_key = os.environ.get("EXA_API_KEY")
        if not api_key:
            raise ValueError("EXA_API_KEY not set in environment")
        self.exa = Exa(api_key)
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

    def _search_query(
        self, query: str, loc_name: str, seen_urls: set[str]
    ) -> list[dict[str, Any]]:
        num_results = self.search_cfg.get("num_results_per_query", 30)
        category = self.search_cfg.get("category", "people")
        contents_cfg = self.search_cfg.get("contents", {"text": True})

        contents: dict[str, Any] = {}
        if contents_cfg.get("text"):
            contents["text"] = True
        if "highlights" in contents_cfg:
            contents["highlights"] = contents_cfg["highlights"]

        try:
            response = self.exa.search(
                query=query,
                category=category,
                type="auto",
                num_results=num_results,
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
                    "scraped_at": datetime.now(timezone.utc).isoformat(),
                }
            )
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

    def search_location(self, location: dict[str, Any]) -> list[dict[str, Any]]:
        loc_name = location["name"]
        queries = location.get("queries") or self._load_generated_queries(loc_name)
        seen_urls: set[str] = set()
        candidates: list[dict[str, Any]] = []

        for query in queries:
            logger.info("[%s] Searching: %r", loc_name, query)
            batch = self._search_query(query, loc_name, seen_urls)
            candidates.extend(batch)
            logger.info("[%s] +%d new (total %d)", loc_name, len(batch), len(candidates))

        return candidates

    def run(self) -> dict[str, list[dict[str, Any]]]:
        results: dict[str, list[dict[str, Any]]] = {}

        for location in self.config.get("locations", []):
            loc_name = location["name"]
            candidates = self.search_location(location)
            results[loc_name] = candidates

            loc_dir = self.campaign_dir / "data" / loc_name
            loc_dir.mkdir(parents=True, exist_ok=True)

            with open(loc_dir / "raw_results.json", "w") as f:
                json.dump(candidates, f, indent=2, ensure_ascii=False)

            with open(loc_dir / "search_metadata.json", "w") as f:
                json.dump(
                    {
                        "location": loc_name,
                        "total_found": len(candidates),
                        "queries": location["queries"],
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                    f,
                    indent=2,
                )

            logger.info("[%s] Saved %d candidates", loc_name, len(candidates))

        return results
