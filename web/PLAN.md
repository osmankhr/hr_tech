# Sourcing Copilot — Web UI Implementation Plan

Wraps `candidate_pool/` in a multi-user web application served at `stagetwoforge.com/hr`.

---

## Goals

- Recruiters log in, create campaigns, run the pipeline, and review/store results — all in-browser
- Campaigns and results are persisted per user for future reference
- No self-registration: admin creates accounts manually
- No job queue: pipeline runs in a background thread, frontend polls for status

---

## Directory Layout

```
hr_tech/web/
├── server.py          # FastAPI app — all routes
├── db.py              # SQLite schema + helpers (users, campaigns, results)
├── auth.py            # Password hashing, session cookie signing, auth dependency
├── pipeline.py        # Thin wrapper: runs candidate_pool pipeline in a thread
├── static/
│   ├── login.html     # Login page (standalone, no auth required)
│   └── app.html       # Main SPA (auth-gated, single file with inline JS)
├── web.db             # SQLite database (gitignored)
└── PLAN.md            # This file
```

`web.db` and any campaign temp files are gitignored. The pipeline writes to a temp dir per run; results are read back into the DB on completion.

---

## Data Model (`db.py`)

```sql
CREATE TABLE users (
    id          INTEGER PRIMARY KEY,
    email       TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE campaigns (
    id              INTEGER PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    name            TEXT NOT NULL,
    job_description TEXT NOT NULL,
    filter_criteria TEXT NOT NULL,
    locations       TEXT NOT NULL,   -- JSON: [{"name": "turkey", "hint": "..."}]
    model           TEXT NOT NULL DEFAULT 'claude-sonnet-4-5',
    num_queries     INTEGER DEFAULT 6,
    num_results     INTEGER DEFAULT 30,
    max_candidates  INTEGER DEFAULT 100,
    status          TEXT DEFAULT 'pending',  -- pending | running | done | failed
    error_message   TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    finished_at     TEXT
);

CREATE TABLE results (
    id              INTEGER PRIMARY KEY,
    campaign_id     INTEGER NOT NULL REFERENCES campaigns(id),
    url             TEXT,
    title           TEXT,
    location        TEXT,
    highlights      TEXT,   -- JSON array
    exa_score       REAL,
    recommendation  TEXT,   -- ACCEPT | REJECT | PENDING
    confidence      TEXT,   -- HIGH | MEDIUM | LOW
    key_strength    TEXT,
    main_concern    TEXT,
    reasoning       TEXT,
    raw_json        TEXT    -- full Exa + filter output preserved
);
```

---

## Auth (`auth.py`)

- **Password hashing:** `bcrypt` via `passlib`
- **Sessions:** signed cookie using `itsdangerous.URLSafeTimedSerializer` — stores `{"user_id": <id>}`, 7-day expiry
- **FastAPI dependency:** `get_current_user(request)` — reads cookie, verifies signature, returns user row or raises 401
- **Admin account creation:** CLI command `python -m web.auth create-user <email> <password>` — hashes password, inserts into DB

No password reset flow for now — admin resets manually via the same CLI.

---

## Pipeline Integration (`pipeline.py`)

The existing `candidate_pool/scripts/` classes (`QueryGenerator`, `ExaSearcher`, `CandidateFilter`, `ReportGenerator`) are imported directly — no subprocess. The `run_campaign()` function:

1. Creates a temp campaign dir with `campaign.yaml`, `job_description.md`, `filter_criteria.md`
2. Instantiates and runs each pipeline class in sequence, updating `campaigns.status` at each phase:
   - `running:queries` → `running:search` → `running:filter` → `running:saving`
3. Reads `filtered_results.json` from the temp dir, inserts each candidate into `results`
4. Sets `status = 'done'` and `finished_at`
5. Cleans up temp dir

On exception: sets `status = 'failed'` and writes `error_message`.

Called from the API as: `threading.Thread(target=run_campaign, args=(campaign_id,), daemon=True).start()`

---

## API Routes (`server.py`)

All `/hr/api/*` routes require auth (cookie). All return JSON.

