# Sourcing Copilot — Web UI Migration Plan (v2)

Supersedes the original from-scratch plan below. A colleague (Mustafa Can Nacak) independently
built a working full-stack app around the same `candidate_pool/` pipeline
(`~/misc/hr_agent_ui` — FastAPI + React/Vite/Tailwind, richer schema, token auth). Rather than
build the vanilla-JS version originally planned, we're adopting their app as the base, fixing
the gaps it has relative to our requirements, and deploying it at `stagetwoforge.com/hr`.

Comparison against the original plan is preserved at the bottom of this file for reference.

---

## Why we're doing this in phases

Each phase is meant to be a self-contained unit of work completable in one session. Check off
a phase's exit criteria before starting the next one. Status as of 2026-07-03: **Phase 0 through
Phase 3 done.**

---

## Phase 0 — Audit (done, 2026-07-03)

- [x] Compared colleague's `hr_agent_ui` against our plan and `candidate_pool/` fork
- [x] Found: `/api/auth/signup` in their backend is public — anyone can create an account
      (defaults to `role='hr'`, which has real read access to campaigns/candidates). A
      `require_admin` dependency already exists in their code but isn't used to gate account
      creation.
- [x] Found: their `candidate_pool/scripts/search.py` adds multi-provider search
      (Exa / PeopleDataLabs / Apollo) — backward-compatible, worth adopting as-is.
- [x] Found: their `generate_queries.py` / `filter.py` swapped our Claude CLI subprocess calls
      for a Copilot CLI subprocess (`llm_client.CopilotClient`) — **not** adopting this swap,
      keep Claude subprocess per existing convention.
- [x] Found: their new `ranking/` module (`rank.py` + `feature_designer_agent` +
      `scoring_designer_agent` + `candidate_scorer_agent` + `manual_grader.py`, ~684 lines) adds
      a post-filter agentic ranking phase. Also built on Copilot CLI — needs porting to Claude
      subprocess before it can be adopted.
- [x] Confirmed deployment target: `momentum-signals.service` (port 8765) is the only thing
      nginx (`/etc/nginx/sites-enabled/stagetwoforge`) proxies for `stagetwoforge.com` today —
      no path-based routing yet. `momentum-signals/server.py:111` has the `/hr` "under
      construction" stub to replace.
- [x] Decisions made: port the ranking module (rewritten onto Claude subprocess); go all the
      way to a live deployment, but phased across sessions.

---

## Phase 1 — Backend port + auth hardening (done, 2026-07-03)

- [x] Copied `hr_agent_ui/backend/main.py`, `auth_utils.py`, `migrate_auth_audit.py`,
      `create_sample_hr_db.py` into `hr_tech/web/backend/`
- [x] Removed the public `POST /api/auth/signup` route; replaced with
      `POST /api/users` gated behind `require_admin` (accepts `role` param, defaults to `hr`).
      No self-registration — matches the original requirement.
