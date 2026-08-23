# User Feedback — Fix List (2026-08-22)

Source: `feedback.txt` (raw reviewer notes, Turkish/English mixed), collected from ING recruiters
testing the candidate search tool across five roles: MLE, Data & AI Chapter Lead, GCP Data
Engineer, Chapter Lead Solution Architect, DevOps Engineer.

**Reviewer key** (initials → name, for follow-up questions):
- MC = Mehmet Can Erim
- UU = Ugur Uresin
- OK = Osman Kahraman
- MY = Muge Yalcinkaya
- ES = Emre Selcuk

Reviewers whose feedback is directly attributed in `feedback.txt`: Kagan (MLE, Chapter Lead, GCP
Data Engineer roles), Emine (Chapter Lead Solution Architect, DevOps Engineer roles).

---

## Bugs (high priority — incorrect behavior, not just rough UX)

- [x] **Location filter appears inverted.** ~~Running the identical search scoped to "Turkey only"
      vs. "global" returned *more* results for the Turkey-only scope than the global scope —
      opposite of expected.~~ **Root cause found and fixed (2026-08-22).** Not a location-matching
      bug — `filter.py`'s `max_candidates` cap (the number of candidates that get AI-reviewed) was
      applied once across *all* locations pooled together and globally sorted by raw Exa relevance
      score, instead of per location. A campaign configured with e.g. `turkey` + `us` (what
      recruiters call "global" — see note below) had its Turkey and US candidates compete for the
      same shared review budget; if Exa happened to rank the other location's candidates higher,
      Turkey could lose most or all of its share, so a "global" run reviewed *fewer* Turkey
      candidates than a Turkey-only run got with the full budget to itself. Reproduced in a unit
      test: 5 Turkey + 5 US candidates, `max_candidates=3`, Turkey scored lower — old logic reviewed
      **0** Turkey candidates; fixed logic reviews 3 Turkey + 3 US (one budget per `search_bucket`,
      so adding a location only adds coverage, never steals it from another). Single-location
      campaigns are unaffected (verified — same top-N-by-score result as before).
      Real-world impact: checked all campaigns on disk — **17 of ~20** are multi-location
      (`turkey` + `us`/`ue`), so this was very likely happening broadly, not just in the reported
      case. Existing campaigns' `filtered_results.json` was generated under the old shared-budget
      logic; re-run the filter step on any campaign where location coverage matters to get results
      under the fixed logic.
      Side note for whoever owns campaign setup: there's no dedicated "global" mode — recruiters
      configure it themselves as a location list (e.g. `turkey` + `us`), so "global" in the feedback
      really meant "2 hardcoded regions," not worldwide. Out of scope for this fix, but worth knowing.
      — MLE feedback (Kagan)

- [ ] **Name-matching breaks the profile link for non-exact-match full names.** ~~Top-ranked
      candidate for the Chapter Lead search was displayed as "GS" with an 89% match, but the
      candidate's full name is actually "GUS" — the profile link didn't resolve~~. **Dropped for
      now (2026-08-22)** — "GS" was an abbreviation of the reviewer's own note, not necessarily a
      real system bug; deprioritized pending clearer repro. Revisit if it recurs with a concrete
      example.
      — Data & AI Chapter Lead feedback (Kagan)

- [x] **Auto-tagging applies NLP/LLM/Python tags independent of role content.** ~~Confirmed on two
      separate roles (Chapter Lead, GCP Data Engineer) — tags get attached regardless of whether
      the job description or filter criteria actually call for them, forcing manual correction
      every time.~~ **Root cause found and fixed (2026-08-22).** `feature_designer_agent.py` had a
      hardcoded fallback schema — "NLP/LLM Depth" (25 pts, keyed on NLP/LLM/BERT/GPT/RAG/NER) plus
      "Seniority" — that silently kicked in whenever the AI feature-design call failed or returned
      unparseable JSON (any transient timeout/rate-limit/malformed-output). Because
      `_load_or_build_feature_schema` in `pipeline.py` caches whatever schema comes back to disk and
      reuses it for every candidate in that campaign, a single failed call permanently locked the
      *entire* campaign into NLP-biased scoring — exactly matching "NLP-heavy candidates surfaced
      with no NLP requirement" and "NLP/LLM/Python tags added regardless of role content."
      Fix: (1) `JsonAgent.call_json` now retries once before giving up, cutting how often the
      fallback fires at all; (2) the fallback itself is now role-agnostic ("Filter Criteria Match" +
      "Seniority", no hardcoded NLP/LLM keywords) and self-flagged (`fallback: true`); (3)
      `pipeline.py` no longer caches a fallback schema to disk, so the next run retries proper
      AI-driven design instead of being stuck. Verified with mocked-failure/mocked-recovery/caching
      unit tests (see commit). Still open: still no first-class control over the manual tag
      taxonomy itself (see "Tag taxonomy is too narrow" below) — this fix addresses the
      *auto*-tagging bias, not the manual tag list.
      — MLE feedback (Kagan): searched with no NLP requirement, got NLP-heavy candidates by default;
        manually changing the tag surfaced better-fitting candidates.
      — GCP Data Engineer feedback (Kagan): "NLP, LLM, and Python tags seem to get added by default
        regardless of role content."

