# `web/frontend/` — React (Vite) Frontend

> Living reference doc. Update this file (not just memory) whenever components/hooks change.
> Last generated: 2026-09-09.

## 1. What this is

A Vite + React 19 SPA (`hr-candidate-search-ui`), deployed under the `/hr/` subpath, no router
library, no global state library, no HTTP client library — plain `fetch` + custom hooks +
prop-drilling. Talks to the `web/backend` FastAPI app over `/api/*`.

### `package.json`
| Dependency | Purpose |
|---|---|
| `react` / `react-dom` ^19.2.7 | UI library |
| `lucide-react` ^1.33.0 | icon set |
| `@fontsource/inter` ^5.3.0 | self-hosted Inter font (no external font CDN) |
| `date-fns` ^4.4.0 | imported in `CandidateActivityLog.jsx` but **currently unused/dead** (native `Date` used instead) |
| `vite` / `@vitejs/plugin-react` | build tooling |
| `tailwindcss` / `@tailwindcss/vite` ^4.3.2 | Tailwind v4 via Vite plugin (config lives in CSS `@theme`, no `tailwind.config.js`) |
| `oxlint` | linter (Rust-based, replaces ESLint) |

Scripts: `dev`, `build`, `lint`, `preview`.

### `vite.config.js`
```js
export default defineConfig({ base: "/hr/", plugins: [react(), tailwindcss()] });
```
`base: "/hr/"` matches the nginx `/hr/` proxy prefix (see [backend.md](./backend.md) §8).

### API base URL resolution (`src/config/api.js`)
```js
export const API_BASE_URL = import.meta.env.VITE_API_BASE ?? "http://localhost:8000/api";
```
Prod build (`.env.production`) sets `VITE_API_BASE=/hr/api`; dev falls back to
`http://localhost:8000/api`. This is the single source of truth for the API base, consumed by
`httpClient.js` and a few raw-`fetch` call sites (file exports, SSE).

### `src/constants/defaults.js`
- `DEFAULT_SKILL_SUGGESTIONS` — ~31 static fallback skill chips shown before/if the backend's
  dynamic `/skills` list loads.
- `EMPTY_CAMPAIGN_FORM` — blank campaign form shape (`campaignName, location, positionName,
  desiredSkillsText, experience: "3-5", sampleCvFile: null, targetProfiles: 25, status: "Active"`).

---

## 2. Bootstrap & routing

- `src/main.jsx` — mounts `<App />` in `<StrictMode>`.
- `src/App.jsx` — **the entire routing mechanism**: calls `useAuth()`; no user → `AuthPage`;
  authenticated → `HRCandidateSearchPage`. No router library at all. Within
  `HRCandidateSearchPage`, page switching is a plain `view` string state (no URL sync — refresh
  always resets to `"dashboard"`, no deep-linking).
- `src/index.css` — `@import "tailwindcss";`, self-hosted Inter via `@fontsource`, a
  **comment-only** heading-size convention (page title = `text-xl font-semibold`, panel/modal
  title = `text-base font-semibold`), `@theme { --font-sans: "Inter", ... }`.

**Styling:** Tailwind utility classes directly in JSX everywhere; no CSS modules, no
styled-components. Palette: `slate` (neutral), `indigo` (primary), `emerald`/`green` (success),
`amber` (warning), `red` (danger). Cards = `rounded-xl shadow-sm ring-1 ring-slate-200`.

---

## 3. API layer (`src/api/`)

### `httpClient.js` — central fetch wrapper
- `getToken()` — reads bearer token from `localStorage["hr_auth_token"]`.
- Internal `request(path, options)`: JSON-serializes plain-object bodies (leaves `FormData` alone
  so the browser sets multipart boundaries — this is why most calls build `FormData` even for
  JSON-shaped data); injects `Authorization: Bearer <token>` if present; on non-OK response, parses
  FastAPI's `{detail}` error shape into a thrown `Error`.
- Exports `httpClient.{get, post, put, delete}`.

⚠️ **Security note**: token lives in `localStorage`, not an httpOnly cookie — vulnerable to
XSS-based token theft if any XSS vector exists elsewhere in the app. Common pattern, but worth
flagging if hardening auth further.

### `authApi.js`
`signIn(email, password)` (FormData → `POST /auth/signin`, returns `{token, user}`), `me()`
(`GET /auth/me`), `signOut()` (`POST /auth/signout`).

