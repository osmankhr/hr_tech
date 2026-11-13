"""Contacted candidates loader, normalizer, and matcher.

Eliminates previously contacted candidates based on an Excel or CSV file
tracked by recruiters (matching on Candidate Name with Turkish/English
diacritic tolerance, and/or URL if present).
"""
from __future__ import annotations

import logging
import os
import re
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pandas as pd

logger = logging.getLogger(__name__)

# Common titles and honorifics that may precede or follow candidate names
HONORIFICS = {
    "dr",
    "dr.",
    "prof",
    "prof.",
    "doc",
    "doc.",
    "doç",
    "doç.",
    "eng",
    "phd",
    "ph.d.",
    "msc",
    "m.sc.",
    "bsc",
    "b.sc.",
    "mr",
    "mr.",
    "ms",
    "ms.",
    "mrs",
    "mrs.",
    "av",
    "av.",
}

# Candidate name column aliases in recruiter spreadsheets
NAME_COLUMN_ALIASES = [
    "candidate name",
    "candidate_name",
    "candidatename",
    "candidate",
    "full name",
    "fullname",
    "name",
    "ad soyad",
    "ad_soyad",
    "aday adi",
    "aday adı",
    "aday",
    "isim",
]

# Profile URL column aliases
URL_COLUMN_ALIASES = [
    "url",
    "linkedin",
    "linkedin_url",
    "github",
    "github_url",
    "huggingface",
    "huggingface_url",
    "kaggle",
    "kaggle_url",
    "profile_url",
    "profile",
    "link",
]

# Turkish to Latin character transliteration map
_TURKISH_CHAR_MAP = str.maketrans(
    {
        "I": "i",
        "İ": "i",
        "ı": "i",
        "i": "i",
        "Ğ": "g",
        "ğ": "g",
        "Ü": "u",
        "ü": "u",
        "Ş": "s",
        "ş": "s",
        "Ö": "o",
        "ö": "o",
        "Ç": "c",
        "ç": "c",
        "Â": "a",
        "â": "a",
        "Î": "i",
        "î": "i",
        "Û": "u",
        "û": "u",
    }
)


def normalize_turkish_text(text: str) -> str:
    """Normalize Turkish and English strings to lowercase ASCII tokens."""
    if not text or not isinstance(text, str):
        return ""
    translated = text.translate(_TURKISH_CHAR_MAP).lower()
    decomposed = unicodedata.normalize("NFKD", translated)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    cleaned = re.sub(r"[^a-z0-9\s]", " ", stripped)
    return re.sub(r"\s+", " ", cleaned).strip()


def clean_candidate_name(name: str) -> str:
    """Normalize name and strip known honorifics/prefixes/suffixes."""
    tokens = normalize_turkish_text(name).split()
    while tokens and tokens[0] in HONORIFICS:
        tokens.pop(0)
    while tokens and tokens[-1] in HONORIFICS:
        tokens.pop()
    return " ".join(tokens)


def normalize_url(url: str) -> str:
    """Normalize a candidate URL for reliable comparison."""
    if not url or not isinstance(url, str):
        return ""
    parsed = urlparse(url.strip())
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    # Normalize regional linkedin subdomains: tr.linkedin.com -> linkedin.com
    if "linkedin.com" in netloc:
        netloc = "linkedin.com"
    path = parsed.path.rstrip("/")
    return f"{netloc}{path}".lower()


def extract_name_from_title(title: str) -> str:
    """Extract candidate name from search result title (e.g. LinkedIn headline)."""
    if not title:
        return ""
    # Split by standard title delimiters like " - ", " | ", " – ", " — ", ": ", " • "
    parts = re.split(r"\s*[-–—|:•]\s+", title.strip())
    name_part = parts[0].strip() if parts else title.strip()
    name_part = re.sub(r"\s*\|\s*LinkedIn.*$", "", name_part, flags=re.IGNORECASE).strip()
    return clean_candidate_name(name_part)