### Auth
| Method | Path | Description |
|--------|------|-------------|
| GET | `/hr/login` | Serve `login.html` |
| POST | `/hr/api/login` | Verify credentials, set session cookie, return `{"ok": true}` |
| POST | `/hr/api/logout` | Clear cookie |

### App shell
| Method | Path | Description |
|--------|------|-------------|
| GET | `/hr` | Redirect to `/hr/app` if logged in, else `/hr/login` |
| GET | `/hr/app` | Serve `app.html` (auth-gated) |

### Campaigns
| Method | Path | Description |
|--------|------|-------------|
| GET | `/hr/api/campaigns` | List user's campaigns (id, name, status, created_at, result_count) |
| POST | `/hr/api/campaigns` | Create campaign, start pipeline in background, return campaign id |
| GET | `/hr/api/campaigns/{id}` | Campaign detail + status |
| DELETE | `/hr/api/campaigns/{id}` | Delete campaign + its results (user must own it) |

### Pipeline status
| Method | Path | Description |
|--------|------|-------------|
| GET | `/hr/api/campaigns/{id}/status` | Returns `{"status": "running:filter", "result_count": 0}` — frontend polls this |

### Results
| Method | Path | Description |
|--------|------|-------------|
| GET | `/hr/api/campaigns/{id}/results` | Paginated results; supports `?recommendation=ACCEPT` filter |
| GET | `/hr/api/campaigns/{id}/export` | Stream CSV download |

---

## Frontend (`static/app.html`)

Single HTML file with inline JS (vanilla, no framework). Three views rendered client-side:

**View 1: Campaign list**
- Table of user's campaigns: name, status, result count, date, actions (view / delete)
- "New campaign" button → View 2
- Auto-refreshes status column every 5s if any campaign is `running:*`

**View 2: New campaign form**
- Fields: Campaign name, Job description (textarea), Filter criteria (textarea), Locations (repeatable: name + optional hint)
- Advanced (collapsed): model selector, num_queries, num_results, max_candidates
- Submit → POST `/hr/api/campaigns` → switches to View 3 with polling

**View 3: Campaign results**
- Header: campaign name, status badge, created_at
- If running: progress indicator (phase label + spinner), polls `/status` every 3s
- If done: candidate cards — each shows name/URL, location, Exa score, recommendation badge (ACCEPT/REJECT/PENDING), key_strength, main_concern, reasoning (expandable)
- Filter bar: filter by recommendation
- Export button → `/export` download

`login.html` is a minimal standalone form — submits to `/hr/api/login`, redirects to `/hr/app` on success.

---

## Deployment

The web app runs as a **separate systemd service** (`sourcing-copilot.service`), not inside `momentum-signals.service`. This keeps the two apps isolated — crashes in one don't affect the other.

`momentum-signals/server.py` route for `/hr` changes from the "under construction" stub to a **reverse proxy pass** to the new service (or a redirect). The cleanest approach: run the new FastAPI app on port 8766, and have nginx (if present) or the existing server proxy `/hr/*` to it. If there's no nginx, just bind it directly and update the systemd config.

### Env vars needed
```
SECRET_KEY=<random 32-byte hex>   # for cookie signing
EXA_API_KEY=<key>                 # passed through to pipeline
```

---

## Dependencies to add (`pyproject.toml` or `requirements.txt`)

```
fastapi
uvicorn
passlib[bcrypt]
itsdangerous
python-multipart   # for form parsing
openpyxl           # already in candidate_pool, verify
```

---

## Implementation order

1. `db.py` — schema + helpers
2. `auth.py` — hashing, cookie, `create-user` CLI
3. `pipeline.py` — wrapper around existing classes, status updates
4. `server.py` — routes (start with login + campaign CRUD, add results/export after)
5. `static/login.html` — minimal form
6. `static/app.html` — campaign list → new form → results view
7. Systemd service file
8. Update `momentum-signals/server.py` `/hr` route to proxy/redirect

---

## What's explicitly out of scope (for now)

- Password reset
- Email notifications when a run completes
- Sharing campaigns across users
- Admin UI (use CLI for account management)
- Rate limiting / concurrent run caps
