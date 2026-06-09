"""Generate shortlist reports from filtered candidate results."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# Columns excluded from tabular exports (too large for spreadsheets)
_LARGE_COLUMNS = {"text"}


def _flatten(candidate: dict[str, Any]) -> dict[str, Any]:
    """Merge ai_review fields into the top-level dict for tabular output."""
    flat = {k: v for k, v in candidate.items() if k not in ("ai_review",)}
    for key, val in (candidate.get("ai_review") or {}).items():
        flat[f"ai_{key}"] = val
    return flat


class ReportGenerator:
    def __init__(self, campaign_dir: Path, config: dict[str, Any]) -> None:
        self.campaign_dir = campaign_dir
        self.config = config
        out_cfg = config.get("output", {})
        self.formats: list[str] = out_cfg.get("formats", ["excel", "csv", "json"])
        self.keep_rejected: bool = out_cfg.get("keep_rejected", True)
        self.datestamp = datetime.now().strftime("%Y%m%d")

    def run(self) -> Path:
        filtered_path = self.campaign_dir / "data" / "filtered_results.json"
        if not filtered_path.exists():
            raise FileNotFoundError(f"filtered_results.json not found: {filtered_path}")

        with open(filtered_path) as f:
            candidates: list[dict[str, Any]] = json.load(f)

        out_dir = self.campaign_dir / "output"
        out_dir.mkdir(parents=True, exist_ok=True)

        # Full shortlist JSON preserves every field for downstream scoring
        shortlist_path = out_dir / "shortlist.json"
        with open(shortlist_path, "w") as f:
            json.dump(candidates, f, indent=2, ensure_ascii=False)
        logger.info("Saved full shortlist: %s (%d candidates)", shortlist_path, len(candidates))

        accepted = [c for c in candidates if c.get("ai_review", {}).get("recommendation") == "ACCEPT"]
        rejected = [c for c in candidates if c.get("ai_review", {}).get("recommendation") == "REJECT"]
        pending = [c for c in candidates if c.get("ai_review", {}).get("recommendation") == "PENDING"]

        if "csv" in self.formats:
            self._write_csv(accepted, out_dir)

        if "excel" in self.formats:
            self._write_excel(accepted, rejected, pending, out_dir)

        logger.info(
            "Report complete — ACCEPT: %d  REJECT: %d  PENDING: %d",
            len(accepted),
            len(rejected),
            len(pending),
        )
        return shortlist_path

    def _to_df(self, candidates: list[dict[str, Any]]) -> pd.DataFrame:
        rows = [_flatten(c) for c in candidates]
        df = pd.DataFrame(rows)
        return df.drop(columns=[c for c in _LARGE_COLUMNS if c in df.columns], errors="ignore")

    def _write_csv(self, accepted: list[dict[str, Any]], out_dir: Path) -> None:
        path = out_dir / f"shortlist_{self.datestamp}.csv"
        self._to_df(accepted).to_csv(path, index=False)
        logger.info("Saved CSV: %s (%d rows)", path, len(accepted))

    def _write_excel(
        self,
        accepted: list[dict[str, Any]],
        rejected: list[dict[str, Any]],
        pending: list[dict[str, Any]],
        out_dir: Path,
    ) -> None:
        path = out_dir / f"shortlist_{self.datestamp}.xlsx"
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            pd.DataFrame(
                {
                    "Metric": ["Total", "Accepted", "Rejected", "Pending", "Run Date"],
                    "Value": [
                        len(accepted) + len(rejected) + len(pending),
                        len(accepted),
                        len(rejected),
                        len(pending),
                        datetime.now().strftime("%Y-%m-%d %H:%M"),
                    ],
                }
            ).to_excel(writer, sheet_name="Summary", index=False)

            self._to_df(accepted).to_excel(writer, sheet_name="Approved", index=False)

            if self.keep_rejected:
                self._to_df(rejected + pending).to_excel(
                    writer, sheet_name="Rejected_Pending", index=False
                )

        logger.info("Saved Excel: %s", path)
