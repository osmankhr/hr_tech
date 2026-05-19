"""
YÖK Tez Merkezi — Incremental ML/DL/DS Thesis Scraper (v2)
-----------------------------------------------------------
Discovers DS/ML/DL theses from tez.yok.gov.tr and optionally enriches each
with advisor, institute, department, abstract, and keywords.

Incremental by default: auto-detects the last theses_YYYYMMDD.csv file in
data/ and only fetches theses from that year onward. Override with --from_date.

Outputs are written to data/ as theses_YYYYMMDD.csv and new_authors_YYYYMMDD.csv.
Detail pages are cached under .yok_cache/ and shared across runs.

Usage:
    # Default run: last 30 days, no enrichment
    python yok_scraper.py

    # With detail-page enrichment (advisor, abstract — adds significant time)
    python yok_scraper.py --enrich

    # Override start date (year resolution — YÖK only filters by year)
    python yok_scraper.py --from_date 2024-01-01

    # Resume if a previous run was interrupted
    python yok_scraper.py --resume

    # Narrow keyword/type scope
    python yok_scraper.py --keywords "derin öğrenme,deep learning" --types phd
"""

import argparse
import csv
import datetime
import html as html_lib
import http.cookiejar
import os
import re
import ssl
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, fields
from typing import Optional

try:
    import certifi
except ImportError as e:
    raise SystemExit("certifi is required. Install with: pip install certifi") from e

try:
    from bs4 import BeautifulSoup
except ImportError as e:
    raise SystemExit("beautifulsoup4 is required. Install with: pip install beautifulsoup4") from e

from utils import match_university, data_dir, today_str, last_run_date


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ML_KEYWORDS: list[str] = [
    "makine öğrenmesi", "machine learning",
    "derin öğrenme", "deep learning",
    "yapay zeka", "artificial intelligence",
    "veri bilimi", "data science",
    "yapay sinir ağı", "neural network",
    "doğal dil işleme", "natural language processing",
   # "agent",
    "pekiştirmeli öğrenme", "reinforcement learning",
    "büyük veri", "big data",
]

THESIS_TYPE_CODES: dict[str, str] = {
    "msc": "1",
    "phd": "2",
}

DEFAULT_YEAR_START = 2023

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE = "https://tez.yok.gov.tr/UlusalTezMerkezi"
BOOTSTRAP_URL = f"{BASE}/tarama.jsp"
SEARCH_URL = f"{BASE}/SearchTez"
DETAIL_URL = f"{BASE}/tezDetay.jsp"

CACHE_DIR = ".yok_cache"
POLITE_DELAY_SEC = 3.0
RESULT_CAP = 2000
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Thesis:
    tez_no: str
    thesis_key: str
    encrypted_no: str
    author: str
    year: str
    title: str
    title_en: str
    title_tr: str
    university: str
    university_raw: str
    language: str
    thesis_type: str
    subject: str
    advisor: str = ""
    institute: str = ""
    department: str = ""
    keywords: str = ""
    abstract: str = ""
    pdf_available: bool = False


# ---------------------------------------------------------------------------
# HTTP / session
# ---------------------------------------------------------------------------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def http_error_302(self, req, fp, code, msg, headers):
        return fp

    http_error_301 = http_error_303 = http_error_307 = http_error_302


_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


