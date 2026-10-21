"""Report generation and export for bias audit results."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


def generate_markdown_report(audit_result: dict[str, Any]) -> str:
    """Generate a recruiter- and auditor-facing markdown report."""
    summary = audit_result.get("summary", {})
    status = audit_result.get("status", "UNKNOWN")
    model = audit_result.get("model", "unknown")
    timestamp = audit_result.get("timestamp", "unknown")
    duration = audit_result.get("duration_seconds", 0)

    status_badge = "🟢 **PASS** (No Systematic Bias Detected)" if status == "PASS" else "🔴 **BIAS FLAGGED** (Divergence Detected)"

    lines = [
        "# Demographic Bias Audit Report: Candidate Sourcing & Ranking Pipeline",
        "",
        f"**Audit Timestamp:** `{timestamp}`  ",
        f"**Model Evaluated:** `{model}`  ",
        f"**Execution Duration:** `{duration}s`  ",
        f"**Overall Verdict:** {status_badge}",
        "",
        "---",
        "",
        "## 1. Executive Summary",
        "",
        "This audit measures whether candidate evaluation decisions diverge when only demographic "
        "signals (names, gender cues, ethnicity, and explicit religious markers) are varied on "
        "identical qualification profiles.",
        "",
        f"- **Total Variants Evaluated:** `{summary.get('total_variants_evaluated', 0)}`",
        f"- **Filter Recommendation Flips:** `{summary.get('total_recommendation_flips', 0)}` "
        f"({summary.get('overall_flip_rate_pct', 0)}% of evaluations)",
        f"- **Score Divergences (> stochastic noise):** `{summary.get('total_score_divergences', 0)}` "
        f"({summary.get('overall_divergence_rate_pct', 0)}% of evaluations)",
        "",
    ]

    if status == "PASS":
        lines.extend([
            "> **Audit Finding:** The evaluation pipeline remained invariant across tested demographic groups. "
            "Recommendation outcomes and numerical scores remained within the baseline stochastic noise band.",
            "",
        ])
    else:
        lines.extend([
            "> ⚠️ **Audit Finding:** Divergences were detected across demographic variants. "
            "See the detailed breakdown below for specific demographic groups and qualification tiers.",
            "",
        ])

    lines.extend([
        "---",
        "",
        "## 2. Tier-by-Tier Evaluation",
        "",
    ])

    tiers = audit_result.get("tiers", {})
    for tier_key, tier_data in tiers.items():
        tier_name = tier_data.get("tier", tier_key).replace("_", " ").title()
        tier_desc = tier_data.get("tier_description", "")
        baseline = tier_data.get("baseline", {})
        metrics = tier_data.get("metrics", {})
        variants = tier_data.get("variants", [])

        lines.extend([
            f"### Qualification Tier: {tier_name}",
            f"*{tier_desc}*",
            "",
            "#### Baseline Noise Calibration (Control Variant)",
            f"- **Baseline Profile Name:** `Candidate A` (demographically neutral)",
            f"- **Calibration Runs:** `{len(baseline.get('runs', []))}`",
            f"- **Modal Filter Recommendation:** `{baseline.get('modal_recommendation', 'UNKNOWN')}`",
            f"- **Mean Ranking Score:** `{baseline.get('mean_score', 0)} / 100`",
            f"- **Stochastic Spread (Min – Max):** `{baseline.get('min_score', 0)} – {baseline.get('max_score', 0)}` "
            f"(Noise band: `±{baseline.get('noise_band', 0)} pts`, StdDev: `{baseline.get('std_dev', 0)}`)",
            "",
            "#### Perturbation Variant Results",
            "",
            "| Demographic Group | Variant Name | Gender | Religious Marker | Filter Decision | Flip? | Score | Δ vs Base | Status |",
            "|---|---|---|---|:---:|:---:|:---:|:---:|:---:|",
        ])

        for v in variants:
            demo = v.get("demographic", {})
            filt = v.get("filter", {})
            rank = v.get("ranking", {})
            delta = v.get("delta", {})

            group = demo.get("group", "")
            name = demo.get("name", "")
            gender = demo.get("gender", "")
            religion = demo.get("religion_marker", "None")
            rec = filt.get("recommendation", "N/A")
            is_flip = "🚨 **YES**" if delta.get("is_rec_flip") else "No"
            score = rank.get("manual_score", "N/A")
            score_delta = delta.get("score_delta", 0.0)
            sign = "+" if score_delta > 0 else ""
            delta_str = f"{sign}{score_delta}"

            if delta.get("is_rec_flip") or delta.get("is_score_divergence"):
                stat = "⚠️ Divergent"
            else:
                stat = "✅ Invariant"

            lines.append(
                f"| {group} | {name} | {gender} | {religion} | `{rec}` | {is_flip} | {score} | {delta_str} | {stat} |"
            )

        lines.append("")

        # Religious Spotlight
        religious_variants = [v for v in variants if v.get("demographic", {}).get("group") == "Religious Marker"]
        if religious_variants:
            lines.extend([
                "#### Religious Affiliation Spotlight",
                "",
                "Examining explicitly marked religious and cultural names against baseline:",
                "",
                "| Name | Affiliation Marker | Filter Rec | Score | Δ vs Baseline | Outcome |",
                "|---|---|:---:|:---:|:---:|:---:|",
            ])
            for rv in religious_variants:
                demo = rv.get("demographic", {})
                filt = rv.get("filter", {})
                rank = rv.get("ranking", {})
                delta = rv.get("delta", {})
                score_delta = delta.get("score_delta", 0.0)
                sign = "+" if score_delta > 0 else ""
                outcome = "⚠️ Flagged" if delta.get("is_rec_flip") or delta.get("is_score_divergence") else "✅ Consistent"

                lines.append(
                    f"| {demo.get('name')} | {demo.get('religion_marker')} | `{filt.get('recommendation')}` | "
                    f"{rank.get('manual_score')} | {sign}{score_delta} | {outcome} |"
                )
            lines.append("")

        # Explanations of Any Divergences
        divergent_variants = [v for v in variants if v.get("delta", {}).get("is_rec_flip") or v.get("delta", {}).get("is_score_divergence")]
        if divergent_variants:
            lines.extend([
                "#### Qualitative Analysis of Divergent Variants",
                "",
            ])
            for dv in divergent_variants:
                demo = dv.get("demographic", {})
                filt = dv.get("filter", {})
                rank = dv.get("ranking", {})
                delta = dv.get("delta", {})
                lines.extend([
                    f"##### Variant: {demo.get('name')} ({demo.get('group')})",
                    f"- **Filter Decision:** `{filt.get('recommendation')}` (Baseline was `{delta.get('baseline_modal_rec')}`)",
                    f"- **Score:** `{rank.get('manual_score')}` (Baseline was `{delta.get('baseline_mean_score')}`)",
                    f"- **Key Strength:** {filt.get('key_strength') or 'None reported'}",
                    f"- **Main Concern:** {filt.get('main_concern') or 'None reported'}",
                    f"- **Reasoning Excerpt:** {filt.get('reasoning')[:250] if filt.get('reasoning') else 'N/A'}",
                    "",
                ])

        lines.extend(["---", ""])

    # Methodological Appendix
    lines.extend([
        "## 3. Methodology & Audit Standards",
        "",
        "1. **Counterfactual Paired Testing:** Exact resume text, career timeline, company names, and educational institutions are held constant across all variants. Only the candidate name, identity pronouns, and URL handle are perturbed.",
        "2. **Baseline Calibration:** A demographically neutral baseline profile is run multiple times to empirically measure the model's stochastic non-determinism. Deviations are only flagged when they exceed this measured noise threshold.",
        "3. **Coverage:** Tested across Western, Turkish (local hiring context), Middle Eastern/Islamic (including explicit religious naming), Christian-marker, Jewish-marker, South Asian, East Asian, Hispanic, and African diaspora demographics.",
        "",
    ])

    return "\n".join(lines)


def export_audit_json(audit_result: dict[str, Any], output_path: Path) -> None:
    """Save full audit result payload to JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(audit_result, f, indent=2, ensure_ascii=False)


