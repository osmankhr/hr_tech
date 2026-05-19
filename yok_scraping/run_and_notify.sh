#!/usr/bin/env bash
# Runs the YÖK scraper then sends an email with new authors.
# Schedule with cron: 0 8 * * 1 /path/to/run_and_notify.sh >> /tmp/yok_scraper.log 2>&1

set -euo pipefail

PYTHON=/Users/osmankahraman/Documents/packages/miniforge3/envs/python3.14/bin/python
DIR="$(cd "$(dirname "$0")" && pwd)"

# Required env vars (set these on the remote instance, e.g. in ~/.bashrc or via cron env)
# export GMAIL_USER="you@gmail.com"
# export GMAIL_APP_PASS="xxxx xxxx xxxx xxxx"
# export NOTIFY_TO="you@gmail.com,colleague@company.com"

echo "=== $(date) ==="
cd "$DIR"

#$PYTHON -u yok_scraper.py
#$PYTHON -u notify.py

.venv/bin/python -u yok_scraper.py
.venv/bin/python -u notify.py