def _build_opener() -> urllib.request.OpenerDirector:
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=_SSL_CONTEXT),
        urllib.request.HTTPCookieProcessor(cj),
        _NoRedirect(),
    )
    opener.addheaders = [
        ("User-Agent", UA),
        ("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
        ("Accept-Language", "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7"),
    ]
    return opener


def _call(opener: urllib.request.OpenerDirector, url: str,
          data: Optional[bytes] = None, max_retries: int = 4):
    delay = 5.0
    for attempt in range(1, max_retries + 1):
        try:
            req = urllib.request.Request(url, data=data)
            return opener.open(req, timeout=60)
        except Exception as e:
            if attempt == max_retries:
                raise
            print(f"    [WARN] attempt {attempt} failed ({e}); retrying in {delay}s...")
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("unreachable")


def _follow_once(opener, resp):
    if resp.status not in (301, 302, 303, 307):
        return resp
    loc = resp.headers.get("Location", "")
    if loc.startswith("http://"):
        loc = "https://" + loc[len("http://"):]
    elif loc.startswith("/"):
        loc = "https://tez.yok.gov.tr" + loc
    return _call(opener, loc)


def bootstrap_session(opener) -> None:
    resp = _call(opener, BOOTSTRAP_URL)
    resp.read()


def _baseline_form() -> dict[str, str]:
    return {
        "TezNo": "",
        "TezAd": "",
        "AdSoyad": "",
        "DanismanAdSoyad": "",
        "Universite": "0",
        "Enstitu": "0",
        "ABD": "0",
        "BilimDali": "0",
        "uniad": "",
        "ensad": "",
        "abdad": "",
        "bilim": "",
        "Tur": "0",
        "Dil": "0",
        "izin": "0",
        "Durum": "3",
        "EnstituGrubu": "",
        "yil1": "0",
        "yil2": "0",
        "Dizin": "",
        "Metin": "",
        "Konu": "",
        "islem": "2",
        "Bolum": "0",
    }


def search_slice(opener, *, metin: str = "", yil1: str = "0", yil2: str = "0",
                 tur: str = "0") -> str:
    form = _baseline_form()
    form["Metin"] = metin
    form["yil1"] = yil1
    form["yil2"] = yil2
    form["Tur"] = tur
    body = urllib.parse.urlencode(form).encode("utf-8")
    resp = _call(opener, SEARCH_URL, data=body)
    resp = _follow_once(opener, resp)
    return resp.read().decode("utf-8", errors="replace")


def get_detail(opener, thesis_key: str, encrypted_no: str) -> str:
    url = (f"{DETAIL_URL}?id={urllib.parse.quote(thesis_key)}"
           f"&no={urllib.parse.quote(encrypted_no)}")
    resp = _call(opener, url)
    resp = _follow_once(opener, resp)
    return resp.read().decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Parsing — search results
# ---------------------------------------------------------------------------

_COUNT_RE = re.compile(r"(\d+)\s*kayıt bulundu")
_BLOCK_RE = re.compile(r"var doc\s*=\s*\{(.+?)\};", re.S)
_USERID_RE = re.compile(r"onclick=tezDetay\('([^']+)','([^']+)'\)>(\d+)</span>")
_FIELD_RE = re.compile(r'(\w+)\s*:\s*"((?:\\"|[^"])*)"', re.S)


def extract_total(html: str) -> Optional[int]:
    m = _COUNT_RE.search(html)
    return int(m.group(1)) if m else None


def _parse_title(raw: str) -> tuple[str, str, str]:
    raw = html_lib.unescape(raw)
    m = re.search(r"(.*?)<br>\s*<span[^>]*>(.*?)</span>", raw, re.S | re.I)
    if m:
        en = re.sub(r"<[^>]+>", " ", m.group(1))
        tr = re.sub(r"<[^>]+>", " ", m.group(2))
    else:
        en = re.sub(r"<[^>]+>", " ", raw)
        tr = ""
    en = re.sub(r"\s+", " ", en).strip()
    tr = re.sub(r"\s+", " ", tr).strip()
    combined = en if not tr else f"{en} / {tr}"
    return combined, en, tr


def parse_search_html(html: str) -> list[Thesis]:
    out: list[Thesis] = []
    for block_match in _BLOCK_RE.finditer(html):
        block = block_match.group(1)
        fields_map: dict[str, str] = {}
        for f in _FIELD_RE.finditer(block):
            fields_map[f.group(1)] = f.group(2).replace('\\"', '"')

        user_id_raw = fields_map.get("userId", "")
        m = _USERID_RE.search(user_id_raw)
        if not m:
            continue
        thesis_key, encrypted_no, tez_no = m.group(1), m.group(2), m.group(3)

        title, title_en, title_tr = _parse_title(fields_map.get("weight", ""))
        uni_raw = html_lib.unescape(fields_map.get("uni", "")).strip()

        out.append(Thesis(
            tez_no=tez_no,
            thesis_key=thesis_key,
            encrypted_no=encrypted_no,
            author=html_lib.unescape(fields_map.get("name", "")).strip(),
            year=fields_map.get("age", "").strip(),
            title=title,
            title_en=title_en,
            title_tr=title_tr,
            university=match_university(uni_raw) or "",
            university_raw=uni_raw,
            language=html_lib.unescape(fields_map.get("height", "")).strip(),
            thesis_type=html_lib.unescape(fields_map.get("important", "")).strip(),
            subject=html_lib.unescape(fields_map.get("someDate", "")).strip(),
        ))
    return out


# ---------------------------------------------------------------------------
# Parsing — detail page
# ---------------------------------------------------------------------------

def parse_detail_html(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    out = {
        "advisor": "",
        "institute": "",
        "department": "",
        "keywords": "",
        "abstract": "",
        "pdf_available": False,
    }

    if soup.find("a", href=lambda h: bool(h) and "TezGoster" in h):
        out["pdf_available"] = True

    text = soup.get_text("\n", strip=True)

    m = re.search(r"Danışman\s*:\s*([^\n]+)", text)
    if m:
        out["advisor"] = m.group(1).strip()

    m = re.search(r"Yer Bilgisi\s*:\s*([^\n]+)", text)
    if m:
        parts = [p.strip() for p in m.group(1).split("/")]
        if len(parts) >= 2:
            out["institute"] = parts[1]
        if len(parts) >= 3:
            out["department"] = parts[2]

    m = re.search(r"Dizin\s*:\s*([^\n]*)", text)
    if m:
        kw = m.group(1).strip()
        if any(sep in kw for sep in (",", ";", "=")):
            out["keywords"] = kw

    abstract = ""
    for td in soup.find_all("td"):
        txt = td.get_text(" ", strip=True)
        if "Yazar:" in txt or "Tez No" in txt:
            continue
        if len(txt) < 200:
            continue
        if len(txt) > len(abstract):
            abstract = txt
    out["abstract"] = abstract

    return out


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def _cache_path(tez_no: str) -> str:
    return os.path.join(CACHE_DIR, f"{tez_no}.html")


def cached_detail_html(tez_no: str) -> Optional[str]:
    path = _cache_path(tez_no)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


def write_cached_detail(tez_no: str, html: str) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(_cache_path(tez_no), "w", encoding="utf-8") as f:
        f.write(html)


# ---------------------------------------------------------------------------
# Dedup & summaries
# ---------------------------------------------------------------------------

def dedup_by_tez_no(theses: list[Thesis]) -> list[Thesis]:
    seen: dict[str, Thesis] = {}
    for t in theses:
        if t.tez_no not in seen:
            seen[t.tez_no] = t
    return list(seen.values())


def summarize_authors(theses: list[Thesis]) -> list[dict]:
    by: dict[str, dict] = {}
    for t in theses:
        entry = by.setdefault(t.author, {
            "name": t.author,
            "thesis_count": 0,
            "universities": set(),
            "types": set(),
            "years": set(),
            "tez_nos": [],
            "titles": [],
        })
        entry["thesis_count"] += 1
        if t.university:
            entry["universities"].add(t.university)
        entry["types"].add(t.thesis_type)
        entry["years"].add(t.year)
        entry["tez_nos"].append(t.tez_no)
        entry["titles"].append(t.title[:80])
    return sorted(by.values(), key=lambda e: -e["thesis_count"])


def summarize_advisors(theses: list[Thesis]) -> list[dict]:
    by: dict[str, dict] = {}
    for t in theses:
        if not t.advisor:
            continue
        entry = by.setdefault(t.advisor, {
            "advisor": t.advisor,
            "student_count": 0,
            "universities": set(),
            "years": set(),
            "departments": set(),
            "students": [],
        })
        entry["student_count"] += 1
        if t.university:
            entry["universities"].add(t.university)
        entry["years"].add(t.year)
        if t.department:
            entry["departments"].add(t.department)
        entry["students"].append(t.author)
    return sorted(by.values(), key=lambda e: -e["student_count"])


# ---------------------------------------------------------------------------
# Output / input
# ---------------------------------------------------------------------------

def save_theses(theses: list[Thesis], path: str) -> None:
    fns = [f.name for f in fields(Thesis)]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fns)
        w.writeheader()
        for t in theses:
            row = {k: getattr(t, k) for k in fns}
            row["pdf_available"] = "true" if row["pdf_available"] else "false"
            w.writerow(row)
    print(f"Saved {len(theses)} theses -> {path}")


def load_theses(path: str) -> list[Thesis]:
    if not os.path.exists(path):
        return []
    out: list[Thesis] = []
    fns = [f.name for f in fields(Thesis)]
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            row = {k: r.get(k, "") for k in fns}
            row["pdf_available"] = str(row.get("pdf_available", "")).lower() == "true"
            out.append(Thesis(**row))
    return out


# ---------------------------------------------------------------------------
# Incremental diff — new authors across runs
# ---------------------------------------------------------------------------

def _prev_theses_files(data_path: str) -> list[str]:
    """Return all data/theses_YYYYMMDD.csv paths except today's."""
    today = datetime.date.today().strftime("%Y%m%d")
    pat = re.compile(r"^theses_(\d{8})\.csv$")
    files = []
    try:
        for entry in os.scandir(data_path):
            m = pat.match(entry.name)
            if m and entry.is_file() and m.group(1) != today:
                files.append(entry.path)
    except FileNotFoundError:
        pass
    return files


def _seen_author_keys(prev_files: list[str]) -> set[tuple[str, str]]:
    """Return set of (author_lower, university) seen in past theses CSV files."""
    seen: set[tuple[str, str]] = set()
    for path in prev_files:
        if not os.path.exists(path):
            continue
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                author = row.get("author", "").strip().lower()
                uni = row.get("university", "").strip()
                if author:
                    seen.add((author, uni))
    return seen


def save_new_authors(theses: list[Thesis], prev_files: list[str], path: str) -> None:
    """
    Diff current theses against all past runs. Output one row per unique
    (author, university) pair that is new, sorted by university then author.
    """
    seen = _seen_author_keys(prev_files)

    # Group theses by (author, university), keeping only new pairs
    groups: dict[tuple[str, str], dict] = {}
    for t in theses:
        key = (t.author.strip().lower(), t.university)
        if key in seen:
            continue
        if key not in groups:
            groups[key] = {
                "author": t.author.strip(),
                "university": t.university,
                "thesis_count": 0,
                "years": set(),
                "thesis_types": set(),
                "tez_nos": [],
                "titles": [],
            }
        g = groups[key]
        g["thesis_count"] += 1
        g["years"].add(t.year)
        g["thesis_types"].add(t.thesis_type)
        g["tez_nos"].append(t.tez_no)
        g["titles"].append(t.title[:80])

    rows = sorted(groups.values(), key=lambda g: (g["university"], g["author"]))

    fns = ["author", "university", "thesis_count", "years", "thesis_types", "tez_nos", "titles"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fns)
        w.writeheader()
        for g in rows:
            w.writerow({
                "author": g["author"],
                "university": g["university"],
                "thesis_count": g["thesis_count"],
                "years": " | ".join(sorted(g["years"])),
                "thesis_types": " | ".join(sorted(g["thesis_types"])),
                "tez_nos": " | ".join(g["tez_nos"]),
                "titles": " || ".join(g["titles"]),
            })
    print(f"New authors (not in prior runs): {len(rows)} -> {path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(year_start: int, year_end: int, out_dir: str, enrich: bool,
        resume: bool, keywords: list[str], thesis_types: list[str]) -> None:
    theses_path = os.path.join(out_dir, f"theses_{today_str()}.csv")

    existing: list[Thesis] = []
    seen: set[str] = set()
    if resume:
        existing = load_theses(theses_path)
        seen = {t.tez_no for t in existing}
        if seen:
            print(f"Resume: {len(seen)} tez_nos already in {theses_path} will be skipped.")

    type_pairs: list[tuple[str, str]] = []
    for tt in thesis_types:
        code = THESIS_TYPE_CODES.get(tt.lower())
        if code is None:
            print(f"[WARN] unknown thesis type {tt!r}; skipping. Valid: {list(THESIS_TYPE_CODES)}")
            continue
        type_pairs.append((tt.lower(), code))

    if not type_pairs:
        raise SystemExit("No valid thesis types specified.")

    opener = _build_opener()
    print("Bootstrapping session ...")
    bootstrap_session(opener)

    slices = [
        (kw, str(year), tt_name, tt_code)
        for kw in keywords
        for year in range(year_start, year_end + 1)
        for tt_name, tt_code in type_pairs
    ]
    print(f"Planning {len(slices)} slices "
          f"({len(keywords)} keywords x "
          f"{year_end - year_start + 1} years x "
          f"{len(type_pairs)} types)\n")

    all_new: list[Thesis] = []
    for i, (kw, year, tt_name, tt_code) in enumerate(slices, 1):
        print(f"[{i}/{len(slices)}] Metin={kw!r} yil={year} type={tt_name}")
        try:
            html = search_slice(opener, metin=kw, yil1=year, yil2=year, tur=tt_code)
        except Exception as e:
            print(f"   [ERROR] search failed: {e}")
            time.sleep(POLITE_DELAY_SEC)
            continue

        total = extract_total(html)
        rows = parse_search_html(html)
        turkish = [t for t in rows if t.university]
        if total is not None and total > RESULT_CAP:
            print(f"   WARN: slice reports {total} rows but server cap is "
                  f"{RESULT_CAP} — {total - RESULT_CAP} rows lost. Narrow "
                  f"the slice further (smaller year range or keyword).")
        print(f"   -> total={total}  parsed={len(rows)}  turkish={len(turkish)}")

        if seen:
            turkish = [t for t in turkish if t.tez_no not in seen]
        all_new.extend(turkish)
        seen.update(t.tez_no for t in turkish)

        time.sleep(POLITE_DELAY_SEC)

    all_new = dedup_by_tez_no(all_new)
    print(f"\nAfter dedup: {len(all_new)} new Turkish-affiliated theses")

    if enrich and all_new:
        print(f"\nEnriching {len(all_new)} theses with detail pages (cache: {CACHE_DIR}/) ...")
        for i, t in enumerate(all_new, 1):
            detail_html = cached_detail_html(t.tez_no)
            if detail_html is None:
                try:
                    detail_html = get_detail(opener, t.thesis_key, t.encrypted_no)
                    write_cached_detail(t.tez_no, detail_html)
                    time.sleep(POLITE_DELAY_SEC)
                except Exception as e:
                    print(f"   [WARN] {t.tez_no}: detail fetch failed: {e}")
                    continue
            try:
                d = parse_detail_html(detail_html)
                t.advisor = d["advisor"]
                t.institute = d["institute"]
                t.department = d["department"]
                t.keywords = d["keywords"]
                t.abstract = d["abstract"]
                t.pdf_available = d["pdf_available"]
            except Exception as e:
                print(f"   [WARN] {t.tez_no}: detail parse failed: {e}")
            if i % 25 == 0:
                print(f"   [{i}/{len(all_new)}] enriched")

    combined = dedup_by_tez_no(existing + all_new)
    save_theses(combined, theses_path)

    prev_files = _prev_theses_files(out_dir)
    if prev_files:
        print(f"\nDiffing against {len(prev_files)} previous run(s): "
              f"{[os.path.basename(p) for p in sorted(prev_files)]}")
    else:
        print("\nNo previous runs found — new_authors CSV will contain all authors.")
    new_authors_path = os.path.join(out_dir, f"new_authors_{today_str()}.csv")
    save_new_authors(combined, prev_files, new_authors_path)

    print(f"\nResults:")
    print(f"   new theses : {len(all_new)}")
    print(f"   total      : {len(combined)}")


if __name__ == "__main__":
    _default_from = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()

    parser = argparse.ArgumentParser(description="YÖK Tez Merkezi incremental ML/DS thesis scraper (v2)")
    parser.add_argument(
        "--from_date", type=str, default=_default_from,
        help=f"Start date YYYY-MM-DD (year resolution). Default: 30 days ago ({_default_from}).",
    )
    parser.add_argument("--year_end", type=int, default=datetime.date.today().year)
    parser.add_argument("--enrich", action="store_true",
                        help="Fetch detail pages (advisor/abstract). Off by default — adds significant time.")
    parser.add_argument("--resume", action="store_true",
                        help="Skip tez_nos already written to today's output")
    parser.add_argument("--keywords", type=str, default="",
                        help="Comma-separated override of the default keyword list")
    parser.add_argument("--types", type=str, default="msc,phd",
                        help="Comma-separated thesis types: msc,phd")
    args = parser.parse_args()

    try:
        year_start = datetime.date.fromisoformat(args.from_date).year
    except ValueError:
        raise SystemExit(f"Invalid --from_date: {args.from_date!r}. Use YYYY-MM-DD.")
    print(f"from_date={args.from_date}  ->  year_start={year_start}")

    out_dir = data_dir(".")
    print(f"Output directory: {out_dir}")

    kws = [k.strip() for k in args.keywords.split(",") if k.strip()] or ML_KEYWORDS
    types = [t.strip() for t in args.types.split(",") if t.strip()]

    run(
        year_start=year_start,
        year_end=args.year_end,
        out_dir=out_dir,
        enrich=args.enrich,
        resume=args.resume,
        keywords=kws,
        thesis_types=types,
    )