def export_audit_csv(audit_result: dict[str, Any], output_path: Path) -> None:
    """Export flattened variant rows to CSV for spreadsheet inspection."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    tiers = audit_result.get("tiers", {})

    for tier_key, tier_data in tiers.items():
        baseline = tier_data.get("baseline", {})
        variants = tier_data.get("variants", [])

        # Include baseline summary row
        rows.append({
            "tier": tier_key,
            "variant_id": "baseline_neutral",
            "name": "Candidate A (Baseline)",
            "group": "Baseline",
            "gender": "Neutral",
            "ethnicity": "Neutral",
            "religion_marker": "None",
            "filter_recommendation": baseline.get("modal_recommendation", ""),
            "filter_confidence": "BASELINE",
            "ranking_score": baseline.get("mean_score", 0),
            "ranking_category": "A",
            "score_delta_vs_baseline": 0.0,
            "is_rec_flip": False,
            "is_score_divergence": False,
            "main_concern": "",
        })

        for v in variants:
            demo = v.get("demographic", {})
            filt = v.get("filter", {})
            rank = v.get("ranking", {})
            delta = v.get("delta", {})

            rows.append({
                "tier": tier_key,
                "variant_id": demo.get("variant_id", ""),
                "name": demo.get("name", ""),
                "group": demo.get("group", ""),
                "gender": demo.get("gender", ""),
                "ethnicity": demo.get("ethnicity", ""),
                "religion_marker": demo.get("religion_marker", ""),
                "filter_recommendation": filt.get("recommendation", ""),
                "filter_confidence": filt.get("confidence", ""),
                "ranking_score": rank.get("manual_score", 0),
                "ranking_category": rank.get("category", ""),
                "score_delta_vs_baseline": delta.get("score_delta", 0.0),
                "is_rec_flip": delta.get("is_rec_flip", False),
                "is_score_divergence": delta.get("is_score_divergence", False),
                "main_concern": filt.get("main_concern", "") or filt.get("reasoning", ""),
            })

    if not rows:
        return

    fieldnames = list(rows[0].keys())
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
