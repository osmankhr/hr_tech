"""
Email notification helper for the YÖK scraper.

Reads yok_new_authors.csv from the latest data_YYYYMMDD/ folder and sends
a summary email via Gmail SMTP.

Required env vars:
    GMAIL_USER      your Gmail address          e.g. you@gmail.com
    GMAIL_APP_PASS  Gmail App Password          (16-char, no spaces)
    NOTIFY_TO       recipient address(es)       comma-separated

Usage (called automatically by run_and_notify.sh, or standalone):
    python notify.py
"""

import csv
import datetime
import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv


# ---------------------------------------------------------------------------
# Config from environment
# ---------------------------------------------------------------------------
load_dotenv()


GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASS = os.environ.get("GMAIL_APP_PASS", "")
NOTIFY_TO = [a.strip() for a in os.environ.get("NOTIFY_TO", "").split(",") if a.strip()]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _latest_data_dir(base: str = ".") -> str | None:
    pat = re.compile(r"^data_(\d{8})$")
    candidates = []
    for entry in os.scandir(base):
        m = pat.match(entry.name)
        if m and entry.is_dir():
            candidates.append((m.group(1), entry.path))
    return max(candidates, key=lambda x: x[0])[1] if candidates else None


def _load_new_authors(data_dir: str) -> list[dict]:
    path = os.path.join(data_dir, "yok_new_authors.csv")
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _build_email(rows: list[dict], data_dir: str) -> tuple[str, str]:
    """Return (subject, html_body)."""
    run_date = os.path.basename(data_dir).replace("data_", "")
    n = len(rows)

    if n == 0:
        subject = f"YÖK Scraper {run_date} — no new authors"
        body = "<p>No new authors found in this run.</p>"
        return subject, body

    subject = f"YÖK Scraper {run_date} — {n} new author{'s' if n != 1 else ''}"

    # Group by university for the email body
    by_uni: dict[str, list[dict]] = {}
    for r in rows:
        by_uni.setdefault(r.get("university", "Unknown"), []).append(r)

    sections = []
    for uni in sorted(by_uni):
        authors = sorted(by_uni[uni], key=lambda r: r.get("author", ""))
        rows_html = "".join(
            f"<tr>"
            f"<td style='padding:4px 8px'>{r.get('author','')}</td>"
            f"<td style='padding:4px 8px;color:#555'>{r.get('thesis_types','')}</td>"
            f"<td style='padding:4px 8px;color:#555'>{r.get('years','')}</td>"
            f"<td style='padding:4px 8px;font-size:12px;color:#777'>{r.get('titles','')[:120]}</td>"
            f"</tr>"
            for r in authors
        )
        sections.append(
            f"<h3 style='margin:16px 0 4px;color:#333'>{uni} ({len(authors)})</h3>"
            f"<table style='border-collapse:collapse;font-size:14px;width:100%'>"
            f"<tr style='background:#f0f0f0'>"
            f"<th style='padding:4px 8px;text-align:left'>Author</th>"
            f"<th style='padding:4px 8px;text-align:left'>Type</th>"
            f"<th style='padding:4px 8px;text-align:left'>Year(s)</th>"
            f"<th style='padding:4px 8px;text-align:left'>Title</th>"
            f"</tr>"
            f"{rows_html}"
            f"</table>"
        )

    body = (
        f"<div style='font-family:sans-serif;max-width:900px'>"
        f"<h2>YÖK Scraper — {n} new author{'s' if n != 1 else ''}</h2>"
        f"<p style='color:#555'>Run date: {run_date} &nbsp;|&nbsp; "
        f"Source: {data_dir}/yok_new_authors.csv</p>"
        + "".join(sections) +
        f"</div>"
    )
    return subject, body


def send(rows: list[dict], data_dir: str) -> None:
    if not GMAIL_USER or not GMAIL_APP_PASS or not NOTIFY_TO:
        missing = [v for v, k in [
            ("GMAIL_USER", GMAIL_USER), ("GMAIL_APP_PASS", GMAIL_APP_PASS), ("NOTIFY_TO", NOTIFY_TO)
        ] if not k]
        raise SystemExit(f"Missing env vars: {missing}")

    subject, html_body = _build_email(rows, data_dir)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_USER
    msg["To"] = ", ".join(NOTIFY_TO)
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.login(GMAIL_USER, GMAIL_APP_PASS)
        smtp.sendmail(GMAIL_USER, NOTIFY_TO, msg.as_string())

    print(f"Email sent to {NOTIFY_TO}: {subject}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    data_dir = _latest_data_dir(".")
    if not data_dir:
        raise SystemExit("No data_YYYYMMDD/ folder found.")
    rows = _load_new_authors(data_dir)
    print(f"Loaded {len(rows)} new authors from {data_dir}")
    send(rows, data_dir)
