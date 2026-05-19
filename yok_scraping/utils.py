"""Shared utilities for v2 hiring scrapers."""

import datetime
import os
import re
from typing import Optional

UNIVERSITIES: dict[str, list[str]] = {
    "Boğaziçi University": ["BOĞAZİÇİ", "BOGAZICI", "Boğaziçi", "Bogazici"],
    "Istanbul Technical University": ["İSTANBUL TEKNİK", "ISTANBUL TECHNICAL", "Istanbul Technical"],
    "Middle East Technical University": [
        "ORTA DOĞU TEKNİK", "MIDDLE EAST TECHNICAL", "METU", "ODTÜ",
        "Middle East Technical", "Orta Doğu Teknik",
    ],
    "Bilkent University": ["BİLKENT", "BILKENT", "Bilkent"],
    "Sabancı University": ["SABANCI", "Sabancı", "Sabanci"],
    "Koç University": ["KOÇ ÜNİVERSİTESİ", "KOC ÜNİVERSİTESİ", "KOÇ UNIVERSITY", "KOC UNIVERSITY", "Koç University", "Koc University"],
    "Hacettepe University": ["HACETTEPE", "Hacettepe"],
    # "Ankara University": ["ANKARA ÜNİVERSİTESİ", "ANKARA UNIVERSITY", "Ankara University"],
    "Yıldız Technical University": ["YILDIZ TEKNİK", "YILDIZ TECHNICAL", "Yıldız Technical", "Yildiz Technical"],
    "Istanbul University": ["İSTANBUL ÜNİVERSİTESİ", "ISTANBUL UNIVERSITY", "Istanbul University"],
    # "Ege University": ["EGE ÜNİVERSİTESİ", "EGE UNIVERSITY", "Ege University"],
    "Izmir Institute of Technology": ["İZMİR YÜKSEK TEKNOLOJİ", "IZMIR INSTITUTE", "Izmir Institute"],
}

_ALIAS_TO_CANONICAL: dict[str, str] = {
    alias.lower(): canonical
    for canonical, aliases in UNIVERSITIES.items()
    for alias in aliases
}


def match_university(text: str) -> Optional[str]:
    if not text:
        return None
    t = text.lower()
    for alias, canonical in _ALIAS_TO_CANONICAL.items():
        if alias in t:
            return canonical
    return None


def today_str() -> str:
    """Return today's date as YYYYMMDD string."""
    return datetime.date.today().strftime("%Y%m%d")


def data_dir(base: str = ".") -> str:
    """Return the flat data/ path (created if missing)."""
    path = os.path.join(base, "data")
    os.makedirs(path, exist_ok=True)
    return path


def last_run_date(base: str = ".") -> Optional[datetime.date]:
    """Return the date of the most recent data/theses_YYYYMMDD.csv file, or None."""
    pattern = re.compile(r"^theses_(\d{4})(\d{2})(\d{2})\.csv$")
    data_path = os.path.join(base, "data")
    dates: list[datetime.date] = []
    try:
        for entry in os.scandir(data_path):
            m = pattern.match(entry.name)
            if m and entry.is_file():
                try:
                    dates.append(datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
                except ValueError:
                    pass
    except FileNotFoundError:
        pass
    return max(dates) if dates else None
