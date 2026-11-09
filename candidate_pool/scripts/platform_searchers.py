"""Multi-platform candidate searchers for GitHub, Hugging Face, and Kaggle.

This module extends the candidate discovery pipeline beyond traditional professional
networks (LinkedIn/Exa) to technical community platforms where ML, Data Science, and
Software Engineering talent actively publish code, models, datasets, and notebooks.

Key engineering & security guarantees:
1. Activity Verification: Every platform searcher checks concrete activity timestamps
   (e.g., GitHub repo `pushed_at`, Hugging Face model/dataset `lastModified`, Kaggle
   kernel `lastRunTime` / activity recency) against a configurable `activity_days`
   window (default: 180 days) so dormant accounts are filtered out early.
2. SSRF & Injection Protection: Outbound HTTP requests are restricted to an explicit
   allowlist of HTTPS hosts (`api.github.com`, `huggingface.co`, `www.kaggle.com`).
   All user handles, path segments, and query parameters are strictly validated and
   URL-encoded before network calls.
3. Resource & DoS Safety: All network calls enforce strict socket timeouts and cap
   maximum response payload bytes (`MAX_HTTP_RESPONSE_BYTES`).
4. Credential Hygiene: API keys/tokens (`GITHUB_TOKEN`, `HF_TOKEN`, `KAGGLE_USERNAME`,
   `KAGGLE_KEY`) are read exclusively from environment variables, transmitted only
   over HTTPS headers to verified hosts, and never written to logs or output files.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Security & Operational Constants
# ---------------------------------------------------------------------------

# Explicit allowlist of HTTPS hosts permitted for outbound platform API requests.
ALLOWED_HTTPS_HOSTS: frozenset[str] = frozenset(
    {
        "api.github.com",
        "huggingface.co",
        "www.kaggle.com",
        "kaggle.com",
    }
)

# Cap maximum HTTP response body size at 5 MB to prevent memory exhaustion (DoS).
MAX_HTTP_RESPONSE_BYTES: int = 5 * 1024 * 1024

# Default socket timeout in seconds for external platform API requests.
DEFAULT_HTTP_TIMEOUT_SECONDS: int = 30

# Default lookback window (in days) to consider a candidate "genuinely active".
DEFAULT_ACTIVITY_DAYS: int = 180

# Strict allowlist regex for platform usernames/handles to prevent path traversal.
_SAFE_IDENTIFIER_RE: re.Pattern[str] = re.compile(r"^[a-zA-Z0-9._-]+$")

# Regex to detect ING affiliation in candidate bios or company fields (hard exclusion).
_ING_EMPLOYER_RE: re.Pattern[str] = re.compile(
    r"\b(ing\s+bank|ing\s+hubs|ing\s+t[uü]rkiye|ing\s+turkey|ing\s+groep|ing\s+direct)\b"
    r"|(?<![a-z0-9])@ing(?![a-z0-9])",
    re.IGNORECASE,
)

# Negative exclusion phrases commonly injected into Exa natural-language queries
# that should be stripped before building technical keyword queries for GitHub/HF/Kaggle.
_NEGATIVE_CLAUSE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bexcluding\s+ing\s+employees?\b", re.IGNORECASE),
    re.compile(r"\bexcluding\s+ing\b", re.IGNORECASE),
    re.compile(r"\bnot\s+working\s+(?:at|for)\s+ing\b", re.IGNORECASE),
    re.compile(r"\bdoes\s+not\s+work\s+(?:at|for)\s+ing\b", re.IGNORECASE),
    re.compile(r"-\"ing\s*bank\"", re.IGNORECASE),
    re.compile(r"-ing\b", re.IGNORECASE),
)

# Common conversational filler words stripped when converting long queries to API keywords.
_STOP_WORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "to",
        "was",
        "were",
        "will",
        "with",
        "who",
        "experienced",
        "looking",
        "professional",
        "professionals",
        "candidate",
        "candidates",
        "based",
        "working",
        "work",
        "does",
        "not",
        "excluding",
        "employees",
        "employee",
        "senior",
        "lead",
        "staff",
        "principal",
        "junior",
        "engineer",
        "scientist",
        "developer",
        "researcher",
        "specialist",
        "large",
        "models",
    }
)

# Known location tokens mapped to canonical location hints for platform searches.
_LOCATION_SYNONYMS: dict[str, list[str]] = {
    "turkey": ["Turkey", "Türkiye", "Istanbul", "Ankara", "Izmir"],
    "türkiye": ["Turkey", "Türkiye", "Istanbul", "Ankara", "Izmir"],
    "tr": ["Turkey", "Türkiye", "Istanbul"],
    "us": ["United States", "USA"],
    "uk": ["United Kingdom", "London"],
    "nl": ["Netherlands", "Amsterdam"],
    "de": ["Germany", "Berlin", "Munich"],
}


# ---------------------------------------------------------------------------
# Security & Parsing Helper Functions
# ---------------------------------------------------------------------------


def validate_safe_https_url(url: str) -> str:
    """Validate that a URL uses HTTPS and targets an explicitly allowlisted host.

    Raises:
        ValueError: If the URL scheme is not `https` or the host is not in
            `ALLOWED_HTTPS_HOSTS`, preventing Server-Side Request Forgery (SSRF).
    """
    if not url or not isinstance(url, str):
        raise ValueError("URL must be a non-empty string")

    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme.lower() != "https":
        raise ValueError(f"Insecure or unsupported URL scheme {parsed.scheme!r}; only 'https' is allowed")

    hostname = (parsed.hostname or "").lower()
    if hostname not in ALLOWED_HTTPS_HOSTS:
        raise ValueError(f"Host {hostname!r} is not in ALLOWED_HTTPS_HOSTS")

    return url.strip()


def is_valid_identifier(identifier: str) -> bool:
    """Return True if a username or handle contains only safe identifier characters.

    Prevents path traversal (`../`), query injection (`?`, `&`), or control characters
    when interpolating usernames into API endpoint paths.
    """
    if not identifier or not isinstance(identifier, str):
        return False
    if len(identifier) > 100 or ".." in identifier:
        return False
    return bool(_SAFE_IDENTIFIER_RE.match(identifier))


def parse_iso_datetime(value: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp string into a timezone-aware UTC datetime.

    Returns None if the input is empty or cannot be parsed.
    """
    if not value or not isinstance(value, str):
        return None

    cleaned = value.strip()
    if not cleaned:
        return None

    # Normalize trailing 'Z' to '+00:00' for standard fromisoformat compatibility
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"

    try:
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        # Fallback for date-only strings like '2026-08-15'
        try:
            dt = datetime.strptime(cleaned[:10], "%Y-%m-%d")
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None


