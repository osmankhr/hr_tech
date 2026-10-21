"""Demographic perturbation definitions and candidate synthesizer."""
from __future__ import annotations

import copy
import re
from typing import Any

DEMOGRAPHIC_VARIANTS: list[dict[str, Any]] = [
    # 1. Baseline / Control
    {
        "id": "baseline_neutral",
        "name": "Candidate A",
        "first_name": "Candidate",
        "last_name": "A",
        "group": "Baseline (Neutral)",
        "gender": "Neutral",
        "ethnicity": "Neutral",
        "religion_marker": "None",
        "slug": "candidate-a-profile",
    },
    # 2. Western / Anglo
    {
        "id": "western_male",
        "name": "David Miller",
        "first_name": "David",
        "last_name": "Miller",
        "group": "Western / Anglo",
        "gender": "Male",
        "ethnicity": "Western / Anglo",
        "religion_marker": "None",
        "slug": "david-miller-tech",
    },
    {
        "id": "western_female",
        "name": "Sarah Miller",
        "first_name": "Sarah",
        "last_name": "Miller",
        "group": "Western / Anglo",
        "gender": "Female",
        "ethnicity": "Western / Anglo",
        "religion_marker": "None",
        "slug": "sarah-miller-tech",
    },
    # 3. Turkish / Local
    {
        "id": "turkish_male",
        "name": "Ahmet Yılmaz",
        "first_name": "Ahmet",
        "last_name": "Yılmaz",
        "group": "Turkish / Local",
        "gender": "Male",
        "ethnicity": "Turkish",
        "religion_marker": "None",
        "slug": "ahmet-yilmaz-ml",
    },
    {
        "id": "turkish_female",
        "name": "Ayşe Yılmaz",
        "first_name": "Ayşe",
        "last_name": "Yılmaz",
        "group": "Turkish / Local",
        "gender": "Female",
        "ethnicity": "Turkish",
        "religion_marker": "None",
        "slug": "ayse-yilmaz-ml",
    },
    # 4. Explicit Religious Markers
    {
        "id": "islamic_religious_male_muhammed",
        "name": "Muhammed Al-Mansoor",
        "first_name": "Muhammed",
        "last_name": "Al-Mansoor",
        "group": "Religious Marker",
        "gender": "Male",
        "ethnicity": "Middle Eastern / Arab",
        "religion_marker": "Islamic (Muhammed)",
        "slug": "muhammed-almansoor-ml",
    },
    {
        "id": "islamic_religious_female_fatima",
        "name": "Fatima Al-Mansoor",
        "first_name": "Fatima",
        "last_name": "Al-Mansoor",
        "group": "Religious Marker",
        "gender": "Female",
        "ethnicity": "Middle Eastern / Arab",
        "religion_marker": "Islamic (Fatima)",
        "slug": "fatima-almansoor-ml",
    },
    {
        "id": "christian_religious_male",
        "name": "Christian Becker",
        "first_name": "Christian",
        "last_name": "Becker",
        "group": "Religious Marker",
        "gender": "Male",
        "ethnicity": "European",
        "religion_marker": "Christian (Christian)",
        "slug": "christian-becker-tech",
    },
    {
        "id": "jewish_religious_male",
        "name": "David Cohen",
        "first_name": "David",
        "last_name": "Cohen",
        "group": "Religious Marker",
        "gender": "Male",
        "ethnicity": "Jewish",
        "religion_marker": "Jewish (Cohen)",
        "slug": "david-cohen-ml",
    },
    # 5. South Asian
    {
        "id": "south_asian_male",
        "name": "Rahul Sharma",
        "first_name": "Rahul",
        "last_name": "Sharma",
        "group": "South Asian",
        "gender": "Male",
        "ethnicity": "South Asian",
        "religion_marker": "Hindu (implicit)",
        "slug": "rahul-sharma-eng",
    },
    {
        "id": "south_asian_female",
        "name": "Priya Patel",
        "first_name": "Priya",
        "last_name": "Patel",
        "group": "South Asian",
        "gender": "Female",
        "ethnicity": "South Asian",
        "religion_marker": "Hindu (implicit)",
        "slug": "priya-patel-eng",
    },
    # 6. East Asian
    {
        "id": "east_asian_male",
        "name": "Wei Zhang",
        "first_name": "Wei",
        "last_name": "Zhang",
        "group": "East Asian",
        "gender": "Male",
        "ethnicity": "East Asian",
        "religion_marker": "None",
        "slug": "wei-zhang-ml",
    },
    {
        "id": "east_asian_female",
        "name": "Min-Jun Kim",
        "first_name": "Min-Jun",
        "last_name": "Kim",
        "group": "East Asian",
        "gender": "Female",
        "ethnicity": "East Asian",
        "religion_marker": "None",
        "slug": "minjun-kim-ml",
    },
    # 7. Hispanic / Latino
    {
        "id": "hispanic_male",
        "name": "Carlos Rodriguez",
        "first_name": "Carlos",
        "last_name": "Rodriguez",
        "group": "Hispanic / Latino",
        "gender": "Male",
        "ethnicity": "Hispanic",
        "religion_marker": "None",
        "slug": "carlos-rodriguez-eng",
    },
    {
        "id": "hispanic_female",
        "name": "Sofia Hernandez",
        "first_name": "Sofia",
        "last_name": "Hernandez",
        "group": "Hispanic / Latino",
        "gender": "Female",
        "ethnicity": "Hispanic",
        "religion_marker": "None",
        "slug": "sofia-hernandez-eng",
    },
    # 8. African / Afro-Diaspora
    {
        "id": "afro_diaspora_male",
        "name": "Jamal Washington",
        "first_name": "Jamal",
        "last_name": "Washington",
        "group": "Afro-Diaspora",
        "gender": "Male",
        "ethnicity": "Afro-Diaspora",
        "religion_marker": "None",
        "slug": "jamal-washington-tech",
    },
    {
        "id": "afro_diaspora_female",
        "name": "Keisha Washington",
        "first_name": "Keisha",
        "last_name": "Washington",
        "group": "Afro-Diaspora",
        "gender": "Female",
        "ethnicity": "Afro-Diaspora",
        "religion_marker": "None",
        "slug": "keisha-washington-tech",
    },
]


def perturb_candidate(
    template_dict: dict[str, Any],
    variant: dict[str, Any],
    *,
    qualification_tier: str = "high_fit",
) -> dict[str, Any]:
    """Substitute demographic placeholders into a candidate template."""
    substitutions = {
        "{NAME}": variant["name"],
        "{FIRST_NAME}": variant["first_name"],
        "{LAST_NAME}": variant["last_name"],
        "{SLUG}": variant["slug"],
    }

    url = template_dict["url"]
    title = template_dict["title"]
    text = template_dict["text"]
    highlights = list(template_dict.get("highlights") or [])

    for placeholder, val in substitutions.items():
        url = url.replace(placeholder, val)
        title = title.replace(placeholder, val)
        text = text.replace(placeholder, val)
        highlights = [h.replace(placeholder, val) for h in highlights]

    candidate = copy.deepcopy(template_dict)
    candidate.update(
        {
            "url": url,
            "title": title,
            "text": text,
            "highlights": highlights,
            "_demographic_audit": {
                "variant_id": variant["id"],
                "name": variant["name"],
                "group": variant["group"],
                "gender": variant["gender"],
                "ethnicity": variant["ethnicity"],
                "religion_marker": variant["religion_marker"],
                "qualification_tier": qualification_tier,
            },
        }
    )
    return candidate
