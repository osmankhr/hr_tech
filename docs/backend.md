# `web/backend/` — FastAPI Backend

> Living reference doc. Update this file (not just memory) whenever routes/schema change.
> Last generated: 2026-09-09.

## 1. What this is

A single-file FastAPI app (`main.py`) that:
- Serves REST + SSE APIs for a recruiter-facing HR web app (auth, campaigns, candidates, comments,
  activity log).
- Drives the `candidate_pool/` sourcing pipeline as background subprocesses and exposes staged
  pipeline artifacts (queries/search/filter/rank) to the frontend.
- In production, also serves the built React frontend as static files (mounted last, after all
  `/api/*` routes, so it acts as a catch-all).

Originally adopted from a colleague's prototype (`hr_agent_ui`) and hardened — see
`web/PLAN.md` for the security fixes made during that port (removed public signup, removed
hardcoded admin password, fixed missing SQL views, fixed hardcoded Copilot model name).

No ORM (raw `sqlite3`), no JWT library — auth is custom bearer-token based (see §4).

### Path/constants (module-level in `main.py`)
| Constant | Value |
|---|---|
| `DB_PATH` | `web/backend/hr_candidate_search_demo.db` (absolute, not CWD-relative) |
| `CANDIDATE_POOL_ROOT` | `hr_tech/candidate_pool` (`BACKEND_DIR.parent.parent / "candidate_pool"`) |
| `CANDIDATE_POOL_CAMPAIGNS_DIR` | `CANDIDATE_POOL_ROOT / "campaigns"` |
| `UPLOAD_DIR` | `web/backend/uploaded_cvs/` (created on startup) |
| `FRONTEND_DIST` | `web/frontend/dist/` (mounted as static catch-all if present) |
| `MAX_WORKERS_CAP` | 20 |
| `STALE_RUN_TIMEOUT_MINUTES` | 30 |

---

## 2. Database schema

SQLite, no migrations framework — schema created by `create_sample_hr_db.py` (destructive: deletes
and recreates the DB file), extended idempotently by `migrate_auth_audit.py` /
`migrate_comments.py`, and `main.py`'s own `ensure_pipeline_tables()` (called on startup).

### Tables
| Table | Key columns | Notes |
|---|---|---|
| `users` | `id, email UNIQUE, full_name, role CHECK(admin\|hr), password_hash, password_salt, password_iterations, is_active` | |
| `auth_tokens` | `id, user_id FK, token_hash UNIQUE, expires_at, revoked_at` | raw token never stored, only its SHA-256 |
| `campaigns` | `id, campaign_code UNIQUE, campaign_name, location, position_name, experience, sample_cv_filename, target_profiles, status CHECK(Draft\|Active\|Past), owner, created_by_user_id FK, updated_by_user_id FK` | |
| `candidates` | `id, candidate_code UNIQUE, full_name, email, current_title, location, source, profile_url, score, status CHECK(New\|Reviewed\|Shortlisted\|Contacted\|Rejected), years_experience, english_confidence(_reason), notes` | |
| `skills` | `id, name UNIQUE` | |
| `campaign_skills`, `candidate_skills` | composite PK | M:N join tables |
| `campaign_candidates` | `(campaign_id, candidate_id)` PK, `match_score, pipeline_stage CHECK(Found\|Reviewed\|Shortlisted\|Contacted\|Rejected)` | per-campaign candidate association |
| `search_runs` | `id, campaign_id FK, search_query, total_results, status` | defined in schema but **unused by any current route** (legacy) |
| `refresh_logs` | `id, candidate_id FK, refresh_type, status, message` | written by `POST /api/candidates/refresh` |
| `audit_events` | `id, entity_type CHECK(campaign\|candidate\|search_run\|refresh_log\|auth\|campaign_candidate), entity_id, action, description, user_id FK` | powers `/candidates/{id}/activities` |
| `candidate_comments` | `id, candidate_id FK, user_id FK, parent_id FK→self (threading), content` | |
| `pipeline_campaign_configs` | `id, campaign_id UNIQUE FK, pipeline_dir, campaign_yaml_path, job_description_path, filter_criteria_path, queries_ready_at, search_completed_at, filter_completed_at, rank_completed_at` | one row per campaign, tracks its `candidate_pool` folder + stage timestamps |
| `pipeline_runs` | `id, campaign_id FK, run_type CHECK(full\|queries\|search\|filter\|rank\|report\|import), status CHECK(Queued\|Running\|Completed\|Failed), command, campaign_dir, artifact_path, error_message, accepted_candidates, ranked_candidates` | history of every pipeline invocation |
| `candidate_rankings` | `id, campaign_id FK, candidate_id FK, manual_score, category, rank, feature_contributions_json, gate_penalty, ai_adjustment, raw_agent_json, raw_manual_json`, UNIQUE(campaign_id, candidate_id) | ranking pipeline output per candidate |