---

## Transparency / explainability (recruiters don't trust or understand the scoring)

- [x] **Similarity/match score is a black box.** ~~Recruiters have no visibility into what drives
      the %~~ — **partially fixed 2026-08-22** (the "expose the scoring breakdown" half; the MC/SM
      exclusion investigation was dropped per instruction, not pursued).
      What was actually missing: the *data* to explain a score already existed end-to-end —
      `feature_designer_agent.py` generates a `name`/`description`/`reason` for every scoring
      feature, and `scoring_designer_agent.py` normalizes weights to a 0–100% split — but none of
      it ever reached the web app. The UI only ever showed a raw internal `feature_id` (naively
      humanized, e.g. `gcp_depth` → "Gcp Depth") next to a number, with no weight %, no description
      of what the feature measures, and no explanation of why it was chosen for this role. That's
      the actual "black box": not missing data, missing plumbing.
      Fix: added `GET /api/campaigns/{id}/pipeline/scoring-explainer`, which reads a campaign's
      `ranking_feature_schema.json` + `ranking_scoring_policy.json` and returns each feature's
      name/description/reason/weight-%, plus hard gates and score tiers. Wired into
      `CandidateDetailModal`: the feature-contribution buttons now show the real feature name and
      "N% of total score — <description>" instead of a humanized ID, and clicking into a feature
      shows its description and "why this feature" reasoning above the evidence. Hard gates (rules
      that can override the weighted score, e.g. location requirements) are now listed on the
      candidate detail panel instead of being invisible. As a bonus, if a campaign's feature schema
      ever falls back to the generic schema (see the auto-tagging fix above), that's now shown to
      the recruiter directly on the candidate panel instead of silently producing a plausible-
      looking but unexplained score.
      Verified: called the new endpoint directly against a real campaign (`mle-engineer`, 9
      features, 10 hard gates) — correct name/description/reason/weight_pct per feature; ownership
      check confirmed (a non-owning user gets 404, same as the rest of the API); frontend build
      passes.
      Not done: the MC/SM exclusion investigation (why two specific expected reference candidates
      never appeared in a past search) — user said to drop this for now.
      — Data & AI Chapter Lead feedback (Kagan)

- [x] **"Target Profiles" parameter has no observable effect.** ~~Reviewer varied it up and down and
      saw no meaningful change in the result set~~ — **confirmed and fixed 2026-08-22.** It wasn't
      subtle: `target_profiles` was written to the `campaigns` table and never read by any pipeline
      script (`search.py`, `generate_queries.py`, `filter.py`, `pipeline.py` all had zero references
      to it) — a completely dead parameter, not a weak effect. Wired it to `filter.max_candidates`
      (how many search hits get AI-reviewed per location, which directly controls shortlist size —
      also the likely lever for the separate "shortlist volume too low" complaint below). Applied at
      two points: (1) `setup_pipeline_campaign` now reads the campaign's `target_profiles` and bakes
      it into `campaign.yaml` instead of a hardcoded 40; (2) editing a campaign's Target Profiles
      *after* pipeline setup now updates the existing `campaign.yaml` too (previously, editing a
      campaign never touched its pipeline directory at all, so post-setup changes silently had no
      effect either). Verified end-to-end: create → setup → yaml contains the chosen value; edit
      after setup → yaml value updates to match.
      — GCP Data Engineer feedback (Kagan)