### `campaignApi.js` — largest module
| Method | HTTP + Path |
|---|---|
| `getAll()` | GET `/campaigns` |
| `create(formData)` | POST `/campaigns` |
| `getById(id)` | GET `/campaigns/{id}` |
| `update(id, formData)` | PUT `/campaigns/{id}` |
| `remove(id)` | DELETE `/campaigns/{id}` |
| `setupPipeline(id, payload)` | POST `/campaigns/{id}/pipeline/setup` (FormData: `pipeline_name`, `pipeline_description`, `locations_json`, `job_description`, `filter_criteria`) |
| `importRankedResults(id, path)` | POST `/campaigns/{id}/pipeline/import-ranked` |
| `getPipelineRuns(id)` | GET `/campaigns/{id}/pipeline/runs` |
| `getPipelineStages(id)` | GET `/campaigns/{id}/pipeline/stages` |
| `getGeneratedQueries(id)` / `saveGeneratedQueries(id, queries)` | GET/PUT `/campaigns/{id}/pipeline/queries` |
| `getSearchResults(id, limitPerLocation)` | GET `/campaigns/{id}/pipeline/search-results` |
| `getFilteredResults(id, limit)` | GET `/campaigns/{id}/pipeline/filtered-results` |
| `getSearchResultsStatus` / `getRankedResultsStatus` | GET `/pipeline/search-results-status` / `/ranked-results-status` |
| `getRankings(id)` | GET `/campaigns/{id}/rankings` |
| `runPipeline(id, runType, maxCandidates)` | POST `/campaigns/{id}/pipeline/run` |
| `getCandidatesByCampaign(id, page, pageSize)` | GET `/campaigns/{id}/candidates` |
| `exportRankedCsv` / `exportSearchCsv` / `exportSearchExcel` | GET `/pipeline/export-*` — **bypass `httpClient`**, use raw `fetch` + manual Blob/object-URL download (needed for binary/file responses); each duplicates its own auth-header + error handling (candidate for a shared helper). |

### `candidateApi.js`
`getAll()`, `getById(id)`, `update(id, formData)`, `refresh()` (`POST /candidates/refresh`),
`getActivities(id)`, `getComments(id)`, `addComment(id, {content, parent_id})` (threaded).

### `skillApi.js`
`getAll()` → `GET /skills`, used to override `DEFAULT_SKILL_SUGGESTIONS`.

---

## 4. Mappers (`src/mappers/`) — snake_case ↔ camelCase boundary

- **`campaignMapper.js`**: `mapCampaignFromApi` (API → view model, splits `desired_skills` string
  into array, truncates `created_at` to `YYYY-MM-DD`), `campaignToFormData` (view model →
  `FormData` for create/update), `campaignToEditForm` (view model → editable form shape).
- **`candidateMapper.js`**: `mapCandidateFromApi` (`full_name`→`name`, `current_title`→`role`,
  splits `skills` string to array), `candidateToFormData` (form → `FormData` for update).

All API responses pass through a mapper before touching component state; all writes go back through
a `*ToFormData` mapper. There is **no optimistic update / cache layer** — every mutation triggers a
full manual refetch of the relevant list(s).

---

## 5. Custom hooks (`src/hooks/`)

### `useAuth.js`
State: `user`, `authLoading` (starts `true`), `authError`.
- `signIn(email, password)` → stores token in `localStorage`, sets `user`.
- `signOut()` → best-effort server call, always clears local token/user regardless of outcome.
- On mount: if a token exists, calls `authApi.me()` to validate/hydrate session (silent restore);
  clears stale token on failure.
- Returns `{user, authLoading, authError, signIn, signOut}` — consumed directly by `App.jsx`.

### `useCampaignForm.js`
Encapsulates the campaign create/edit form's local state (shared between create/edit flows).
State: `campaignForm`, `skillInput`, `formError`, `sampleCvRef` (DOM ref to reset file input).
Derived: `selectedSkills` (comma-split from `desiredSkillsText`).
Functions: `updateForm`, `resetForm`, `addSkill` (dedupes case-insensitively), `removeSkill`,
`handleSkillKeyDown` (Enter/comma commits a chip), `handleCvUpload` (validates PDF mimetype/extension).

### `useHrData.js`
Primary data-fetch hook for global app data.
State: `campaigns`, `candidates`, `skillSuggestions` (defaults to static list), `loading`, `apiError`.
`loadCampaigns` / `loadCandidates` / `loadSkills` (each maps API → view model), `loadInitialData`
(runs all three via `Promise.all` on mount, sets a generic `apiError` on any failure). Re-invoked
manually by `HRCandidateSearchPage` after every create/update/delete mutation.