### Views
- **`campaign_summary`** — campaigns + creator/updater names + `candidate_count` +
  `shortlisted_count` + comma-joined `desired_skills`. Backs `GET /api/campaigns`, `/active`, `/past`.
- **`candidate_profile_summary`** — candidates + creator/updater/first-contacted names + comma-joined
  `skills`. Backs `GET /api/candidates`.

  ⚠️ History note: these two views were **missing** from the originally ported
  `create_sample_hr_db.py`, causing "Could not load data from backend" on every fresh login in
  production. Fixed by adding view definitions + applying live via `CREATE VIEW IF NOT EXISTS`.
  If you ever regenerate the DB from scratch, verify these views exist.

---

## 3. Bootstrap / migration scripts

| Script | Purpose |
|---|---|
| `create_sample_hr_db.py` | **Destructively** deletes + recreates `hr_candidate_search_demo.db` with the full empty schema (no seed data, despite the name). Run once, then run `migrate_auth_audit.py`. |
| `migrate_auth_audit.py` | Idempotent: creates `users`/`auth_tokens` tables if missing, adds ownership columns to `campaigns`/`candidates`, seeds a bootstrap admin (`HR_ADMIN_EMAIL`/`HR_ADMIN_PASSWORD` env vars, or a random generated password printed once), backfills ownership on existing rows, repairs `campaign_summary` view if outdated. |
| `migrate_comments.py` | Idempotent: adds `candidate_comments` table for installs predating comment support. |

`auth_utils.py` holds the pure password/token primitives (no FastAPI/DB dependency):

| Function | Behavior |
|---|---|
| `utc_now()` | `datetime.utcnow().isoformat(timespec="seconds")` |
| `hash_password(password, salt=None)` | PBKDF2-HMAC-SHA256, `PASSWORD_ITERATIONS=600_000`, random 32-byte hex salt if not given |
| `verify_password(password, stored_hash, salt, iterations)` | recomputes with the row's own stored iteration count, compares via `hmac.compare_digest` |
| `create_raw_token()` | `secrets.token_urlsafe(48)` |
| `hash_token(raw_token)` | SHA-256 hex digest — this is what's persisted, never the raw token |
| `token_expiry()` | now + `TOKEN_EXPIRE_HOURS=12`, ISO string |

---

## 4. Auth & authorization model

- **Not JWT, not signed cookies.** `POST /api/auth/signin` issues a random 48-byte URL-safe token;
  only its SHA-256 hash is stored (`auth_tokens.token_hash`). Client sends it back as
  `Authorization: Bearer <raw_token>`.
- **Validation** (`_get_current_user_from_raw_token`): hash token → join `auth_tokens`+`users` →
  401 if no match / revoked, 403 if `is_active=0`, 401 if past `expires_at` (12h, no refresh
  mechanism — must re-signin).
- **Roles**: `admin` | `hr` (DB CHECK constraint).
  - `get_current_user` — base dependency, any authenticated user.
  - `require_admin` — additionally requires `role == "admin"`; gates `POST/GET /api/users`.