- [x] **Example CV upload has no observable effect on shortlist ranking.** ~~Reviewer uploaded a
      sample CV expecting it to influence candidate matching/ranking and saw no discernible
      impact~~ — **confirmed and fixed 2026-08-22, root cause found.** The wiring to actually *use*
      a seed CV already existed in `generate_queries.py` (`_load_seed_cvs`), which reads PDFs from
      `campaign_dir/input/seed_cvs/` — but the upload endpoint only ever saved the file to a
      generic uploads folder and stored its filename on the `campaigns` row; it was never copied
      into the one folder the pipeline actually reads. Separately, and more surprising: the *edit*
      campaign form has always shown a CV upload field and sent it to the backend, but the
      `PUT /api/campaigns/{id}` endpoint never declared a `sample_cv` parameter at all — FastAPI
      silently drops unbound multipart fields, so re-uploading a CV via edit didn't even get saved,
      let alone reach the pipeline. Fixed both: `update_campaign` now accepts and saves the file
      (matching `create_campaign`'s existing logic, extracted into a shared helper), and both the
      initial pipeline setup and any later edit now copy the sample CV into
      `input/seed_cvs/<filename>.pdf` so query generation actually uses it. Verified end-to-end
      (create with CV → setup → file present in `seed_cvs/`; edit after setup with a new CV → new
      file appears in the existing pipeline's `seed_cvs/`).
      — GCP Data Engineer feedback (Kagan)

- [ ] **Terminology mismatch with recruiter workflows.** Platform vocabulary doesn't line up with
      day-to-day recruitment terminology; aligning the UI language to how recruiting teams actually
      talk would lower the learning curve.
      — MLE feedback (Kagan)

---

## Data quality / enrichment requests

- [x] **No way to exclude current ING employees from external search results.** ~~ING Hubs Türkiye
      employees keep showing up in results without a clear filter to exclude them.~~ **Fixed
      2026-08-22, at the AI-review stage (`filter.py`), which is where it was actually missing.**
      `generate_queries.py` already told the model to bake a "not working at ING" phrase into every
      *search query* — but that's just a soft hint to Exa's search ranking; nothing downstream ever
      actually checked whether a returned candidate currently works at ING before accepting them,
      which is exactly why Hubs employees kept slipping through despite the query-level hint.
      Added two layers at the point candidates get ACCEPT/REJECT/PENDING decided:
      1. The AI reviewer now also extracts `candidate_current_employer` from the actual profile
         text and is instructed with a standing hard rule (independent of each campaign's own
         filter criteria): if the real current employer is ING or a clear ING entity (ING Bank, ING
         Hubs, ING Groep, ING Direct, etc.), always REJECT.
      2. A deterministic regex backstop (`\bing\b`, whole-word match on the extracted employer
         field only) overrides the recommendation to REJECT even if the model's own judgment missed
         it — this is the actual fix for "the search criteria say don't match ING but it still let
         them through," since it no longer depends on the model reliably applying the rule every
         single time.
      Verified: false-positive check against employers merely *containing* the letters "ing"
      (Consulting, Engineering, Marketing, Banking, Boeing, Springer) — none flagged; true-positive
      check against ING/ING Bank/ING Hubs/ING Hubs Türkiye/ING Groep/ING Direct/ING Türkiye (mixed
      case) — all flagged; end-to-end test where the model itself mistakenly said ACCEPT for an
      "ING Hubs Türkiye" employee — backstop overrode it to REJECT; end-to-end test with a real
      external employer containing "ing" (Accenture Consulting) — stayed ACCEPT, no false positive.
      Not addressed by this fix: this only helps *future* pipeline runs — it doesn't retroactively
      re-score candidates already sitting in `filtered_results.json`/`ranked_results.json` for
      existing campaigns; re-run the filter step on a campaign to apply it there.
      — Chapter Lead Solution Architect feedback (Emine): 15 candidates on first pass, many were
        existing ING Hubs Türkiye staff; rephrasing the prompt to exclude active ING employees and
        simplifying criteria increased usable candidate count.
      — Data & AI Chapter Lead feedback (Kagan): a current ING Hubs Türkiye employee appeared in
        results, but similar-profile colleagues who'd be expected to co-appear did not — same
        underlying "how are internal employees handled" question.

- [ ] **ATS/Tracker history enrichment.** Recruiters want candidate cards enriched with past
      pipeline history where available: which roles a candidate was previously evaluated for, how
      many times they went through a process, and why they were rejected. Flagged as high-value for
      recruiter efficiency, not just a nice-to-have.
      — MLE feedback (Kagan)

- [x] **Tag taxonomy is too narrow.** ~~Manual tag editing is currently limited to 8 fixed
      options~~ — **investigated and fixed differently than assumed, 2026-08-22.** The 8 tags
      weren't a hardcoded limit — `skills` is a fully dynamic table (already had 33+ entries across
      real campaigns by the time this was checked). The real problem: tags only ever grow from
      whatever a recruiter happened to type by hand before, so a brand-new role type starts with
      zero relevant suggestions, and recruiters have no way to know what's "canonical" for their
      role vs. free-typing and risking typos. Fix: `import_ranked_results` now auto-populates the
      tag taxonomy from the campaign's own AI-designed scoring `capabilities` (e.g. "MLOps/LLMOps
      Production Engineering", "Turkey/Regional Connection" — already generated per-campaign by
      `feature_designer_agent.py`, previously unused for tagging) — so a new role type gets
      good, specific, non-typo tag suggestions automatically, with zero manual typing required.
      Verified end-to-end against a real campaign (`mle-engineer`): 7 new capability-derived tags
      added on import, re-running import doesn't duplicate them.
      — GCP Data Engineer feedback (Kagan)

