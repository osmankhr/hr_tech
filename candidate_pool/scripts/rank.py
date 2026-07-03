#!/usr/bin/env python3
"""Run agentic + manual candidate ranking for a campaign."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

# Allow sibling-module imports when run as a script
sys.path.insert(0, str(Path(__file__).parent))

from ranking.pipeline import RankingPipeline

load_dotenv()


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def _load_config(campaign_dir: Path) -> dict:
    config_path = campaign_dir / "campaign.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"campaign.yaml not found in {campaign_dir}")
    with open(config_path) as f:
        return yaml.safe_load(f)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run candidate ranking pipeline")
    parser.add_argument("campaign_dir", type=Path, help="Path to the campaign directory")
    parser.add_argument(
        "--force-redesign",
        action="store_true",
        help="Regenerate dynamic feature schema and scoring policy even if cache exists",
    )
    args = parser.parse_args()

    campaign_dir = args.campaign_dir.resolve()
    if not campaign_dir.is_dir():
        print(f"Error: {campaign_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    _setup_logging()
    config = _load_config(campaign_dir)
    config.setdefault("ranking", {})
    if args.force_redesign:
        config["ranking"]["force_redesign"] = True

    RankingPipeline(campaign_dir, config).run()


if __name__ == "__main__":
    main()