- **Ownership scoping** (`_get_owned_campaign`): admins see all campaigns; `hr` users only see
  campaigns where `created_by_user_id` matches them. Non-owners get **404, not 403** (avoids leaking
  existence of other users' campaigns) on essentially every campaign/pipeline route.
- ⚠️ **Inconsistency to know about**: `GET/PUT /api/candidates/{id}` are **not** ownership-scoped —
  any authenticated user of any role can read/edit any candidate globally, unlike the careful
  per-campaign scoping elsewhere.
- **No self-registration.** No `/api/auth/signup` route exists. New accounts only via
  `POST /api/users` (admin-only). This was a deliberate fix over the forked code, which had a public
  signup endpoint defaulting to `role='hr'`.
- **Bootstrap admin** created only by `migrate_auth_audit.py`, never hardcoded in source.

---

## 5. API routes

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/api/auth/signin` | public | issue bearer token |
| GET | `/api/auth/me` | user | current user profile |
| POST | `/api/auth/signout` | user (best-effort) | revoke current token |
| POST | `/api/users` | **admin** | create user (`role` defaults `hr`) |
| GET | `/api/users` | **admin** | list all users |
| GET | `/api/campaigns` | user | list (scoped) campaigns from `campaign_summary` view |
| POST | `/api/campaigns` | user | create campaign (+ optional PDF `sample_cv` upload) |
| GET | `/api/campaigns/{id}` | user (owner/admin) | single campaign detail + counts + skills |
| PUT | `/api/campaigns/{id}` | user (owner/admin) | update campaign + replace skills |
| DELETE | `/api/campaigns/{id}` | user (owner/admin) | delete campaign, cascade candidates, remove `candidate_pool` dir (path-traversal-guarded) |
| GET | `/api/campaigns/active` / `/past` | user | scoped campaigns by status |
| GET | `/api/campaigns/{id}/candidates` | user (owner/admin) | paginated candidates for a campaign (`page`, `page_size` ≤50) |
| GET | `/api/campaigns/{id}/rankings` | user (owner/admin) | joined `candidate_rankings` + `candidates`, JSON-decoded blobs |
| GET | `/api/candidates` | user | all candidates from `candidate_profile_summary` view |
| GET | `/api/candidates/{id}` | user (**not** ownership-scoped) | candidate detail + skills |
| PUT | `/api/candidates/{id}` | user (**not** ownership-scoped) | update candidate + replace skills |
| POST | `/api/candidates/refresh` | user | mock refresh (bumps every score by 1, capped 99) + logs `refresh_logs` |
| GET | `/api/candidates/{id}/activities` | user | audit-log entries |
| GET | `/api/candidates/{id}/comments` | user | threaded comments |
| POST | `/api/candidates/{id}/comments` | user | add comment (optional `parent_id`) + audit event |
| GET | `/api/skills` | user | distinct skill names |
| POST | `/api/campaigns/{id}/pipeline/setup` | user (owner/admin) | create `candidate_pool` campaign folder (`campaign.yaml` + `input/*.md`), upsert `pipeline_campaign_configs` |
| GET | `/api/campaigns/{id}/pipeline/runs` | user (owner/admin) | list `pipeline_runs` (marks stale runs failed first) |
| GET | `/api/campaigns/{id}/pipeline/events` | user (header **or** `?token=`) | **SSE** stream, latest run status every 2s |
| POST | `/api/campaigns/{id}/pipeline/run` | user (owner/admin) | kick off `run_campaign.py` subprocess in a background thread |
| POST | `/api/campaigns/{id}/pipeline/import-ranked` | user (owner/admin) | import `ranked_results.json` into `candidates`/`campaign_candidates`/`candidate_rankings` |
| GET/PUT | `/api/campaigns/{id}/pipeline/queries` | user (owner/admin) | read/overwrite `generated_queries.yaml` |
| GET | `/api/campaigns/{id}/pipeline/stages` | user (owner/admin) | combined DB-timestamp + on-disk stage readiness |
| GET | `/api/campaigns/{id}/pipeline/search-results-status` | user (owner/admin) | existence + count summary of raw search files |
| GET | `/api/campaigns/{id}/pipeline/search-results` | user (owner/admin) | paginated raw search results (`limit_per_location`) |
| GET | `/api/campaigns/{id}/pipeline/filtered-results` | user (owner/admin) | `filtered_results.json` (`limit`) + ACCEPT/REJECT/PENDING counts |
| GET | `/api/campaigns/{id}/pipeline/export-search-csv` / `-excel` | user (owner/admin) | flattened raw search results download |
| GET | `/api/campaigns/{id}/pipeline/ranked-results-status` | user (owner/admin) | whether `ranked_results.json` exists |
| GET | `/api/campaigns/{id}/pipeline/export-ranked-csv` | user (owner/admin) | flattened ranked results download |
| — (static mount) | `/` | — | serves built frontend `dist/`; registered **last** so it never shadows `/api/*` |

### Notable route behaviors
- `setup_pipeline_campaign`: form fields `pipeline_name`, `pipeline_description`, `locations_json`
  (JSON array of `{name, hint}`), `job_description`, `filter_criteria`. Folder name =
  `<slug>_<UTC timestamp>`; 409 if it already exists.
- `run_pipeline`: form field `run_type` (`full|queries|search|filter|rank|report`, default `full`),
  optional `max_candidates` (1–100). 409 if a run is already `Running` for that campaign. See §6 for
  the flag mapping.
- `stream_pipeline_events`: accepts token via header **or** `?token=` query param (needed because
  `EventSource` can't set custom headers). Emits `pipeline_run_update` / `heartbeat` events every 2s.
- `import_ranked_results`: upserts `candidates` (matched by `profile_url` then `email`),
  `campaign_candidates`, `candidate_rankings` — all in one transaction, rolls back + marks
  `pipeline_runs.status='Failed'` on exception.

---

## 6. Integration with `candidate_pool/`

- **Python interpreter resolution**:
  ```python
  preferred = CANDIDATE_POOL_ROOT / ".venv" / "bin" / "python"
  python_bin = os.getenv("CANDIDATE_POOL_PYTHON") or (str(preferred) if preferred.exists() else "python3")
  ```
- **`run_type` → `run_campaign.py` flags**:

  | `run_type` | Flags |
  |---|---|
  | `full` | *(none)* |
  | `queries` | `--queries-only --force-queries` |
  | `search` | `--search-only` |
  | `filter` | `--filter-only` |
  | `rank` | `--rank-only` |
  | `report` | `--report-only` |

  If `max_candidates` given, also appends `--filter-max-candidates`, `--ranking-max-candidates`,
  `--filter-max-workers`, `--ranking-max-workers` (workers = `min(max_candidates, MAX_WORKERS_CAP=20)`).
  Full command: `[python_bin, "scripts/run_campaign.py", str(pipeline_dir), *flags]`, `cwd=CANDIDATE_POOL_ROOT`.
- **Execution model**: `subprocess.run(...)` (blocking) inside a **daemon thread**, not
  `Popen`+poll, not a real job queue. `_mark_stale_running_runs` auto-fails any `Running` row older
  than 30 minutes (guards against orphaned threads from dev-server reloads/restarts).
- **Staged artifact endpoints** let the frontend inspect/edit intermediate state without running the
  whole pipeline (queries editor, search/filtered previews, stage-readiness, CSV/Excel exports).

---

## 7. Environment variables

| Variable | Used in | Default if unset |
|---|---|---|
| `HR_CORS_ORIGINS` | CORS allowed origins (comma-separated) | `http://localhost:5173` |
| `CANDIDATE_POOL_PYTHON` | interpreter for `candidate_pool` subprocesses | `candidate_pool/.venv/bin/python` if present, else `python3` |
| `HR_ADMIN_EMAIL` | bootstrap admin email (`migrate_auth_audit.py`) | `admin@hr.local` |
| `HR_ADMIN_PASSWORD` | bootstrap admin password | randomly generated + printed once |

(`candidate_pool` itself separately needs `EXA_API_KEY` / `DATALABS_API_KEY` / `APOLLO_API_KEY`;
the frontend build needs `VITE_API_BASE` — neither read directly by this backend.)

---

## 8. Deployment

- **systemd** (`web/deploy/hr-tech.service`): uvicorn bound to `127.0.0.1:8766` (loopback only),
  `WorkingDirectory=web/backend`, `EnvironmentFile=.env`, `Restart=always`.
- **nginx** (`web/deploy/nginx-hr-location.conf`): `location = /hr` → 301 redirect to `/hr/`;
  `location /hr/` → `proxy_pass http://127.0.0.1:8766/` (prefix stripped), `proxy_buffering off`
  (required so the SSE `pipeline/events` endpoint streams instead of being buffered). The FastAPI
  app itself has no knowledge of the `/hr` prefix — it always serves at root.
- Live at `https://stagetwoforge.com/hr/`.
- No job queue, no rate limiting, no password reset, no cross-user campaign sharing — all
  explicitly out of scope per `web/PLAN.md`.

---

## 9. Libraries used

| Package | Purpose |
|---|---|
| `fastapi` | routing, DI, request parsing (`Form`, `UploadFile`, `Depends`, `Header`, `Query`) |
| `uvicorn[standard]` | ASGI server (run via CLI, not imported) |
| `python-multipart` | required for `Form(...)`/`UploadFile` parsing |
| `openpyxl` | Excel export routes |
| `sqlite3`, `hashlib`, `hmac`, `secrets`, `shutil`, `subprocess`, `threading`, `csv`, `io`, `re`, `yaml` (PyYAML) | stdlib + PyYAML, everything else |

No ORM, no `passlib`, no `jose`/JWT library, no `requests` (uses stdlib `urllib`/`subprocess` only
where needed — mirrors the same stdlib-first style as `candidate_pool`).