- [x] **[New feature idea] English Language Confidence signal — built.** One 90%-match candidate
      for GCP Data Engineer had historically been rejected for English proficiency — a signal the
      match score didn't account for. Added exactly as proposed: the AI reviewer (`filter.py`) now
      also extracts an `english_confidence` (LOW/MEDIUM/HIGH) + short reason per candidate, based on
      whether the profile text itself is in English, explicit proficiency/certification mentions,
      and international study/work history. Explicitly a soft signal — verified it never affects
      ACCEPT/REJECT (a LOW-confidence candidate can still be ACCEPTed), and defaults safely to
      MEDIUM (never LOW) when there's no evidence either way, so absence of a signal doesn't read as
      a red flag. Wired end-to-end: new `candidates.english_confidence`/`_reason` DB columns
      (migration verified idempotent against a copy of the live DB, including recreating the
      `candidate_profile_summary` view, which — being a SQL view — doesn't pick up new table columns
      automatically), exposed via the candidate list/detail APIs, and shown as a color-coded badge
      (green/amber/red) with its reason on the candidate detail panel.
      Not done: "answers to English-related application questions" — no ATS/application-question
      data exists anywhere in this codebase to draw that signal from.
      — GCP Data Engineer feedback (Kagan)

---

## Performance / workflow friction

- [x] **Candidate generation is slow.** ~~Search/shortlist generation for DevOps Engineer role
      took noticeably long.~~ **Profiled and fixed 2026-08-23.** Pulled the actual per-stage log
      for that exact run: query generation 9s, search 35s, **filter (AI review) 4m 29s — 62% of
      total wall time**, ranking ~1m 55s, report <1s. Confirmed this pattern holds across all 22
      historical "full" runs — total wall time (6.5-10.6 min) doesn't scale with candidate count
      (4 candidates and 30 candidates both took ~8-9 min), which pointed at a fixed-concurrency
      bottleneck rather than a volume problem.
      Root cause: `filter.py` reviews candidates in parallel via `ThreadPoolExecutor`, but
      `max_workers` defaulted to **6** — checked every campaign.yaml in the repo, none override
      it. `ranking.pipeline`, by contrast, already defaults its concurrency to `batch_size` (50)
      and finishes in a fraction of the time despite doing comparable work. Since these calls are
      I/O-bound (waiting on the model, not CPU), concurrency scales close to linearly.
      Fix: raised `filter.py`'s default `max_workers` from 6 to 20 (still overridable per-campaign
      via `filter.max_workers` in campaign.yaml, or the pipeline's existing `--filter-max-workers`
      CLI flag — that override mechanism already existed, the default was just too conservative).
      Not done: didn't re-run a full campaign to measure the new wall-clock time directly (would
      cost real API spend) — the fix is a direct, low-risk concurrency change to an I/O-bound
      workload, not something that needed a live re-measurement to justify.
      — DevOps Engineer feedback (Emine)