- [x] Fixed the hardcoded default admin password in `migrate_auth_audit.py`
      (`Admin123!ChangeMe`, committed in colleague's repo) — now reads
      `HR_ADMIN_EMAIL` / `HR_ADMIN_PASSWORD` from env, generates a random password and prints it
      once if unset. Never a known fixed password in source.
- [x] Verified bootstrap flow: `create_sample_hr_db.py` (schema) →
      `migrate_auth_audit.py` (seeds admin) works standalone.
- [x] `CANDIDATE_POOL_ROOT` now resolves to `hr_tech/candidate_pool` (was a sibling-of-backend
      path in the original code; adjusted for our one-level-deeper `web/backend/` layout).
- [x] `DB_PATH` / `UPLOAD_DIR` made absolute (anchored to the script's own directory) instead of
      CWD-relative, so behavior doesn't depend on where the process is launched from (matters
      once this runs under systemd).
- [x] CORS origins now read from `HR_CORS_ORIGINS` env var (comma-separated), defaults to
      `http://localhost:5173` for local dev; prod origin to be set when the systemd unit is
      written in Phase 6.
- [x] Added `web/backend/requirements.txt` (fastapi, uvicorn[standard], python-multipart)
- [x] Added `.gitignore` entries for `web/backend/*.db`, `web/backend/uploaded_cvs/`,
      `web/frontend/node_modules/`, `web/frontend/dist/`
- [x] Smoke tested locally end-to-end (uvicorn on a scratch port): confirmed
      `/api/auth/signup` is gone (404), admin sign-in works, admin can create a new `hr` user via
      `POST /api/users`, that user can sign in, and both an unauthenticated request and a
      non-admin token get rejected (401/403) when hitting `POST /api/users`.

**Exit criteria met:** backend runs locally, only admin-created accounts can log in, no path
touched production infra.

**Follow-up noted, not blocking:** `migrate_auth_audit.py` uses `datetime.utcnow()`, which is
deprecated in newer Python — harmless today, worth a quick swap to `datetime.now(UTC)` whenever
this file is touched again.

---

## Phase 2 — candidate_pool merge (search.py) (done, 2026-07-03)

- [x] Merged multi-provider `search.py` (Exa / PeopleDataLabs / Apollo) from `hr_agent_ui` into
      `hr_tech/candidate_pool/scripts/search.py` — verified it's a clean, purely additive diff
      over our copy (same base, no divergent unrelated changes), and confirmed `run()`'s return
      type (`dict[str, list[dict]]`) is unchanged so `run_campaign.py` needs no changes
- [x] Left `filter.py` / `generate_queries.py` untouched (still Claude subprocess)
- [x] Documented `search.provider: exa | peopledatalabs | apollo` in `candidate_pool/README.md`
      (defaults to `exa` if omitted) and added `DATALABS_API_KEY` / `APOLLO_API_KEY` as commented
      optional entries in `.env.example` — only required if that provider is selected
- [x] Regression-checked the default path in a throwaway venv against the existing example
      campaign (no `search.provider` set): confirms provider resolves to `exa`, the `Exa` client
      is still constructed the same way, and query dispatch still falls through to
      `location.queries or generated_queries.yaml` unchanged (hit the same pre-existing
      "no generated queries yet" error the file always raised in that state — not a regression)

**Exit criteria met:** `search.py` supports 3 providers, default behavior unchanged, no
CopilotClient dependency introduced.

**Exit criteria:** `search.py` supports 3 providers, default behavior unchanged, no CopilotClient
dependency introduced.

---

## Phase 3 — Ranking module port (Claude subprocess) (done, 2026-07-03)

- [x] Ported `ranking/` (`pipeline.py`, `agents/agent_base.py`,
      `agents/feature_designer_agent.py`, `agents/scoring_designer_agent.py`,
      `agents/candidate_scorer_agent.py`, `utils/json_utils.py`) and `rank.py` +
      `manual_grader.py` into `hr_tech/candidate_pool/scripts/`
- [x] Rewrote `agents/agent_base.py` to replace every `CopilotClient` call with our Claude
      subprocess helper (`claude --print --model <model>`) — the only file in the ranking module
      that calls an LLM; all other files were copied as-is (no Copilot dependency)
- [x] Fixed default fallback model in `pipeline.py` and `RANKING.md` from the placeholder
      `openai/gpt-5.3-codex` to `claude-sonnet-4-5`
- [x] Wired `--rank-only` / `--force-ranking-redesign` flags into `run_campaign.py`; ranking
      block runs after filter phase, respects `ranking.enabled` in campaign config
- [x] Smoke-tested: `scripts/rank.py` ran against a 2-candidate synthetic campaign end-to-end
      — produced `ranked_results.json` and `ranking_summary.json` in ~42 s; ranking structure
      verified correct. Previous exit-137 was a 240 s `timeout` wrapper being too tight on first
      run (3 sequential LLM design calls); no OOM or code issue.

**Exit criteria met:** ranking phase runs on Claude subprocess, produces scored/ranked
candidates with deterministic `manual_score`, `category`, and `rank` fields.

---

## Phase 4 — Frontend port

- [ ] Copy `hr_agent_ui/frontend/` into `hr_tech/web/frontend/`
- [ ] Set `vite.config.js` → `base: '/hr/'`
- [ ] Replace hardcoded `API_BASE_URL = "http://localhost:8000/api"` in `src/config/api.js`
      with an env-driven value (`import.meta.env.VITE_API_BASE`, default `/hr/api` for prod,
      `http://localhost:8000/api` for dev)
- [ ] Check for client-side router `basename` requirements (none found in initial scan, so
      re-verify once files are copied)
- [ ] `npm run build` and confirm the built `dist/` loads correctly when served under a `/hr/`
      prefix (test with a throwaway static server before wiring into the backend)

**Exit criteria:** frontend builds, all asset/API paths resolve correctly under `/hr/` prefix
when served locally.

---

## Phase 5 — Local integration test

- [ ] Serve built frontend `dist/` as static files from the FastAPI app (or via a lightweight
      reverse-proxy setup replicating the prod path) alongside `/api/*` routes, all under one
      local port
- [ ] Full manual pass: admin login, create campaign, run pipeline (search → filter → rank),
      view results, export
- [ ] Confirm no secrets/API keys committed; `.env`/DB files gitignored

**Exit criteria:** whole app works end-to-end on a single local port, mirroring what prod will
look like structurally.

---

## Phase 6 — Deployment (production infra — needs explicit go-ahead per step)

- [ ] Write systemd unit `hr-tech.service` (uvicorn, `127.0.0.1:8766`, `WorkingDirectory` set,
      env file for API keys)
- [ ] Add nginx `location /hr { proxy_pass http://127.0.0.1:8766/; ... }` block to
      `/etc/nginx/sites-enabled/stagetwoforge` (existing config only proxies `/` today — this
      is the first path-based route on that domain, review carefully)
- [ ] `nginx -t` before reload, then reload
- [ ] Start + enable `hr-tech.service`, confirm `https://stagetwoforge.com/hr` serves the app
- [ ] Verify TLS/cert (already covers the domain via existing Certbot cert, no new cert needed)

**Exit criteria:** app reachable at `stagetwoforge.com/hr` over HTTPS, systemd service enabled
on boot.

---

## Phase 7 — Cutover + cleanup

- [ ] Replace the `/hr` stub in `momentum-signals/server.py:111` (currently "under
      construction" text) — likely just remove it once nginx routes `/hr` directly to the new
      service, or replace with a redirect if nginx routing isn't in place yet
- [ ] Final smoke test through the real domain (not localhost)
- [ ] Decide what to do with `~/misc/hr_agent_ui` and the zips (archive or remove, since the
      code now lives in `hr_tech/web/`)

**Exit criteria:** live, no leftover stub routes, source of truth is `hr_tech` repo only.

---

## Env vars needed (final list, grows as phases land)

```
EXA_API_KEY=<key>                    # search.py default provider
DATALABS_API_KEY=<key>               # optional, only if provider=peopledatalabs
APOLLO_API_KEY=<key>                 # optional, only if provider=apollo
VITE_API_BASE=/hr/api                # frontend build-time env
```

No cookie-signing secret needed — auth uses random Bearer tokens (sha256-hashed at rest), not
signed cookies.

---

## What's explicitly out of scope (for now)

- Password reset
- Email notifications when a run completes
- Sharing campaigns across users
- Rate limiting / concurrent run caps

---

<details>
<summary>Original from-scratch plan (superseded, kept for reference)</summary>

# Sourcing Copilot — Web UI Implementation Plan (v1, superseded)

Wraps `candidate_pool/` in a multi-user web application served at `stagetwoforge.com/hr`.

## Goals

- Recruiters log in, create campaigns, run the pipeline, and review/store results — all in-browser
- Campaigns and results are persisted per user for future reference
- No self-registration: admin creates accounts manually
- No job queue: pipeline runs in a background thread, frontend polls for status

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

## Auth (`auth.py`)

- **Password hashing:** `bcrypt` via `passlib`
- **Sessions:** signed cookie using `itsdangerous.URLSafeTimedSerializer` — stores `{"user_id": <id>}`, 7-day expiry
- **FastAPI dependency:** `get_current_user(request)` — reads cookie, verifies signature, returns user row or raises 401
- **Admin account creation:** CLI command `python -m web.auth create-user <email> <password>` — hashes password, inserts into DB

No password reset flow for now — admin resets manually via the same CLI.

## Deployment

The web app runs as a **separate systemd service** (`sourcing-copilot.service`), not inside `momentum-signals.service`. This keeps the two apps isolated — crashes in one don't affect the other.

`momentum-signals/server.py` route for `/hr` changes from the "under construction" stub to a **reverse proxy pass** to the new service (or a redirect).

</details>