class ContactedCandidatesStore:
    """In-memory index of previously contacted candidates."""

    def __init__(self, file_path: Path | str | None = None) -> None:
        self.file_path: Path | None = Path(file_path).resolve() if file_path else None
        self.contacted_names: set[str] = set()
        self.contacted_urls: set[str] = set()
        self.contacted_records_by_name: dict[str, dict[str, Any]] = {}
        self.contacted_records_by_url: dict[str, dict[str, Any]] = {}
        if self.file_path:
            self.load(self.file_path)

    def is_empty(self) -> bool:
        return len(self.contacted_names) == 0 and len(self.contacted_urls) == 0

    def load(self, path: Path | str) -> None:
        file_path = Path(path).resolve()
        if not file_path.exists():
            logger.warning("Contacted candidates file not found: %s", file_path)
            return

        self.file_path = file_path
        dfs: list[pd.DataFrame] = []
        suffix = file_path.suffix.lower()

        try:
            if suffix in (".xlsx", ".xls"):
                excel_file = pd.ExcelFile(file_path)
                for sheet_name in excel_file.sheet_names:
                    df = excel_file.parse(sheet_name)
                    if not df.empty:
                        dfs.append(df)
            elif suffix == ".csv":
                df = pd.read_csv(file_path)
                if not df.empty:
                    dfs.append(df)
            else:
                logger.warning("Unsupported contacted candidates file extension: %s", suffix)
                return
        except Exception as e:
            logger.exception("Failed to read contacted candidates file %s: %s", file_path, e)
            return

        for df in dfs:
            self._extract_from_df(df)

        logger.info(
            "Loaded %d contacted candidate names and %d URLs from %s",
            len(self.contacted_names),
            len(self.contacted_urls),
            file_path.name,
        )

    def _extract_from_df(self, df: pd.DataFrame) -> None:
        # Normalize column header names
        col_map = {str(col).strip().lower(): col for col in df.columns}

        # Look for candidate name column
        name_col = None
        for alias in NAME_COLUMN_ALIASES:
            if alias in col_map:
                name_col = col_map[alias]
                break

        # Look for url column
        url_col = None
        for alias in URL_COLUMN_ALIASES:
            if alias in col_map:
                url_col = col_map[alias]
                break

        for _, row in df.iterrows():
            row_dict: dict[str, Any] = {}
            for col_name, val in row.items():
                if pd.notna(val):
                    val_str = str(val).strip()
                    if val_str:
                        row_dict[str(col_name)] = val_str

            if name_col is not None and name_col in row and pd.notna(row[name_col]):
                cleaned = clean_candidate_name(str(row[name_col]))
                if cleaned and len(cleaned) >= 2:
                    self.contacted_names.add(cleaned)
                    if cleaned not in self.contacted_records_by_name:
                        self.contacted_records_by_name[cleaned] = row_dict

            if url_col is not None and url_col in row and pd.notna(row[url_col]):
                norm = normalize_url(str(row[url_col]))
                if norm:
                    self.contacted_urls.add(norm)
                    if norm not in self.contacted_records_by_url:
                        self.contacted_records_by_url[norm] = row_dict

    def get_contacted_match(self, candidate: dict[str, Any]) -> dict[str, Any] | None:
        """Return match details and recruiter metadata if candidate matches contacted store."""
        if self.is_empty():
            return None

        # 1. Direct URL match
        cand_url = candidate.get("url") or ""
        cand_url_norm = normalize_url(cand_url)
        if cand_url_norm and cand_url_norm in self.contacted_urls:
            return {
                "match_type": "url",
                "matched_key": cand_url_norm,
                "recruiter_record": dict(self.contacted_records_by_url.get(cand_url_norm, {})),
            }

        title = candidate.get("title") or ""
        title_name = extract_name_from_title(title)
        norm_title = normalize_turkish_text(title)
        cand_url_lower = cand_url.lower()

        # Check explicit candidate name field if present
        direct_name = clean_candidate_name(candidate.get("name") or "")

        for contacted in self.contacted_names:
            matched = False
            match_type = ""
            if direct_name and contacted == direct_name:
                matched = True
                match_type = "direct_name"
            elif title_name and contacted == title_name:
                matched = True
                match_type = "title_name"
            else:
                words = contacted.split()
                # If contacted name has 2+ words (first + last name), check phrase in title or url slug
                if len(words) >= 2:
                    # Word-boundary phrase search in full title
                    if re.search(r"\b" + re.escape(contacted) + r"\b", norm_title):
                        matched = True
                        match_type = "title_phrase"
                    else:
                        # LinkedIn URL slug match (e.g. in/yigit-can-ozkaya or in/yigitcanozkaya)
                        slug_dash = "-".join(words)
                        slug_nodash = "".join(words)
                        slug_pattern = rf"/(in|pub)/({re.escape(slug_dash)}|{re.escape(slug_nodash)})(-[0-9a-z]+)?(/|\?|$)"
                        if re.search(slug_pattern, cand_url_lower):
                            matched = True
                            match_type = "linkedin_slug"
                        else:
                            # Community platform handle match (github.com/<slug>, huggingface.co/<slug>, kaggle.com/<slug>)
                            platform_slug_pattern = (
                                rf"(github\.com|huggingface\.co|kaggle\.com)/"
                                rf"({re.escape(slug_dash)}|{re.escape(slug_nodash)})(/|\?|$)"
                            )
                            if re.search(platform_slug_pattern, cand_url_lower):
                                matched = True
                                match_type = "platform_slug"

            if matched:
                return {
                    "match_type": match_type,
                    "matched_key": contacted,
                    "recruiter_record": dict(self.contacted_records_by_name.get(contacted, {})),
                }

        return None

    def is_contacted(self, candidate: dict[str, Any]) -> bool:
        """Check if candidate matches any contacted candidate by URL or name."""
        return self.get_contacted_match(candidate) is not None


