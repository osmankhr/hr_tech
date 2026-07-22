"""Generate Exa search queries from input folder contents using Claude headless mode."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import yaml

from llm_provider import call_model_text

logger = logging.getLogger(__name__)

_SYSTEM_INSTRUCTIONS = """\
You are a recruitment researcher designing search queries for Exa.ai's people-search API. \
Exa searches professional profiles (LinkedIn, personal sites, GitHub bios, etc.). Respond \
with ONLY a valid JSON array of strings — no markdown, no explanation, no preamble.
"""

_PROMPT_TEMPLATE = """\
## Job Description

{job_description}

## Filtering Criteria

{filter_criteria}

{seed_cv_section}## Task

Generate {n} diverse Exa.ai search queries to find candidate profiles matching the role above.
Target location / audience: **{location_name}**{location_hint}

Rules:
- Each query should target a different angle: vary job titles, skill combinations, and seniority signals
- Write queries as natural language phrases that would appear verbatim on a professional profile
- Do NOT repeat the same query with minor wording changes
- Do NOT include location words that might over-restrict results unless the location is a country
  (e.g. prefer "data scientist Turkey" over "data scientist Istanbul" to cast a wider net)
- HARD EXCLUSION: Every query must explicitly include a negative employment signal indicating that the target candidate does not work for ING (e.g. "not working at ING", "does not work for ING", "excluding ING employees"). This exclusion should be expressed in the query itself and must not otherwise restrict relevant roles, skills, industries, or employers."""

_SEED_CV_SECTION = """\
## Seed CVs (ideal candidate examples)

{excerpts}

"""


def _extract_pdf_text(pdf_path: Path, max_chars: int = 2000) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(pdf_path))
        pages_text = []
        for page in reader.pages:
            text = page.extract_text() or ""
            pages_text.append(text)
        full_text = "\n".join(pages_text)
        return full_text[:max_chars]
    except Exception as e:
        logger.warning("Could not extract text from %s: %s", pdf_path.name, e)
        return ""


def _load_seed_cvs(campaign_dir: Path) -> list[tuple[str, str]]:
    """Return list of (filename, text_excerpt) for PDFs in input/seed_cvs/."""
    seed_dir = campaign_dir / "input" / "seed_cvs"
    if not seed_dir.exists():
        return []
    results = []
    for pdf_path in sorted(seed_dir.glob("*.pdf")):
        text = _extract_pdf_text(pdf_path)
        if text.strip():
            results.append((pdf_path.name, text))
            logger.info("Loaded seed CV: %s (%d chars)", pdf_path.name, len(text))
    return results


def _call_model(prompt: str, model: str) -> list[str] | None:
    output = call_model_text(
        prompt=prompt,
        model=model,
        system=_SYSTEM_INSTRUCTIONS,
        timeout=120,
    )
    if not output:
        return None

    # Extract JSON array from output
    match = re.search(r"\[.*\]", output, re.DOTALL)
    if not match:
        logger.warning("No JSON array found in model output: %s", output[:300])
        return None
    try:
        queries = json.loads(match.group())
        return [q for q in queries if isinstance(q, str)]
    except json.JSONDecodeError as e:
        logger.warning("JSON parse error: %s", e)
        return None


class QueryGenerator:
    def __init__(self, campaign_dir: Path, config: dict[str, Any]) -> None:
        self.campaign_dir = campaign_dir
        self.config = config
        qg_cfg = config.get("query_generation", {})
        self.model = qg_cfg.get("model", config.get("filter", {}).get("model", "claude-sonnet-5"))
        self.num_queries = config.get("search", {}).get("num_queries_per_location", 6)
        self._out_path = campaign_dir / "data" / "generated_queries.yaml"

        jd_path = campaign_dir / "input" / "job_description.md"
        if not jd_path.exists():
            raise FileNotFoundError(f"job_description.md not found: {jd_path}")
        self.job_description = jd_path.read_text()

        criteria_path = campaign_dir / "input" / "filter_criteria.md"
        self.filter_criteria = criteria_path.read_text() if criteria_path.exists() else "(not provided)"

        self.seed_cvs = _load_seed_cvs(campaign_dir)

    def _build_prompt(self, loc_name: str, hint: str | None) -> str:
        hint_str = f" ({hint})" if hint else ""

        if self.seed_cvs:
            excerpts = "\n\n".join(
                f"### {name}\n{text}" for name, text in self.seed_cvs
            )
            seed_section = _SEED_CV_SECTION.format(excerpts=excerpts)
        else:
            seed_section = ""

        return _PROMPT_TEMPLATE.format(
            job_description=self.job_description,
            filter_criteria=self.filter_criteria,
            seed_cv_section=seed_section,
            n=self.num_queries,
            location_name=loc_name,
            location_hint=hint_str,
        )

    def generate_for_location(self, loc_name: str, hint: str | None = None) -> list[str]:
        prompt = self._build_prompt(loc_name, hint)
        logger.info("Generating %d queries for location: %s", self.num_queries, loc_name)
        queries = _call_model(prompt, self.model)
        if not queries:
            logger.error("Query generation failed for %s — no queries returned", loc_name)
            return []
        logger.info("Generated %d queries for %s", len(queries), loc_name)
        for i, q in enumerate(queries, 1):
            logger.info("  [%d] %s", i, q)
        return queries

    def run(self, force: bool = False) -> dict[str, list[str]]:
        if self._out_path.exists() and not force:
            logger.info("Reusing cached queries from %s (pass --force-queries to regenerate)", self._out_path)
            with open(self._out_path) as f:
                return yaml.safe_load(f)

        self._out_path.parent.mkdir(parents=True, exist_ok=True)
        all_queries: dict[str, list[str]] = {}

        for location in self.config.get("locations", []):
            loc_name = location["name"]
            hint = location.get("hint")
            queries = self.generate_for_location(loc_name, hint)
            all_queries[loc_name] = queries

        with open(self._out_path, "w") as f:
            yaml.dump(all_queries, f, allow_unicode=True, default_flow_style=False)
        logger.info("Saved generated queries to %s", self._out_path)

        return all_queries
