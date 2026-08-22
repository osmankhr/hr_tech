#!/usr/bin/env python3
"""Campaign orchestrator.

Usage:
    python scripts/run_campaign.py <campaign_dir>
    python scripts/run_campaign.py <campaign_dir> --search-only
    python scripts/run_campaign.py <campaign_dir> --filter-only
    python scripts/run_campaign.py <campaign_dir> --rank-only
    python scripts/run_campaign.py <campaign_dir> --report-only
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv

# Allow sibling-module imports when run as a script
sys.path.insert(0, str(Path(__file__).parent))

load_dotenv()


def _setup_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_dir / f"run_{stamp}.log"),
        ],
    )


def _load_config(campaign_dir: Path) -> dict:
    config_path = campaign_dir / "campaign.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"campaign.yaml not found in {campaign_dir}")
    with open(config_path) as f:
        return yaml.safe_load(f)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a candidate pool campaign")
    parser.add_argument("campaign_dir", type=Path, help="Path to the campaign directory")
    parser.add_argument("--queries-only", action="store_true", help="Run query generation phase only")
    parser.add_argument("--search-only", action="store_true", help="Run search phase only (includes query generation if needed)")
    parser.add_argument("--filter-only", action="store_true", help="Run filter phase only")
    parser.add_argument("--rank-only", action="store_true", help="Run ranking phase only")
    parser.add_argument("--report-only", action="store_true", help="Run report phase only")
    parser.add_argument("--force-queries", action="store_true", help="Regenerate queries even if cached")
    parser.add_argument("--force-ranking-redesign", action="store_true", help="Regenerate ranking feature schema and scoring policy")
    parser.add_argument(
        "--filter-max-candidates",
        type=int,
        default=None,
        help="Override filter.max_candidates for this run",
    )
    parser.add_argument(
        "--ranking-max-candidates",
        type=int,
        default=None,
        help="Override ranking.max_candidates for this run",
    )
    parser.add_argument(
        "--filter-max-workers",
        type=int,
        default=None,
        help="Override filter.max_workers for this run",
    )
    parser.add_argument(
        "--ranking-max-workers",
        type=int,
        default=None,
        help="Override ranking.max_workers for this run",
    )
    args = parser.parse_args()

    campaign_dir = args.campaign_dir.resolve()
    if not campaign_dir.is_dir():
        print(f"Error: {campaign_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    config = _load_config(campaign_dir)

    if args.filter_max_candidates is not None:
        config.setdefault("filter", {})["max_candidates"] = int(args.filter_max_candidates)
    if args.ranking_max_candidates is not None:
        config.setdefault("ranking", {})["max_candidates"] = int(args.ranking_max_candidates)
    if args.filter_max_workers is not None:
        config.setdefault("filter", {})["max_workers"] = int(args.filter_max_workers)
    if args.ranking_max_workers is not None:
        config.setdefault("ranking", {})["max_workers"] = int(args.ranking_max_workers)

    _setup_logging(campaign_dir / "logs")
    logger = logging.getLogger(__name__)
    logger.info("Campaign: %s", config.get("name", campaign_dir.name))
    if any(
        value is not None
        for value in [
            args.filter_max_candidates,
            args.ranking_max_candidates,
            args.filter_max_workers,
            args.ranking_max_workers,
        ]
    ):
        logger.info(
            "Runtime overrides: filter.max_candidates=%s, ranking.max_candidates=%s, filter.max_workers=%s, ranking.max_workers=%s",
            config.get("filter", {}).get("max_candidates"),
            config.get("ranking", {}).get("max_candidates"),
            config.get("filter", {}).get("max_workers"),
            config.get("ranking", {}).get("max_workers"),
        )

    run_all = not any([args.search_only, args.filter_only, args.rank_only, args.report_only, args.queries_only])

    if run_all or args.search_only or args.queries_only:
        from generate_queries import QueryGenerator

        logger.info("=== QUERY GENERATION PHASE ===")
        queries = QueryGenerator(campaign_dir, config).run(force=args.force_queries)
        total_q = sum(len(v) for v in queries.values())
        logger.info("Query generation complete: %d queries across %d locations", total_q, len(queries))

    if run_all or args.search_only:
        from search import ExaSearcher

        logger.info("=== SEARCH PHASE ===")
        results = ExaSearcher(campaign_dir, config).run()
        total = sum(len(v) for v in results.values())
        logger.info("Search complete: %d candidates across %d locations", total, len(results))

    if run_all or args.filter_only:
        from filter import CandidateFilter

        logger.info("=== FILTER PHASE ===")
        filtered = CandidateFilter(campaign_dir, config).run()
        accepted = sum(
            1 for c in filtered if c.get("ai_review", {}).get("recommendation") == "ACCEPT"
        )
        logger.info("Filter complete: %d/%d accepted", accepted, len(filtered))

    ranking_enabled = config.get("ranking", {}).get("enabled", True)
    if args.force_ranking_redesign:
        config.setdefault("ranking", {})["force_redesign"] = True

    if (run_all and ranking_enabled) or args.rank_only:
        from ranking.pipeline import RankingPipeline

        logger.info("=== RANKING PHASE ===")
        ranked = RankingPipeline(campaign_dir, config).run()
        logger.info("Ranking complete: %d candidates ranked", len(ranked))

    if run_all or args.report_only:
        from report import ReportGenerator

        logger.info("=== REPORT PHASE ===")
        shortlist_path = ReportGenerator(campaign_dir, config).run()
        logger.info("Report complete: %s", shortlist_path)

    logger.info("Campaign finished.")


if __name__ == "__main__":
    main()
