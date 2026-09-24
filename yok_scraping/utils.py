"""Shared utilities for v2 hiring scrapers."""

import datetime
import os
import re
from typing import Optional

UNIVERSITIES: dict[str, list[str]] = {
    # --- Istanbul ---
    "Boğaziçi University": ["BOĞAZİÇİ", "BOGAZICI", "Boğaziçi", "Bogazici"],
    "Istanbul Technical University": ["İSTANBUL TEKNİK", "ISTANBUL TECHNICAL", "Istanbul Technical"],
    "Sabancı University": ["SABANCI", "Sabancı", "Sabanci"],
    "Koç University": ["KOÇ ÜNİVERSİTESİ", "KOC ÜNİVERSİTESİ", "KOÇ UNIVERSITY", "KOC UNIVERSITY", "Koç University", "Koc University"],
    "Yıldız Technical University": ["YILDIZ TEKNİK", "YILDIZ TECHNICAL", "Yıldız Technical", "Yildiz Technical"],
    "Istanbul University": ["İSTANBUL ÜNİVERSİTESİ", "ISTANBUL UNIVERSITY", "Istanbul University"],
    "Istanbul University-Cerrahpaşa": ["CERRAHPAŞA", "CERRAHPASA", "Cerrahpaşa"],
    "Marmara University": ["MARMARA ÜNİVERSİTESİ", "MARMARA UNIVERSITY", "Marmara University"],
    "Özyeğin University": ["ÖZYEĞİN", "OZYEGIN", "Özyeğin", "Ozyegin"],
    "Istanbul Bilgi University": ["İSTANBUL BİLGİ", "ISTANBUL BILGI", "Bilgi University"],
    "Işık University": ["IŞIK ÜNİVERSİTESİ", "ISIK UNIVERSITY", "Işık University", "Isik University"],
    "MEF University": ["MEF ÜNİVERSİTESİ", "MEF UNIVERSITY"],
    "Kadir Has University": ["KADİR HAS", "KADIR HAS"],
    "Bahçeşehir University": ["BAHÇEŞEHİR", "BAHCESEHIR"],
    "Yeditepe University": ["YEDİTEPE", "YEDITEPE"],
    "Galatasaray University": ["GALATASARAY ÜNİVERSİTESİ", "GALATASARAY UNIVERSITY"],
    "Fatih Sultan Mehmet Vakıf University": ["FATİH SULTAN MEHMET", "FATIH SULTAN MEHMET"],
    # --- Ankara ---
    "Middle East Technical University": [
        "ORTA DOĞU TEKNİK", "MIDDLE EAST TECHNICAL", "METU", "ODTÜ",
        "Middle East Technical", "Orta Doğu Teknik",
    ],
    "Bilkent University": ["BİLKENT", "BILKENT", "Bilkent"],
    "Hacettepe University": ["HACETTEPE", "Hacettepe"],
    "Ankara University": ["ANKARA ÜNİVERSİTESİ", "ANKARA UNIVERSITY", "Ankara University"],
    "Gazi University": ["GAZİ ÜNİVERSİTESİ", "GAZI UNIVERSITY", "Gazi University"],
    "TOBB University of Economics and Technology": ["TOBB", "TOBB ETÜ", "TOBB ETU"],
    "Ankara Yıldırım Beyazıt University": ["YILDIRIM BEYAZIT"],
    "Çankaya University": ["ÇANKAYA ÜNİVERSİTESİ", "CANKAYA UNIVERSITY"],
    "Atılım University": ["ATILIM ÜNİVERSİTESİ", "ATILIM UNIVERSITY", "Atilim University"],
    # --- Izmir ---
    "Ege University": ["EGE ÜNİVERSİTESİ", "EGE UNIVERSITY", "Ege University"],
    "Dokuz Eylül University": ["DOKUZ EYLÜL", "DOKUZ EYLUL"],
    "Izmir Institute of Technology": ["İZMİR YÜKSEK TEKNOLOJİ", "IZMIR INSTITUTE", "Izmir Institute"],
    "Izmir Katip Çelebi University": ["İZMİR KATİP ÇELEBİ", "IZMIR KATIP CELEBI"],
    "Yaşar University": ["YAŞAR ÜNİVERSİTESİ", "YASAR UNIVERSITY", "Yaşar University"],
    "Izmir University of Economics": ["İZMİR EKONOMİ", "IZMIR EKONOMI", "IZMIR UNIVERSITY OF ECONOMICS"],
    "Izmir Democracy University": ["İZMİR DEMOKRASİ", "IZMIR DEMOKRASI"],
}

# City each university above is headquartered in, for talent-pool comparisons.
UNIVERSITY_CITY: dict[str, str] = {
    "Boğaziçi University": "Istanbul",
    "Istanbul Technical University": "Istanbul",
    "Sabancı University": "Istanbul",
    "Koç University": "Istanbul",
    "Yıldız Technical University": "Istanbul",
    "Istanbul University": "Istanbul",
    "Istanbul University-Cerrahpaşa": "Istanbul",
    "Marmara University": "Istanbul",
    "Özyeğin University": "Istanbul",
    "Istanbul Bilgi University": "Istanbul",
    "Işık University": "Istanbul",
    "MEF University": "Istanbul",
    "Kadir Has University": "Istanbul",
    "Bahçeşehir University": "Istanbul",
    "Yeditepe University": "Istanbul",
    "Galatasaray University": "Istanbul",
    "Fatih Sultan Mehmet Vakıf University": "Istanbul",
    "Middle East Technical University": "Ankara",
    "Bilkent University": "Ankara",
    "Hacettepe University": "Ankara",
    "Ankara University": "Ankara",
    "Gazi University": "Ankara",
    "TOBB University of Economics and Technology": "Ankara",
    "Ankara Yıldırım Beyazıt University": "Ankara",
    "Çankaya University": "Ankara",
    "Atılım University": "Ankara",
    "Ege University": "Izmir",
    "Dokuz Eylül University": "Izmir",
    "Izmir Institute of Technology": "Izmir",
    "Izmir Katip Çelebi University": "Izmir",
    "Yaşar University": "Izmir",
    "Izmir University of Economics": "Izmir",
    "Izmir Democracy University": "Izmir",
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


def university_city(university: str) -> Optional[str]:
    """Return Istanbul/Ankara/Izmir for a canonical university name, or None."""
    return UNIVERSITY_CITY.get(university)


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