- [x] **[Follow-up, not from original feedback] Token/cost usage was never tracked.** While
      profiling the above, found that `llm_provider.py` called the `claude` CLI without
      `--output-format json`, so cost/token data was discarded, not just unlogged — no historical
      run has ever had this data. Calibrated real per-call cost/latency with live test calls
      (~$0.01-0.025 per candidate review call, 7-16s each under realistic concurrency) to answer
      Osman's "what does this cost us" question with real numbers instead of a guess: a typical
      campaign (~69 total Claude calls: 40 filter + 25 ranking + 2 query-gen + 2 one-time
      schema/policy design) runs **~$0.70-$1.50 per full pipeline execution**.
      Added permanently: `llm_provider.call_model_text` now uses `--output-format json`, parses
      cost/token/duration from every call, and accumulates it thread-safely (filter.py and the
      ranking pipeline both call this concurrently). `run_campaign.py` writes the accumulated
      total to `data/usage_summary.json` at the end of every run and logs a summary line. Exposed
      via `GET /api/campaigns/{id}/pipeline/usage-summary` and a small card on the Pipeline Run
      Control panel showing cost/calls/tokens/errors for a campaign's most recent run.
      Verified end-to-end with a real (minimal-cost) pipeline run: usage correctly tracked,
      written to disk, and readable via the API — not just unit-tested in isolation. Also verified
      thread-safety under real concurrent calls (5-way parallel, no lost updates) and that
      timeouts/errors are counted without corrupting the running totals.
      Not covered: the Copilot/GitHub Models provider path (opt-in, rarely used — default is
      Claude) doesn't report usage the same way and wasn't instrumented.

- [ ] **Can't make "critical" edits once inside a generated result.** Reviewer wanted to go back
      into a shortlist/result after generation and make an update, but the UI didn't allow the
      specific kind of change needed (not further specified in the raw note — worth a follow-up
      question to Emine on what edit she was trying to make).
      — DevOps Engineer feedback (Emine)

---

## Volume/quality calibration

- [ ] **Shortlist volume was lower than expected for an easy-to-fill role.** GCP Data Engineer is
      characterized as a role with a comparatively large, easy-to-source market pool, but the
      shortlist returned fewer candidates than expected relative to that. Compare shortlist-size
      heuristics against role difficulty/market size — may be a generic "we always cap around N"
      behavior that doesn't adapt to how deep the actual talent pool is.
      — GCP Data Engineer feedback (Kagan)

---

## Suggested priority for next iteration

1. ~~Auto-tagging fix~~ — done 2026-08-22.
2. ~~Location filter bug (Turkey vs. global count inversion)~~ — done 2026-08-22.
3. ~~Exclude-current-ING-employee filter~~ — done 2026-08-22.
4. ~~Similarity score transparency~~ — done 2026-08-22 (MC/SM exclusion investigation dropped).
5. ~~Name-matching bug (GS/GUS profile link)~~ — dropped 2026-08-22, not a confirmed real bug.
6. Item 6 was split into narrower sub-tasks 2026-08-22 (see below); done in order:
   - ~~Target Profiles parameter~~ — done (was fully dead code; wired to `filter.max_candidates`).
   - ~~Example CV upload~~ — done (root cause: never copied to the one folder the pipeline reads;
     also fixed the edit-form upload path, which silently dropped the file entirely).
   - ~~English Language Confidence signal~~ — done (built as proposed, soft signal only).
   - ~~Tag taxonomy expansion~~ — done (auto-populate from AI-designed capabilities, not a bigger
     fixed list).
   - ~~Candidate generation is slow~~ — done 2026-08-23 (filter.py concurrency 6->20; also added
     LLM cost/token usage tracking as a follow-up, previously nonexistent).
   - Shortlist volume too low for easy-to-fill roles — not started; may already be partially
     addressed by the Target Profiles fix above (recruiters can now raise it directly per
     campaign), but not verified against the original GCP Data Engineer complaint specifically.
   - ATS/Tracker history enrichment — not started, needs to know what (if any) real ATS system
     this should pull from; no such integration exists in this codebase today.
   - Terminology mismatch — not started, needs concrete "call it X not Y" examples from a
     recruiter before it's actionable.
