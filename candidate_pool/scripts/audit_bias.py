#!/usr/bin/env python3
"""CLI script to run counterfactual demographic bias audits on candidate_pool."""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# Add candidate_pool/scripts to path
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from bias_audit.perturbations import DEMOGRAPHIC_VARIANTS, perturb_candidate
from bias_audit.reporter import (
    export_audit_csv,
    export_audit_json,
    generate_markdown_report,
)
from bias_audit.runner import BiasAuditRunner
from bias_audit.seed_profiles import SEED_PROFILES


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run demographic bias audit across candidate_pool filter and ranking stages."
    )
    parser.add_argument(
        "--model",
        default="claude-sonnet-5",
        help="LLM model name to evaluate (default: claude-sonnet-5).",
    )
    parser.add_argument(
        "--tiers",
        default="high_fit,borderline_fit",
        help="Comma-separated qualification tiers to audit: high_fit, borderline_fit, low_fit, or 'all'.",
    )
    parser.add_argument(
        "--baseline-repeats",
        type=int,
        default=3,
        help="Number of calibration runs for the baseline profile (default: 3).",
    )
    parser.add_argument(
        "--variants-repeats",
        type=int,
        default=1,
        help="Number of runs per perturbed variant (default: 1).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=5,
        help="Concurrent worker threads for LLM calls (default: 5).",
    )
    parser.add_argument(
        "--output-dir",
        default="bias_audit_reports",
        help="Output directory for reports and raw data (default: bias_audit_reports).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Synthesize all candidate variants and print statistics without invoking LLM calls.",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable detailed debug logging.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.tiers.strip().lower() == "all":
        target_tiers = list(SEED_PROFILES.keys())
    else:
        target_tiers = [t.strip() for t in args.tiers.split(",") if t.strip()]

    for t in target_tiers:
        if t not in SEED_PROFILES:
            sys.stderr.write(f"Error: Unknown tier '{t}'. Available tiers: {list(SEED_PROFILES.keys())}\n")
            return 1

    print("=" * 70)
    print("DEMOGRAPHIC BIAS AUDIT: CANDIDATE POOL")
    print(f"Target Tiers: {target_tiers}")
    print(f"Variants per Tier: {len(DEMOGRAPHIC_VARIANTS)} (1 baseline + {len(DEMOGRAPHIC_VARIANTS) - 1} demographic variants)")
    print(f"Target Model: {args.model}")
    print(f"Baseline Repeats: {args.baseline_repeats} | Workers: {args.workers}")
    print("=" * 70)

    if args.dry_run:
        print("\n[DRY RUN MODE] Synthesizing candidate variants across tiers...\n")
        for tier in target_tiers:
            seed = SEED_PROFILES[tier]
            print(f"Qualification Tier: {tier.upper()} ({seed['description']})")
            for v in DEMOGRAPHIC_VARIANTS:
                c = perturb_candidate(seed["template"], v, qualification_tier=tier)
                print(f"  - [{v['group']:<18}] {v['name']:<22} (Gender: {v['gender']:<6} | Religion: {v['religion_marker']}) -> URL: {c['url']}")
            print()
        print("[DRY RUN COMPLETE] Perturbation synthesis validated successfully.")
        return 0

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp_slug = time.strftime("%Y%m%d_%H%M%S")

    runner = BiasAuditRunner(
        model=args.model,
        baseline_repeats=args.baseline_repeats,
        variants_repeats=args.variants_repeats,
        max_workers=args.workers,
    )

    def progress_callback(phase: str, current: int, total: int) -> None:
        print(f"  [{phase.upper()}] Progress: {current}/{total} evaluations complete...", end="\r", flush=True)

    print("\nStarting live audit evaluations...")
    audit_result = runner.run_full_audit(tiers=target_tiers, progress_callback=progress_callback)
    print("\nEvaluations complete!\n")

    # Generate Reports
    md_report = generate_markdown_report(audit_result)
    report_path = output_dir / f"bias_audit_report_{timestamp_slug}.md"
    latest_report_path = output_dir / "latest_bias_audit_report.md"
    json_path = output_dir / f"bias_audit_{timestamp_slug}.json"
    csv_path = output_dir / f"bias_audit_{timestamp_slug}.csv"

    report_path.write_text(md_report, encoding="utf-8")
    latest_report_path.write_text(md_report, encoding="utf-8")
    export_audit_json(audit_result, json_path)
    export_audit_csv(audit_result, csv_path)

    print("=" * 70)
    print(f"AUDIT COMPLETE. Overall Status: {audit_result['status']}")
    print(f"Recommendation Flips: {audit_result['summary']['total_recommendation_flips']}")
    print(f"Score Divergences:   {audit_result['summary']['total_score_divergences']}")
    print("-" * 70)
    print(f"Markdown Report: {report_path}")
    print(f"Latest Report:   {latest_report_path}")
    print(f"JSON Data:       {json_path}")
    print(f"CSV Data:        {csv_path}")
    print("=" * 70)

    # Also print markdown report to stdout
    print("\n" + md_report)

    return 0 if audit_result["status"] == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