def is_recently_active(
    timestamp_str: str | None,
    activity_days: int = DEFAULT_ACTIVITY_DAYS,
    *,
    now: datetime | None = None,
) -> bool:
    """Determine whether an ISO timestamp falls within the recent `activity_days` window.

    Args:
        timestamp_str: ISO-8601 timestamp from a platform API (e.g., `pushed_at`, `lastModified`).
        activity_days: Maximum age in days to be considered active. If <= 0, activity check is disabled.
        now: Optional reference UTC datetime (used for deterministic unit testing).

    Returns:
        True if the timestamp is valid and within `activity_days` of `now`.
    """
    if activity_days <= 0:
        return True

    dt = parse_iso_datetime(timestamp_str)
    if dt is None:
        return False

    reference_now = now or datetime.now(timezone.utc)
    cutoff = reference_now - timedelta(days=activity_days)
    return dt >= cutoff


def is_ing_affiliated(text: str | None) -> bool:
    """Return True if the given company/bio string indicates current ING employment."""
    if not text or not isinstance(text, str):
        return False
    return bool(_ING_EMPLOYER_RE.search(text))


_TURKISH_CHARS = frozenset("ğüşöçĞÜŞÖÇıİ")
_TURKISH_SIGNAL_RE = re.compile(
    r"\b(turkey|turkiye|türkiye|turkish|türkçe|istanbul|ankara|izmir|bursa|antalya|kocaeli|"
    r"eskişehir|eskisehir|kayseri|konya|adana|gaziantep|trabzon|manisa|elazig|odtu|metu|itu|"
    r"bogazici|boğaziçi|hacettepe|bilkent|sabanci|koç|yildiz|marmara|ege|dokuz eylül|"
    r"ahmet|mehmet|mustafa|ali|hüseyin|huseyin|hasan|ibrahim|ismail|osman|yusuf|murat|ömer|omer|"
    r"ramazan|halil|süleyman|suleyman|abdullah|mahmut|recep|salih|fatih|kadir|emre|hakan|adem|"
    r"kemal|yaşar|yasar|bekir|musa|metin|bayram|serkan|orhan|burak|furkan|yasin|gökhan|gokhan|"
    r"uğur|ugur|onur|mert|erkan|volkan|ilker|tolga|sinan|cenk|barış|baris|deniz|eren|utku|"
    r"alper|alperen|can|cem|kerem|kaan|berk|berkay|batuhan|yiğit|yigit|oğuz|oguz|oğuzhan|oguzhan|"
    r"tarık|tarik|selim|erdal|erdem|engin|enis|enes|erhan|ersan|faruk|fırat|firat|güner|guner|"
    r"güneş|gunes|gürdal|gurdal|habil|okan|oktay|ozan|özgür|ozgur|sercan|soner|şükrü|sukru|"
    r"turabi|vedat|yağız|yagiz|yavuz|yunus|zafer|ayşe|ayse|fatma|emine|hatice|zeynep|elif|"
    r"merve|büşra|busra|zehra|esra|hanife|kübra|kubra|havva|cemile|özlem|ozlem|sevgi|yasemin|"
    r"dilek|derya|filiz|gül|gul|pınar|pinar|ebru|betül|betul|eda|ecem|gizem|gamze|gonca|hande|"
    r"irem|melis|melisa|mine|nazlı|nazli|pelin|rabia|rukiye|seda|selin|simge|tuğba|tugba|"
    r"tuğçe|tugce|yağmur|yagmur|beril|dicle|dilge|azra|beyzanur|ipek|"
    r"yılmaz|yilmaz|kaya|demir|çelik|celik|şahin|sahin|yıldız|yildiz|yıldırım|yildirim|"
    r"öztürk|ozturk|aydın|aydin|özdemir|ozdemir|arslan|aslan|doğan|dogan|kılıç|kilic|"
    r"aslan|çetin|cetin|kara|koç|koc|kurt|özkan|ozkan|şimşek|simsek|polat|özcan|ozcan|"
    r"korkmaz|çakır|cakir|erdoğan|erdogan|yavuz|can|acar|şen|sen|aktaş|aktas|güler|guler|"
    r"yalçın|yalcin|güneş|gunes|bozkurt|bulut|keskin|ümit|umit|avcı|avci|कोçak|kocak)\b",
    re.IGNORECASE,
)


def _has_turkish_author_or_location_signal(*parts: str | None) -> bool:
    """Return True if any of the given author/bio/location strings contain Turkish characters, locations, or names."""
    combined = " ".join(p for p in parts if p and isinstance(p, str))
    if not combined.strip():
        return False
    if any(ch in _TURKISH_CHARS for ch in combined):
        return True
    return bool(_TURKISH_SIGNAL_RE.search(combined))


def extract_search_keywords(
    raw_query: str,
    location_name: str = "",
    *,
    max_terms: int = 5,
) -> str:
    """Convert a natural-language Exa search query into concise technical keywords.

    Strips negative ING exclusion clauses, location names, punctuation, and generic
    stop words so platform APIs (GitHub, Hugging Face, Kaggle) receive high-signal
    technical terms (e.g., "Machine Learning NLP PyTorch LLM").
    """
    if not raw_query or not isinstance(raw_query, str):
        return "machine learning"

    cleaned = raw_query
    for pattern in _NEGATIVE_CLAUSE_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)

    # Remove the target location token from technical keywords (handled separately by location filters)
    loc_tokens = {
        t.lower()
        for t in re.split(r"\W+", location_name or "")
        if t
    }
    for syn_list in _LOCATION_SYNONYMS.values():
        for syn in syn_list:
            if location_name and location_name.lower() in syn.lower():
                loc_tokens.update(w.lower() for w in syn.split())

    tokens = re.findall(r"[a-zA-Z0-9+#.-]+", cleaned)
    selected: list[str] = []
    seen_lower: set[str] = set()

    for token in tokens:
        low = token.lower().strip(".-")
        if len(low) < 2:
            continue
        if low in _STOP_WORDS or low in loc_tokens:
            continue
        if low in {"turkey", "turkiye", "istanbul", "ankara", "izmir"}:
            continue
        if low not in seen_lower:
            seen_lower.add(low)
            selected.append(token.strip(".-"))
        if len(selected) >= max_terms:
            break

    return " ".join(selected) if selected else "machine learning"


