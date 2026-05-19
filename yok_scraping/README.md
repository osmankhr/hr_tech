# YÖK Tez Merkezi — ML/DS Thesis Scraper

Weekly scraper for [tez.yok.gov.tr](https://tez.yok.gov.tr) that tracks new ML, DL, and data science theses from top Turkish universities and emails a digest of new authors each Monday.

## What it does

- Searches YÖK's thesis database across 16 ML/DS/AI keywords in Turkish and English
- Filters to a curated set of target universities (Boğaziçi, İTÜ, ODTÜ, Bilkent, Sabancı, Koç, etc.)
- Diffs each weekly run against all prior runs to surface **new authors** only
- Sends an HTML email summary via Gmail SMTP

## Schedule

Runs every **Monday at 05:00 UTC** (08:00 Istanbul) via crontab on the server.

```
0 5 * * 1 cd /home/osman/projects/hr_tech/yok_scraping && ./run_and_notify.sh >> /tmp/yok_scraper.log 2>&1
```

Log: `/tmp/yok_scraper.log`

## Setup

```bash
cd yok_scraping
python -m venv .venv
.venv/bin/pip install beautifulsoup4 certifi python-dotenv
```

Create a `.env` file (not committed):

```
GMAIL_USER=you@gmail.com
GMAIL_APP_PASS=xxxx xxxx xxxx xxxx
NOTIFY_TO=recipient@email.com
```

## Running manually

```bash
cd yok_scraping
./run_and_notify.sh
# or just the scraper:
.venv/bin/python yok_scraper.py
# with detail enrichment (advisor, abstract — much slower):
.venv/bin/python yok_scraper.py --enrich
```

## Output

All output lands in `data/`:

| File | Description |
|------|-------------|
| `theses_YYYYMMDD.csv` | All theses found in that week's run |
| `new_authors_YYYYMMDD.csv` | Authors not seen in any prior run |

## Target universities

Boğaziçi · İTÜ · ODTÜ · Bilkent · Sabancı · Koç · Hacettepe · Yıldız Technical · Istanbul University · İzmir Institute of Technology

## Keywords searched

Turkish: makine öğrenmesi, derin öğrenme, yapay zeka, veri bilimi, yapay sinir ağı, doğal dil işleme, pekiştirmeli öğrenme, büyük veri

English: machine learning, deep learning, artificial intelligence, data science, neural network, natural language processing, reinforcement learning, big data