def resolve_contacted_candidates_path(campaign_dir: Path, config: dict[str, Any]) -> Path | None:
    """Find the configured or default contacted candidates file path."""
    # 1. Configured path in campaign.yaml (under dedup or search)
    configured = (
        config.get("dedup", {}).get("contacted_candidates_path")
        or config.get("search", {}).get("contacted_candidates_path")
    )
    if configured:
        p = Path(configured)
        if not p.is_absolute():
            p = (campaign_dir / p).resolve()
        if p.exists():
            return p
        logger.warning("Configured contacted_candidates_path not found: %s", p)

    # 2. Ambient environment variable
    env_path = os.environ.get("CONTACTED_CANDIDATES_PATH")
    if env_path:
        p = Path(env_path).resolve()
        if p.exists():
            return p
        logger.warning("Environment CONTACTED_CANDIDATES_PATH not found: %s", p)

    # 3. Standard fallback locations inside campaign directory
    candidates = [
        campaign_dir / "input" / "contacted_candidates.xlsx",
        campaign_dir / "input" / "contacted_candidates.xls",
        campaign_dir / "input" / "contacted_candidates.csv",
        campaign_dir / "input" / "contacted.xlsx",
        campaign_dir / "input" / "contacted.csv",
    ]
    for p in candidates:
        if p.exists():
            return p

    # 4. Global shared fallback locations across all campaigns
    global_dir = Path(__file__).resolve().parent.parent / "data"
    global_candidates = [
        global_dir / "contacted_candidates.xlsx",
        global_dir / "contacted_candidates.xls",
        global_dir / "contacted_candidates.csv",
        global_dir / "contacted.xlsx",
        global_dir / "contacted.csv",
    ]
    for p in global_candidates:
        if p.exists():
            return p

    return None