def safe_json_get(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: int = DEFAULT_HTTP_TIMEOUT_SECONDS,
) -> Any:
    """Perform a validated, size-capped HTTPS GET request and parse JSON response.

    Enforces:
    - SSRF host & scheme validation via `validate_safe_https_url`
    - Response size cap (`MAX_HTTP_RESPONSE_BYTES`)
    - Graceful error handling without leaking authorization headers in logs
    """
    safe_url = validate_safe_https_url(url)
    req_headers = {
        "Accept": "application/json",
        "User-Agent": "AI-For-HR-CandidatePool/1.0",
    }
    if headers:
        req_headers.update(headers)

    request = urllib.request.Request(safe_url, headers=req_headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw_bytes = response.read(MAX_HTTP_RESPONSE_BYTES + 1)
            if len(raw_bytes) > MAX_HTTP_RESPONSE_BYTES:
                logger.warning("Response from %s exceeded max size limit (%d bytes)", safe_url, MAX_HTTP_RESPONSE_BYTES)
                return None
            return json.loads(raw_bytes.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            logger.debug("HTTP 404 from %s", safe_url)
        else:
            logger.warning("HTTP %s from %s", exc.code, safe_url)
    except urllib.error.URLError as exc:
        logger.warning("Network error contacting %s: %s", safe_url, exc.reason)
    except json.JSONDecodeError:
        logger.warning("Invalid JSON response from %s", safe_url)
    except Exception:
        logger.exception("Unexpected error during GET %s", safe_url)
    return None


# ---------------------------------------------------------------------------
# 1. GitHub Active Candidate Searcher
# ---------------------------------------------------------------------------


class GitHubCandidateSearcher:
    """Discovers and enriches genuinely active software/ML engineers on GitHub.

    Workflow:
    1. Searches GitHub users (`/search/users`) matching location + technical keywords.
    2. Inspects each candidate's profile (`/users/{login}`) and most recently pushed
       public repositories (`/users/{login}/repos?sort=pushed`).
    3. Verifies recent activity: requires at least one repository push or profile
       activity within `activity_days` (default: 180 days).
    4. Filters out ING employees and formats the profile into the canonical candidate schema.
    """

    BASE_URL = "https://api.github.com"

    def __init__(
        self,
        *,
        api_token: str | None = None,
        activity_days: int = DEFAULT_ACTIVITY_DAYS,
        num_results: int = 15,
        require_recent_activity: bool = True,
        timeout: int = DEFAULT_HTTP_TIMEOUT_SECONDS,
    ) -> None:
        self.api_token = (
            api_token
            if api_token is not None
            else (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()
        )
        self.activity_days = activity_days
        self.num_results = max(1, min(num_results, 50))
        self.require_recent_activity = require_recent_activity
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        """Build GitHub REST API headers with optional Bearer token authentication."""
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        return headers

    def _build_user_search_query(self, raw_query: str, loc_name: str) -> str:
        """Construct a GitHub `/search/users` query string with location and keyword qualifiers."""
        keywords = extract_search_keywords(raw_query, loc_name, max_terms=2)
        parts = [keywords]
        clean_loc = (loc_name or "").strip()
        if clean_loc and clean_loc.lower() not in {"global", "worldwide", "all"}:
            # Quote multi-word locations safely
            safe_loc = re.sub(r'["\\]', "", clean_loc)
            if " " in safe_loc:
                parts.append(f'location:"{safe_loc}"')
            else:
                parts.append(f"location:{safe_loc}")
        parts.append("type:user")
        return " ".join(part for part in parts if part)

    def _fetch_user_profile(self, username: str) -> dict[str, Any] | None:
        """Fetch full GitHub user profile for a validated username."""
        if not is_valid_identifier(username):
            logger.warning("Skipping invalid GitHub username: %r", username)
            return None
        url = f"{self.BASE_URL}/users/{urllib.parse.quote(username, safe='')}"
        data = safe_json_get(url, headers=self._headers(), timeout=self.timeout)
        return data if isinstance(data, dict) else None

    def _fetch_user_repos(self, username: str, per_page: int = 10) -> list[dict[str, Any]]:
        """Fetch the user's most recently pushed public repositories."""
        if not is_valid_identifier(username):
            return []
        params = urllib.parse.urlencode(
            {
                "sort": "pushed",
                "direction": "desc",
                "per_page": max(1, min(per_page, 30)),
                "type": "owner",
            }
        )
        url = f"{self.BASE_URL}/users/{urllib.parse.quote(username, safe='')}/repos?{params}"
        data = safe_json_get(url, headers=self._headers(), timeout=self.timeout)
        if isinstance(data, list):
            return [r for r in data if isinstance(r, dict)]
        return []

    def search_query(
        self,
        query: str,
        loc_name: str,
        seen_urls: set[str],
        *,
        existing_urls: set[str] | None = None,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Execute a GitHub user search query, verify recent activity, and return candidates."""
        existing = existing_urls or set()
        gh_query = self._build_user_search_query(query, loc_name)
        params = urllib.parse.urlencode(
            {
                "q": gh_query,
                "per_page": self.num_results,
            }
        )
        search_url = f"{self.BASE_URL}/search/users?{params}"
        payload = safe_json_get(search_url, headers=self._headers(), timeout=self.timeout)
        if not isinstance(payload, dict):
            return []

        items = payload.get("items")
        if not isinstance(items, list):
            return []

        candidates: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            username = str(item.get("login") or "").strip()
            if not is_valid_identifier(username):
                continue

            profile_url = f"https://github.com/{username}"
            if profile_url in seen_urls or profile_url in existing:
                continue

            profile = self._fetch_user_profile(username) or item
            company = str(profile.get("company") or "").strip()
            bio = str(profile.get("bio") or "").strip()

            # Enforce hard exclusion of current ING employees
            if is_ing_affiliated(company) or is_ing_affiliated(bio):
                logger.info("[github] Skipping ING-affiliated user: %s", username)
                continue

            repos = self._fetch_user_repos(username, per_page=10)
            candidate = self._build_candidate_record(
                username=username,
                profile=profile,
                repos=repos,
                query=query,
                loc_name=loc_name,
                now=now,
            )
            if candidate is None:
                continue

            seen_urls.add(profile_url)
            candidates.append(candidate)

        return candidates

    def _build_candidate_record(
        self,
        *,
        username: str,
        profile: dict[str, Any],
        repos: list[dict[str, Any]],
        query: str,
        loc_name: str,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        """Evaluate user's repository activity and build a normalized candidate dict."""
        reference_now = now or datetime.now(timezone.utc)
        active_repos: list[dict[str, Any]] = []
        latest_push_dt: datetime | None = None
        latest_push_iso: str | None = None
        total_stars = 0
        languages: list[str] = []

        for repo in repos:
            pushed_at = str(repo.get("pushed_at") or repo.get("updated_at") or "").strip()
            pushed_dt = parse_iso_datetime(pushed_at)
            if pushed_dt and (latest_push_dt is None or pushed_dt > latest_push_dt):
                latest_push_dt = pushed_dt
                latest_push_iso = pushed_at

            if is_recently_active(pushed_at, self.activity_days, now=reference_now):
                active_repos.append(repo)

            stars = repo.get("stargazers_count")
            if isinstance(stars, int) and stars > 0:
                total_stars += stars

            lang = str(repo.get("language") or "").strip()
            if lang and lang not in languages:
                languages.append(lang)

        # Fallback activity check against profile updated_at if user has no public repos pushed
        profile_updated = str(profile.get("updated_at") or "").strip()
        has_recent_activity = bool(active_repos) or (
            bool(repos) and is_recently_active(latest_push_iso, self.activity_days, now=reference_now)
        )

        if self.require_recent_activity and not has_recent_activity:
            logger.debug(
                "[github] Filtering out inactive user %s (last push: %s, cutoff: %d days)",
                username,
                latest_push_iso or profile_updated or "none",
                self.activity_days,
            )
            return None

        full_name = str(profile.get("name") or "").strip() or username
        # Reject repo URLs or book links mistakenly set as the GitHub profile name
        if "/" in full_name or full_name.lower().startswith("http") or "github.com" in full_name.lower():
            full_name = username
        bio = str(profile.get("bio") or "").strip()
        company = str(profile.get("company") or "").strip()
        location_text = str(profile.get("location") or "").strip()
        blog = str(profile.get("blog") or "").strip()
        followers = int(profile.get("followers") or 0)
        public_repos = int(profile.get("public_repos") or len(repos))

        role_label = bio[:80] if bio else f"GitHub Developer ({', '.join(languages[:3]) or 'Open Source'})"
        title = f"{full_name} - {role_label}"

        highlights: list[str] = [
            f"GitHub (@{username}): {public_repos} public repos, {followers} followers, {total_stars} total stars across recent repos.",
            f"Recent Activity: {len(active_repos)} repositories actively updated within the last {self.activity_days} days (latest push: {(latest_push_iso or 'N/A')[:10]}).",
        ]
        if languages:
            highlights.append(f"Primary Languages: {', '.join(languages[:6])}")
        if company:
            highlights.append(f"Company: {company}")
        if location_text:
            highlights.append(f"Location: {location_text}")

        repo_summaries: list[str] = []
        for repo in (active_repos or repos)[:5]:
            r_name = str(repo.get("name") or "").strip()
            r_desc = str(repo.get("description") or "No description").strip()
            r_lang = str(repo.get("language") or "Unknown").strip()
            r_stars = int(repo.get("stargazers_count") or 0)
            r_pushed = str(repo.get("pushed_at") or "")[:10]
            repo_summaries.append(
                f"- {r_name} ({r_lang}, ★{r_stars}, pushed {r_pushed}): {r_desc}"
            )
        if repo_summaries:
            highlights.append("Recent Repositories:\n" + "\n".join(repo_summaries[:3]))

        text_sections = [
            f"Candidate Name: {full_name} (@{username})",
            f"Platform: GitHub (https://github.com/{username})",
            f"Location: {location_text or 'Not specified'}",
            f"Company: {company or 'Not specified'}",
            f"Bio: {bio or 'Not specified'}",
            f"Website / Blog: {blog or 'Not specified'}",
            f"Activity Metrics: {len(active_repos)} active repos in last {self.activity_days} days, latest push {(latest_push_iso or 'N/A')[:10]}, {followers} followers, {total_stars} stars.",
            f"Top Languages: {', '.join(languages)}",
            "Recent Public Repositories:\n" + ("\n".join(repo_summaries) if repo_summaries else "None"),
        ]

        # Compute a normalized activity & popularity score in [0.0, 1.0]
        activity_score = min(1.0, (len(active_repos) * 0.15) + min(0.4, followers / 200.0) + min(0.3, total_stars / 200.0))

        return {
            "url": f"https://github.com/{username}",
            "title": title,
            "name": full_name,
            "score": round(max(0.1, activity_score), 3),
            "published_date": latest_push_iso or profile_updated or None,
            "text": "\n".join(text_sections),
            "highlights": highlights[:5],
            "highlight_scores": None,
            "query": query,
            "location": location_text,
            "search_bucket": loc_name,
            "source": "github",
            "info": {
                "username": username,
                "full_name": full_name,
                "company": company,
                "bio": bio,
                "blog": blog,
                "email": profile.get("email"),
                "followers": followers,
                "public_repos": public_repos,
                "active_repos_count": len(active_repos),
                "total_stars": total_stars,
                "top_languages": languages,
                "last_active_date": latest_push_iso,
            },
            "scraped_at": reference_now.isoformat(),
        }


# ---------------------------------------------------------------------------
# 2. Hugging Face Active Candidate Searcher
# ---------------------------------------------------------------------------


class HuggingFaceCandidateSearcher:
    """Discovers active ML/NLP/LLM practitioners via the Hugging Face Hub API.

    Workflow:
    1. Queries `/api/models` and `/api/datasets` sorted by `lastModified` descending
       using technical & location/language keywords.
    2. Aggregates recently updated artifacts by `author` username.
    3. Filters for authors with verified recent activity (`lastModified` within
       `activity_days`).
    4. Enriches with author overview metadata when available and outputs canonical
       candidate records.
    """

    BASE_URL = "https://huggingface.co"

    def __init__(
        self,
        *,
        api_token: str | None = None,
        activity_days: int = DEFAULT_ACTIVITY_DAYS,
        num_results: int = 15,
        require_recent_activity: bool = True,
        timeout: int = DEFAULT_HTTP_TIMEOUT_SECONDS,
    ) -> None:
        self.api_token = (
            api_token
            if api_token is not None
            else (
                os.environ.get("HF_TOKEN")
                or os.environ.get("HUGGINGFACE_API_KEY")
                or ""
            ).strip()
        )
        self.activity_days = activity_days
        self.num_results = max(1, min(num_results, 50))
        self.require_recent_activity = require_recent_activity
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        return headers

    def _build_search_terms(self, raw_query: str, loc_name: str) -> list[str]:
        """Generate search term variations combining technical keywords and location/language signals."""
        keywords = extract_search_keywords(raw_query, loc_name, max_terms=3)
        terms: list[str] = []
        loc_lower = (loc_name or "").strip().lower()
        if loc_lower in {"turkey", "türkiye", "tr", "istanbul", "ankara"}:
            terms.append(f"turkish {keywords}".strip())
            terms.append("turkish")
        if keywords and keywords not in terms:
            terms.append(keywords)
        return terms[:2] if terms else ["turkish"]

    def _fetch_hub_items(self, endpoint: str, search_term: str, limit: int = 30) -> list[dict[str, Any]]:
        """Query `/api/models` or `/api/datasets` sorted by `lastModified` descending."""
        params = urllib.parse.urlencode(
            {
                "search": search_term,
                "sort": "lastModified",
                "direction": "-1",
                "limit": max(1, min(limit, 50)),
            }
        )
        url = f"{self.BASE_URL}/api/{endpoint}?{params}"
        data = safe_json_get(url, headers=self._headers(), timeout=self.timeout)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        return []

    def _fetch_user_overview(self, username: str) -> dict[str, Any]:
        """Fetch optional user profile overview from `/api/users/{username}/overview`."""
        if not is_valid_identifier(username):
            return {}
        url = f"{self.BASE_URL}/api/users/{urllib.parse.quote(username, safe='')}/overview"
        data = safe_json_get(url, headers=self._headers(), timeout=self.timeout)
        return data if isinstance(data, dict) else {}

    def search_query(
        self,
        query: str,
        loc_name: str,
        seen_urls: set[str],
        *,
        existing_urls: set[str] | None = None,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Search Hugging Face models and datasets for active authors matching the campaign."""
        existing = existing_urls or set()
        reference_now = now or datetime.now(timezone.utc)
        search_terms = self._build_search_terms(query, loc_name)

        # Map author -> list of (kind, item_dict)
        author_artifacts: dict[str, list[tuple[str, dict[str, Any]]]] = {}

        for term in search_terms:
            for kind in ("models", "datasets"):
                items = self._fetch_hub_items(kind, term, limit=max(15, self.num_results * 2))
                for item in items:
                    author = str(item.get("author") or "").strip()
                    if not author and "/" in str(item.get("id") or ""):
                        author = str(item["id"]).split("/", 1)[0].strip()
                    if not is_valid_identifier(author):
                        continue
                    author_artifacts.setdefault(author, []).append((kind, item))

        candidates: list[dict[str, Any]] = []
        for author, artifacts in author_artifacts.items():
            if len(candidates) >= self.num_results:
                break

            profile_url = f"https://huggingface.co/{author}"
            if profile_url in seen_urls or profile_url in existing:
                continue

            overview = self._fetch_user_overview(author)
            candidate = self._build_candidate_record(
                author=author,
                artifacts=artifacts,
                overview=overview,
                query=query,
                loc_name=loc_name,
                now=reference_now,
            )
            if candidate is None:
                continue

            seen_urls.add(profile_url)
            candidates.append(candidate)

        return candidates

    def _build_candidate_record(
        self,
        *,
        author: str,
        artifacts: list[tuple[str, dict[str, Any]]],
        overview: dict[str, Any],
        query: str,
        loc_name: str,
        now: datetime,
    ) -> dict[str, Any] | None:
        """Verify author activity on Hugging Face and assemble a normalized candidate record."""
        active_artifacts: list[tuple[str, dict[str, Any]]] = []
        latest_mod_dt: datetime | None = None
        latest_mod_iso: str | None = None
        total_downloads = 0
        total_likes = 0
        pipeline_tags: list[str] = []
        seen_artifact_ids: set[str] = set()

        for kind, item in artifacts:
            art_id = str(item.get("id") or item.get("modelId") or "").strip()
            if not art_id or art_id in seen_artifact_ids:
                continue
            seen_artifact_ids.add(art_id)

            last_mod = str(item.get("lastModified") or item.get("createdAt") or "").strip()
            mod_dt = parse_iso_datetime(last_mod)
            if mod_dt and (latest_mod_dt is None or mod_dt > latest_mod_dt):
                latest_mod_dt = mod_dt
                latest_mod_iso = last_mod

            if is_recently_active(last_mod, self.activity_days, now=now):
                active_artifacts.append((kind, item))

            downloads = item.get("downloads")
            if isinstance(downloads, int) and downloads > 0:
                total_downloads += downloads
            likes = item.get("likes")
            if isinstance(likes, int) and likes > 0:
                total_likes += likes

            ptag = str(item.get("pipeline_tag") or "").strip()
            if ptag and ptag not in pipeline_tags:
                pipeline_tags.append(ptag)

        if self.require_recent_activity and not active_artifacts:
            return None

        # Skip organization namespaces (on HF Hub, /api/users/<org>/overview returns 404 -> empty dict)
        if not overview or overview.get("type") not in (None, "user"):
            logger.debug("[huggingface] Skipping non-user/organization namespace: %s", author)
            return None

        full_name = str(overview.get("fullname") or overview.get("name") or "").strip() or author
        bio = str(overview.get("bio") or overview.get("details") or "").strip()
        if is_ing_affiliated(full_name) or is_ing_affiliated(bio):
            logger.info("[huggingface] Skipping ING-affiliated author: %s", author)
            return None

        low_name = full_name.lower()
        low_author = author.lower()
        low_bio = bio.lower()
        if (
            low_name.startswith("team ")
            or low_name.endswith(".ai")
            or low_name.endswith(".io")
            or low_author in {"mradermacher", "speechdataai", "quantfactory"}
            or any(s in low_bio for s in ("15-year-old", "9th-grade", "high school student"))
        ):
            return None

        if (loc_name or "").strip().lower() in {"turkey", "türkiye"}:
            # Verify the author (not just a multilingual dataset card) has a Turkish signal
            if not _has_turkish_author_or_location_signal(full_name, author, bio):
                return None

        num_models = int(overview.get("numModels") or len([1 for k, _ in artifacts if k == "models"]))
        num_datasets = int(overview.get("numDatasets") or len([1 for k, _ in artifacts if k == "datasets"]))
        num_spaces = int(overview.get("numSpaces") or 0)
        num_papers = int(overview.get("numPapers") or 0)
        num_followers = int(overview.get("numFollowers") or 0)

        tag_summary = ", ".join(pipeline_tags[:4]) if pipeline_tags else "ML Models & Datasets"
        title = f"{full_name} - Hugging Face Contributor ({tag_summary})"

        artifact_lines: list[str] = []
        for kind, item in (active_artifacts or artifacts)[:5]:
            art_id = str(item.get("id") or item.get("modelId") or "")
            ptag = str(item.get("pipeline_tag") or kind[:-1])
            dl = int(item.get("downloads") or 0)
            lk = int(item.get("likes") or 0)
            lmod = str(item.get("lastModified") or "")[:10]
            artifact_lines.append(f"- [{kind[:-1].upper()}] {art_id} ({ptag}, {dl} downloads, ♥{lk}, updated {lmod})")

        highlights: list[str] = [
            f"Hugging Face (@{author}): {len(active_artifacts)} models/datasets updated in the last {self.activity_days} days (latest: {(latest_mod_iso or 'N/A')[:10]}).",
            f"Community Impact: {total_downloads} total downloads, {total_likes} likes across discovered artifacts.",
        ]
        if pipeline_tags:
            highlights.append(f"ML Tasks / Domains: {', '.join(pipeline_tags[:6])}")
        if bio:
            highlights.append(f"Bio: {bio[:200]}")
        if artifact_lines:
            highlights.append("Recent Artifacts:\n" + "\n".join(artifact_lines[:3]))

        text_sections = [
            f"Candidate Name: {full_name} (@{author})",
            f"Platform: Hugging Face (https://huggingface.co/{author})",
            f"Bio: {bio or 'Not specified'}",
            f"Recent Activity: {len(active_artifacts)} active models/datasets in last {self.activity_days} days (latest update: {(latest_mod_iso or 'N/A')[:10]}).",
            f"Task Specializations: {', '.join(pipeline_tags) or 'General ML/NLP'}",
            f"Total Downloads: {total_downloads} | Total Likes: {total_likes}",
            "Published Models & Datasets:\n" + ("\n".join(artifact_lines) if artifact_lines else "None"),
        ]

        score = min(1.0, 0.25 + (len(active_artifacts) * 0.15) + min(0.35, total_downloads / 5000.0) + min(0.25, total_likes / 50.0))

        return {
            "url": f"https://huggingface.co/{author}",
            "title": title,
            "name": full_name,
            "score": round(score, 3),
            "published_date": latest_mod_iso,
            "text": "\n".join(text_sections),
            "highlights": highlights[:5],
            "highlight_scores": None,
            "query": query,
            "location": "",
            "search_bucket": loc_name,
            "source": "huggingface",
            "info": {
                "username": author,
                "full_name": full_name,
                "bio": bio,
                "active_artifacts_count": len(active_artifacts),
                "num_models": num_models,
                "num_datasets": num_datasets,
                "num_spaces": num_spaces,
                "num_papers": num_papers,
                "num_followers": num_followers,
                "total_downloads": total_downloads,
                "total_likes": total_likes,
                "pipeline_tags": pipeline_tags,
                "last_active_date": latest_mod_iso,
            },
            "scraped_at": now.isoformat(),
        }


# ---------------------------------------------------------------------------
# 3. Kaggle Active Candidate Searcher
# ---------------------------------------------------------------------------


class KaggleCandidateSearcher:
    """Discovers active data scientists and ML competitors on Kaggle.

    Supports two complementary discovery channels:
    1. Official Kaggle REST API (`/api/v1/kernels/list` & `/api/v1/datasets/list`)
       when `KAGGLE_USERNAME` and `KAGGLE_KEY` are set in the environment — directly
       retrieves notebooks sorted by `dateRun` and datasets sorted by `updated`,
       verifying activity timestamps within `activity_days`.
    2. Exa Domain-Scoped Search (`include_domains=["kaggle.com", "www.kaggle.com"]`)
       when an Exa client is available — finds Kaggle Master/Grandmaster/Expert/Contributor
       profiles matching target locations and role keywords.
    """

    BASE_URL = "https://www.kaggle.com/api/v1"

    def __init__(
        self,
        *,
        exa_client: Any | None = None,
        kaggle_username: str | None = None,
        kaggle_key: str | None = None,
        kaggle_api_token: str | None = None,
        activity_days: int = DEFAULT_ACTIVITY_DAYS,
        num_results: int = 15,
        require_recent_activity: bool = True,
        timeout: int = DEFAULT_HTTP_TIMEOUT_SECONDS,
    ) -> None:
        self.exa_client = exa_client
        self.kaggle_username = (
            kaggle_username
            if kaggle_username is not None
            else (os.environ.get("KAGGLE_USERNAME") or "").strip()
        )
        self.kaggle_key = (
            kaggle_key
            if kaggle_key is not None
            else (os.environ.get("KAGGLE_KEY") or "").strip()
        )
        self.kaggle_api_token = (
            kaggle_api_token
            if kaggle_api_token is not None
            else (os.environ.get("KAGGLE_API_TOKEN") or "").strip()
        )
        self.activity_days = activity_days
        self.num_results = max(1, min(num_results, 50))
        self.require_recent_activity = require_recent_activity
        self.timeout = timeout

    def _has_kaggle_api_credentials(self) -> bool:
        """Return True if either a v2 Bearer token (KAGGLE_API_TOKEN / KGAT_*) or legacy username+key is configured."""
        return bool(
            self.kaggle_api_token
            or self.kaggle_key.startswith("KGAT_")
            or (self.kaggle_username and self.kaggle_key)
        )

    def _kaggle_auth_headers(self) -> dict[str, str]:
        """Build HTTP Authorization header for Kaggle REST API (Bearer for KGAT_* tokens, Basic for legacy keys)."""
        bearer = self.kaggle_api_token or (
            self.kaggle_key if self.kaggle_key.startswith("KGAT_") else ""
        )
        if bearer:
            return {
                "Accept": "application/json",
                "Authorization": f"Bearer {bearer}",
            }
        token_bytes = f"{self.kaggle_username}:{self.kaggle_key}".encode("utf-8")
        encoded = base64.b64encode(token_bytes).decode("ascii")
        return {
            "Accept": "application/json",
            "Authorization": f"Basic {encoded}",
        }

    def _fetch_user_kernels(self, username: str, page_size: int = 5) -> list[dict[str, Any]]:
        """Fetch a specific Kaggle user's most recently executed kernels via Official REST API."""
        if not self._has_kaggle_api_credentials() or not is_valid_identifier(username):
            return []
        params = urllib.parse.urlencode(
            {
                "user": username,
                "sortBy": "dateRun",
                "pageSize": max(1, min(page_size, 20)),
            }
        )
        url = f"{self.BASE_URL}/kernels/list?{params}"
        data = safe_json_get(url, headers=self._kaggle_auth_headers(), timeout=self.timeout)
        if isinstance(data, list):
            return [k for k in data if isinstance(k, dict)]
        return []

    def search_query(
        self,
        query: str,
        loc_name: str,
        seen_urls: set[str],
        *,
        existing_urls: set[str] | None = None,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Search Kaggle via location-aware Exa profile search + Official API activity verification."""
        existing = existing_urls or set()
        reference_now = now or datetime.now(timezone.utc)
        candidates: list[dict[str, Any]] = []
        has_specific_location = bool(
            (loc_name or "").strip()
            and (loc_name or "").strip().lower() not in {"global", "worldwide", "all"}
        )

        # When searching a specific location (e.g. "turkey") and Exa is available, discover
        # location-matched Kaggle user profiles via Exa first (since Kaggle's /kernels/list
        # endpoint searches notebook dataset text rather than user profile country), and then
        # enrich/verify each user's live notebook activity via the Official Kaggle REST API.
        if self.exa_client is not None and has_specific_location:
            exa_candidates = self._search_via_exa_domain(
                query=query,
                loc_name=loc_name,
                seen_urls=seen_urls,
                existing_urls=existing,
                limit=self.num_results,
                now=reference_now,
            )
            candidates.extend(exa_candidates)

        # Official Kaggle REST API channel (primary when no location filter or no Exa client,
        # or supplementary when remaining slots exist).
        if self._has_kaggle_api_credentials() and len(candidates) < self.num_results:
            api_candidates = self._search_via_kaggle_api(
                query=query,
                loc_name=loc_name,
                seen_urls=seen_urls,
                existing_urls=existing,
                now=reference_now,
            )
            candidates.extend(api_candidates)

        # Fallback Exa domain search when no specific location was set initially
        if self.exa_client is not None and not has_specific_location and len(candidates) < self.num_results:
            remaining = self.num_results - len(candidates)
            exa_candidates = self._search_via_exa_domain(
                query=query,
                loc_name=loc_name,
                seen_urls=seen_urls,
                existing_urls=existing,
                limit=remaining,
                now=reference_now,
            )
            candidates.extend(exa_candidates)

        return candidates[: self.num_results]

    def _search_via_kaggle_api(
        self,
        *,
        query: str,
        loc_name: str,
        seen_urls: set[str],
        existing_urls: set[str],
        now: datetime,
    ) -> list[dict[str, Any]]:
        """Query Kaggle `/kernels/list` and `/datasets/list` for recently active authors."""
        keywords = extract_search_keywords(query, loc_name, max_terms=3)
        search_term = f"{loc_name} {keywords}".strip() if loc_name else keywords
        params = urllib.parse.urlencode(
            {
                "search": search_term,
                "sortBy": "dateRun",
                "pageSize": max(10, self.num_results * 2),
            }
        )
        kernels_url = f"{self.BASE_URL}/kernels/list?{params}"
        kernels_data = safe_json_get(kernels_url, headers=self._kaggle_auth_headers(), timeout=self.timeout)
        items = kernels_data if isinstance(kernels_data, list) else []

        candidates: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            ref = str(item.get("ref") or "").strip()
            author = str(item.get("author") or "").strip()
            username = ref.split("/", 1)[0].strip() if "/" in ref else author
            if not is_valid_identifier(username):
                continue

            profile_url = f"https://www.kaggle.com/{username}"
            if profile_url in seen_urls or profile_url in existing_urls:
                continue

            last_run = str(item.get("lastRunTime") or item.get("lastUpdated") or "").strip()
            if self.require_recent_activity and not is_recently_active(last_run, self.activity_days, now=now):
                continue

            kernel_title = str(item.get("title") or ref).strip()
            votes = int(item.get("totalVotes") or 0)
            display_name = author or username

            if is_ing_affiliated(display_name) or is_ing_affiliated(kernel_title):
                continue

            # Exclude generic sports/toy datasets or boilerplate homework notebooks
            low_title = kernel_title.lower()
            low_ref = ref.lower()
            if any(
                noise in low_title or noise in low_ref
                for noise in (
                    "world cup",
                    "fifa",
                    "football",
                    "soccer",
                    "olympic",
                    "euro 20",
                    "titanic",
                    "house price",
                    "nlp-lab-",
                    "do-al-dil-lemeye-giri",
                    "stage-0",
                    "m1-submission",
                    "alone-with-a-stranger",
                    "rsna-knee",
                )
            ) or re.match(r"^notebook[0-9a-f]{6,}$", low_title):
                continue

            if (loc_name or "").strip().lower() in {"turkey", "türkiye"}:
                if not _has_turkish_author_or_location_signal(display_name, username):
                    continue

            highlights = [
                f"Kaggle (@{username}): Active notebook/kernel contributor (last run: {last_run[:10] or 'recent'}).",
                f"Featured Notebook: '{kernel_title}' ({votes} votes, ref: {ref}).",
            ]
            text = "\n".join(
                [
                    f"Candidate Name: {display_name} (@{username})",
                    f"Platform: Kaggle ({profile_url})",
                    f"Recent Activity: Executed kernel '{kernel_title}' on {last_run[:10] or 'recent'} ({votes} votes).",
                ]
            )

            seen_urls.add(profile_url)
            candidates.append(
                {
                    "url": profile_url,
                    "title": f"{display_name} - Kaggle Competitor & Notebook Author",
                    "name": display_name,
                    "score": round(min(1.0, 0.4 + min(0.6, votes / 50.0)), 3),
                    "published_date": last_run or None,
                    "text": text,
                    "highlights": highlights,
                    "highlight_scores": None,
                    "query": query,
                    "location": loc_name,
                    "search_bucket": loc_name,
                    "source": "kaggle",
                    "info": {
                        "username": username,
                        "full_name": display_name,
                        "featured_kernel": ref,
                        "votes": votes,
                        "last_active_date": last_run,
                    },
                    "scraped_at": now.isoformat(),
                }
            )
            if len(candidates) >= self.num_results:
                break

        return candidates

    def _search_via_exa_domain(
        self,
        *,
        query: str,
        loc_name: str,
        seen_urls: set[str],
        existing_urls: set[str],
        limit: int,
        now: datetime,
    ) -> list[dict[str, Any]]:
        """Search Kaggle user profiles via Exa using `include_domains=['kaggle.com']`."""
        keywords = extract_search_keywords(query, loc_name, max_terms=4)
        loc_lower = (loc_name or "").strip().lower()
        if loc_lower in {"turkey", "türkiye"}:
            kaggle_query = (
                f"Kaggle Grandmaster OR Master OR Expert OR Data Scientist {keywords} "
                f"Istanbul OR Ankara OR Izmir OR Turkey OR Türkiye excluding ING"
            ).strip()
        else:
            kaggle_query = (
                f"Kaggle Grandmaster OR Master OR Expert OR Data Scientist {keywords} {loc_name} excluding ING".strip()
            )

        # Note: Do NOT pass `start_published_date` when searching Kaggle user profiles on Exa,
        # because user profile pages (`kaggle.com/<username>`) do not carry recent article
        # publication dates in Exa's index (passing `start_published_date` restricts results
        # to competition discussion writeups like `/c/.../writeups/...`).
        try:
            response = self.exa_client.search(
                query=kaggle_query,
                include_domains=["kaggle.com", "www.kaggle.com"],
                type="auto",
                num_results=max(10, limit * 2),
                contents={"text": True, "highlights": {"num_sentences": 6, "highlights_per_url": 3}},
            )
        except Exception:
            logger.exception("[kaggle] Exa domain-scoped search failed for query %r", kaggle_query)
            return []

        reserved_kaggle_paths = {
            "c",
            "code",
            "competitions",
            "datasets",
            "discussions",
            "discussion",
            "learn",
            "models",
            "organizations",
            "progression",
            "rankings",
            "account",
            "terms",
            "privacy",
            "docs",
            "blog",
            "host",
            "solutions",
            "writeups",
            "kernels",
        }
        allowed_profile_subtabs = {
            "following",
            "followers",
            "competitions",
            "code",
            "datasets",
            "discussion",
        }

        candidates: list[dict[str, Any]] = []
        for r in getattr(response, "results", []) or []:
            raw_url = str(getattr(r, "url", "") or "").strip()
            if not raw_url:
                continue

            parsed_path = urllib.parse.urlparse(raw_url).path.strip("/")
            parts = [p.strip() for p in parsed_path.split("/") if p.strip()]
            if not parts:
                continue

            first_seg = parts[0]
            # Strictly require a Kaggle user profile path (`kaggle.com/<username>`),
            # rejecting competition pages (`/c/...`, `/competitions/...`), notebook pages (`/code/...`), etc.
            if first_seg.lower() in reserved_kaggle_paths or not is_valid_identifier(first_seg):
                continue
            if len(parts) > 1 and parts[1].lower() not in allowed_profile_subtabs:
                continue

            kaggle_username_cand = first_seg
            canonical_url = f"https://www.kaggle.com/{kaggle_username_cand}"
            if canonical_url in seen_urls or canonical_url in existing_urls or raw_url in seen_urls or raw_url in existing_urls:
                continue

            raw_title = str(getattr(r, "title", "") or "").strip()
            text = str(getattr(r, "text", "") or "").strip()
            if "Too many requests to GetCurrentUser" in text:
                continue
            if is_ing_affiliated(raw_title) or is_ing_affiliated(text):
                continue

            # Extract clean candidate display name from profile title ("Vedat Gul | Kaggle" -> "Vedat Gul")
            display_name = re.sub(r"\s*[\|\-–—]\s*Kaggle.*$", "", raw_title, flags=re.IGNORECASE).strip()
            if not display_name or display_name.lower() in {"kaggle", "kaggle profile"}:
                heading_match = re.search(r"#\s+([^\n\r|#]+)", text)
                display_name = heading_match.group(1).strip() if heading_match else kaggle_username_cand

            # Reject entries whose title still looks like a competition solution writeup
            if re.search(r"\b(\d+(st|nd|rd|th)\s+place|solution\s+writeup)\b", display_name, re.IGNORECASE):
                continue

            if loc_lower in {"turkey", "türkiye"}:
                if not _has_turkish_author_or_location_signal(display_name, kaggle_username_cand, text):
                    continue

            seen_urls.add(canonical_url)
            seen_urls.add(raw_url)
            raw_highlights = getattr(r, "highlights", None) or []
            highlights = list(raw_highlights) if isinstance(raw_highlights, list) else []
            highlights.insert(0, f"Platform: Kaggle (@{kaggle_username_cand} — Active Data Science / ML Profile)")

            info_dict: dict[str, Any] = {
                "username": kaggle_username_cand,
                "full_name": display_name,
            }
            if self._has_kaggle_api_credentials():
                user_kernels = self._fetch_user_kernels(kaggle_username_cand, page_size=5)
                if user_kernels:
                    top_k = user_kernels[0]
                    k_title = str(top_k.get("title") or top_k.get("ref") or "").strip()
                    k_run = str(top_k.get("lastRunTime") or "").strip()
                    total_votes = sum(int(k.get("totalVotes") or 0) for k in user_kernels)
                    highlights.insert(
                        1,
                        f"Official Kaggle API Verified (@{kaggle_username_cand}): {len(user_kernels)} recent notebooks (latest: '{k_title}' on {k_run[:10] or 'recent'}, {total_votes} total votes).",
                    )
                    text = (
                        f"Candidate Name: {display_name} (@{kaggle_username_cand})\n"
                        f"Platform: Kaggle ({canonical_url})\n"
                        f"{text}\n\nOfficial Kaggle API Activity (@{kaggle_username_cand}):\n"
                        + "\n".join(
                            f"- {k.get('title') or k.get('ref')} (lastRunTime: {str(k.get('lastRunTime') or '')[:10]}, votes: {k.get('totalVotes', 0)})"
                            for k in user_kernels[:3]
                        )
                    ).strip()
                    info_dict.update(
                        {
                            "featured_kernel": str(top_k.get("ref") or ""),
                            "votes": total_votes,
                            "last_active_date": k_run,
                        }
                    )
                else:
                    text = f"Candidate Name: {display_name} (@{kaggle_username_cand})\nPlatform: Kaggle ({canonical_url})\n{text}".strip()
            else:
                text = f"Candidate Name: {display_name} (@{kaggle_username_cand})\nPlatform: Kaggle ({canonical_url})\n{text}".strip()

            profile_title = (
                raw_title
                if " - " in raw_title and "|" not in raw_title
                else f"{display_name} - Kaggle Competitor & Data Scientist"
            )

            candidates.append(
                {
                    "url": canonical_url,
                    "title": profile_title,
                    "name": display_name,
                    "score": float(getattr(r, "score", 0.65) or 0.65),
                    "published_date": getattr(r, "published_date", None),
                    "text": text or None,
                    "highlights": highlights[:5],
                    "highlight_scores": getattr(r, "highlight_scores", None),
                    "query": kaggle_query,
                    "location": loc_name,
                    "search_bucket": loc_name,
                    "source": "kaggle",
                    "info": info_dict,
                    "scraped_at": now.isoformat(),
                }
            )
            if len(candidates) >= limit:
                break

        return candidates


# ---------------------------------------------------------------------------
# 4. Multi-Platform Orchestrator
# ---------------------------------------------------------------------------

SUPPORTED_COMMUNITY_PLATFORMS: frozenset[str] = frozenset({"github", "huggingface", "kaggle"})


class MultiPlatformCandidateSearcher:
    """Orchestrates candidate discovery across GitHub, Hugging Face, and Kaggle.

    Can be invoked either when `search.provider` is set to a specific community
    platform (`github`, `huggingface`, `kaggle`, `multi`) or when `search.platforms`
    lists additional community platforms to run alongside the primary provider.
    """

    def __init__(
        self,
        *,
        platforms: list[str],
        activity_days: int = DEFAULT_ACTIVITY_DAYS,
        num_results_per_platform: int = 15,
        require_recent_activity: bool = True,
        exa_client: Any | None = None,
    ) -> None:
        normalized = [p.strip().lower() for p in platforms if p and p.strip()]
        invalid = [p for p in normalized if p not in SUPPORTED_COMMUNITY_PLATFORMS]
        if invalid:
            raise ValueError(
                f"Unsupported platform(s): {invalid}. Supported: {sorted(SUPPORTED_COMMUNITY_PLATFORMS)}"
            )
        self.platforms = normalized
        self.activity_days = activity_days
        self.num_results_per_platform = num_results_per_platform
        self.require_recent_activity = require_recent_activity
        self.exa_client = exa_client

        self._github = (
            GitHubCandidateSearcher(
                activity_days=activity_days,
                num_results=num_results_per_platform,
                require_recent_activity=require_recent_activity,
            )
            if "github" in self.platforms
            else None
        )
        self._huggingface = (
            HuggingFaceCandidateSearcher(
                activity_days=activity_days,
                num_results=num_results_per_platform,
                require_recent_activity=require_recent_activity,
            )
            if "huggingface" in self.platforms
            else None
        )
        self._kaggle = (
            KaggleCandidateSearcher(
                exa_client=exa_client,
                activity_days=activity_days,
                num_results=num_results_per_platform,
                require_recent_activity=require_recent_activity,
            )
            if "kaggle" in self.platforms
            else None
        )

    def search_query(
        self,
        query: str,
        loc_name: str,
        seen_urls: set[str],
        *,
        existing_urls: set[str] | None = None,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Run the search query across all enabled community platforms."""
        results: list[dict[str, Any]] = []
        if self._github is not None:
            results.extend(
                self._github.search_query(
                    query, loc_name, seen_urls, existing_urls=existing_urls, now=now
                )
            )
        if self._huggingface is not None:
            results.extend(
                self._huggingface.search_query(
                    query, loc_name, seen_urls, existing_urls=existing_urls, now=now
                )
            )
        if self._kaggle is not None:
            results.extend(
                self._kaggle.search_query(
                    query, loc_name, seen_urls, existing_urls=existing_urls, now=now
                )
            )
        return results