---

## 6. Pages (`src/pages/`)

### `AuthPage.jsx`
Sign-in screen. Local `email`/`password` state, calls `onSignIn` prop (→ `useAuth.signIn`).
Footer note: "Accounts are created by an administrator" (reflects the no-self-signup backend design).

### `HRCandidateSearchPage.jsx` — the main app shell (~1580 lines, a "god component")
Owns nearly all app-level state; no router, manual `view` tab switching
(`dashboard | pipeline | campaigns | active | past | database`).

**Key state groups:**
- Navigation/search/filter state for the candidate database view.
- Create-campaign flow state (`showCreate`, `createForm`, `createBusy/Error`).
- Modal/selection state (selected/editing/deleting campaign or candidate).
- **Dashboard tab**: per-campaign paginated candidate list.
- **Pipeline tab** (largest chunk): current pipeline campaign, `pipelineRuns`, `rankings`,
  `pipelineStages`, editable `queryDraft`, `searchPreview`, `filteredPreview`, per-campaign
  `campaignArtifactStatus` map, per-export-button busy-state map.
- `autoImportedRunIdsRef` — tracks which pipeline run IDs already triggered an auto-import of
  ranked results, to avoid duplicate imports across SSE re-renders.

**Real-time pipeline updates**: opens `new EventSource(".../pipeline/events?token=...")`
(token in query param because `EventSource` can't set custom headers) whenever the selected
pipeline campaign changes. On `pipeline_run_update`: merges the run into `pipelineRuns`;
auto-calls `campaignApi.importRankedResults` the first time a `full`/`rank` run completes;
refreshes rankings/stages/query-and-search-previews/global candidates/campaigns and artifact
statuses. Closes the `EventSource` on unmount or dependency change.

**Campaign creation is a two-step backend call**: `campaignApi.create` (baseline `FormData` →
`campaign_id`) then `campaignApi.setupPipeline(campaignId, ...)` (writes `campaign.yaml` +
`input/*.md` via the backend). Not a single atomic call.

**Render structure**: `Sidebar` + `main` (`AppHeader`, mobile tab switcher, loading/error banners,
conditional `PipelineCampaignCreateForm`, then one of the 6 `view` sections) + 5 always-mounted
modals that internally `return null` when their subject is falsy
(`CampaignDetailModal`, `CampaignEditModal`, `CampaignDeleteModal`, `CandidateDetailModal`,
`CandidateEditModal`).

This page is the composition root for essentially every feature/UI component in the app.

---

## 7. Layout & UI primitives

### `src/components/layout/`
- `AppHeader.jsx` — title/subtitle + "Create New Campaign" / "Refresh Candidates" (spinning icon
  while busy) / "Sign Out" buttons. Purely presentational.
- `Sidebar.jsx` — desktop-only vertical nav, 6 buttons mapping to `view` states.

### `src/components/ui/` — small internal design system
| Component | Purpose |
|---|---|
| `Badge` | pill label, `tone` prop (`green/brand/amber/gray/red`) |
| `Button` | `variant` prop (`primary/dark/outline/soft/danger`) |
| `Card` | base white rounded surface |
| `EmptyState` | dashed-border placeholder for empty lists |
| `Icon` | `Icons` lookup mapping short names → specific `lucide-react` icons (some files still import `lucide-react` directly — inconsistent usage) |
| `InputField` | labeled input, `onChange` receives the raw value (not the event) |
| `KPI` | dashboard stat card (icon + value + label + sub-text) |
| `Modal` | fixed overlay + centered panel + title bar + Close button — base for every modal in the app |
| `SkillSelector` | chip-style multi-select for skills, fully controlled by `useCampaignForm` |

---

## 8. Feature components

### `src/features/campaigns/`
- `CampaignCard.jsx` — clickable summary card (name, status badge, metrics grid via internal
  `MetricBox`); if `full`, shows action row (Explore/View Details/Edit/Delete). Note: a "Run
  Search" button exists but its click handler only stops propagation — appears to be a stub.
- `CampaignPanel.jsx` — `Card` wrapper listing `CampaignCard`s or an `EmptyState`.
- `CampaignDetailModal.jsx` — read-only detail view (`Info` tiles grid).
- `CampaignEditModal.jsx` — wraps `CampaignForm` with a skill-suggestion filter (`useMemo`, caps 8).
- `CampaignForm.jsx` — pure presentational **edit-only** form (fields + `SkillSelector`); creation
  uses a different form (`PipelineCampaignCreateForm`), not this one.
- `CampaignDeleteModal.jsx` — confirmation dialog; warns deletion also removes `candidate_pool`
  campaign files (matches backend's cascade delete + `_remove_pipeline_campaign_dir`).
- `PipelineCampaignCreateForm.jsx` — the actual **creation** form: name, description, dynamic
  locations list (name+hint rows, add/remove), large Job Description + Filter Criteria markdown
  textareas — these two feed `campaignApi.setupPipeline`'s `job_description`/`filter_criteria`.

### `src/features/candidates/`
- `CandidateCard.jsx` — summary card with status badge (via `getCandidateStatusTone`), rank
  display if `candidate.ranking?.rank` exists, score chip (prefers `ranking.manual_score` over
  raw `score`).
- `CandidatePanel.jsx` — list wrapper with optional pagination controls (Previous/Next).
- `CandidateDetailModal.jsx` — the most complex component: tabbed view (Details / Comments /
  Activity), an **"explainable AI ranking" breakdown** reading `candidate.ranking.manual` +
  `candidate.ranking.agent.feature_assessments` + a `scoringExplainer` prop (features/hard_gates) —
  tightly coupled to the shape produced by `candidate_pool/scripts/ranking/`. Clicking a feature
  contribution opens a nested modal with evidence/notes for that specific feature
  (`FeatureAssessmentContent`).
- `CandidateEditModal.jsx` — edit form seeded from the `candidate` prop. ⚠️ Contains a
  `useState` call positioned after an early-return guard (`if (!candidate) return null;`) —
  violates React's Rules of Hooks in principle; works today only because the early return means
  React never reaches that hook on the relevant render. Don't add hooks *before* the guard without
  fixing this.
- `CandidateProgressBar.jsx` — 4-step stepper (New → Reviewed → Shortlisted → Contacted), special
  greyed-out "Candidate Rejected" state.
- `CandidateComments.jsx` — recursive `CommentItem` (renders nested replies via
  `allComments.filter(c => c.parent_id === comment.id)`, arbitrarily deep threads), root-level
  comment composer.
- `CandidateActivityLog.jsx` — fetches and renders a vertical timeline of `audit_events`.

---

## 9. Cross-cutting architecture summary

- **State management**: no Redux/Zustand/Context — everything is local `useState`/`useMemo`/`useRef`
  organized into hooks (`useAuth`, `useHrData`, `useCampaignForm`), composed and prop-drilled from
  `HRCandidateSearchPage` down.
- **Routing**: none. Auth-gated binary switch in `App.jsx`; manual `view` string switch inside
  `HRCandidateSearchPage`. No deep-linking.
- **Real-time**: Server-Sent Events (`EventSource`) for pipeline run status — not polling, not
  WebSockets (though the SSE endpoint itself is implemented as 2s server-side polling of the DB,
  see [backend.md](./backend.md) §5).
- **Data flow**: backend snake_case JSON → `mappers/*.js` → camelCase view model → React
  state/props → UI. Mutations build `FormData` via `*ToFormData` mappers → API call → full manual
  refetch (no optimistic updates, no cache invalidation library).

### Component composition (high level)
```
App
├─ AuthPage (Card, Button, InputField)
└─ HRCandidateSearchPage
   ├─ Sidebar
   ├─ AppHeader
   ├─ PipelineCampaignCreateForm
   ├─ KPI × 4
   ├─ CampaignPanel → CampaignCard × N
   ├─ CandidatePanel → CandidateCard × N
   ├─ CampaignDetailModal / CampaignEditModal(→CampaignForm→SkillSelector) / CampaignDeleteModal
   └─ CandidateDetailModal(→CandidateProgressBar, CandidateComments, CandidateActivityLog) / CandidateEditModal
```

---

## 10. Known rough edges (for future work)

1. `date-fns` imported but unused in `CandidateActivityLog.jsx` — dead dependency in that file.
2. `CampaignCard`'s "Run Search" button appears to be a non-wired stub (only stops propagation).
3. `CampaignPanel`'s `renderExtraActions`/`extraActions` prop may not actually be rendered inside
   `CampaignCard` — verify before relying on it for new export-button wiring.
4. `CandidateEditModal` has a hook called after an early-return guard — fragile, fix before adding
   more hooks to that component.
5. Export functions (`exportSearchCsv`/`exportSearchExcel`/`exportRankedCsv`) duplicate
   blob-download + auth-header logic three times — candidate for a shared helper.
6. Bearer token in `localStorage` — acceptable for now per project scope, but a real XSS
   vulnerability vector if introduced elsewhere.
