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


def today_dir(base: str = ".") -> str:
    """Return today's data_YYYYMMDD path (created if missing)."""
    name = f"data_{datetime.date.today():%Y%m%d}"
    path = os.path.join(base, name)
    os.makedirs(path, exist_ok=True)
    return path


def last_run_date(base: str = ".") -> Optional[datetime.date]:
    """Return the date of the most recent data_YYYYMMDD folder, or None."""
    pattern = re.compile(r"^data_(\d{4})(\d{2})(\d{2})$")
    dates: list[datetime.date] = []
    try:
        for entry in os.scandir(base):
            m = pattern.match(entry.name)
            if m and entry.is_dir():
                try:
                    dates.append(datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
                except ValueError:
                    pass
    except FileNotFoundError:
        pass
    return max(dates) if dates else None
