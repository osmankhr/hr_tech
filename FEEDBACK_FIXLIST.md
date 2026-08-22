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

- [ ] **"Target Profiles" parameter has no observable effect.** Reviewer varied it up and down and
      saw no meaningful change in the result set, and couldn't tell from the UI whether it affects
      how many candidates get scanned, how many get returned, or just how many are displayed. Either
      fix the parameter so it visibly does something, or document/label what it actually controls.
      — GCP Data Engineer feedback (Kagan)

- [ ] **Example CV upload has no observable effect on shortlist ranking.** Reviewer uploaded a
      sample CV expecting it to influence candidate matching/ranking and saw no discernible impact.
      Same ask as above: either wire it into the scoring path or make clear what it's currently
      used for.
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

- [ ] **Tag taxonomy is too narrow.** Manual tag editing is currently limited to 8 fixed options
      (A/B Testing, LLM, LLMOps, MLE, MLOps, NLP, Python, Analytics) — missing many skills that are
      critical for other role types, forcing free-text tag entry which is typo-prone and degrades
      search quality. Expand the taxonomy so common skills across role types have a canonical tag,
      and ideally auto-derive relevant tags from the job description / filter criteria at campaign
      creation time rather than requiring manual cleanup afterward (ties into the auto-tagging bug
      above).
      — GCP Data Engineer feedback (Kagan)

- [ ] **[New feature idea] English Language Confidence signal.** One 90%-match candidate for GCP
      Data Engineer had historically been rejected for English proficiency — a signal the current
      match score doesn't account for. Proposed: a "Low / Medium / High English Confidence" score
      derived from available signals (CV written entirely in Turkish, whether LinkedIn lists English
      and at what level, answers to English-related application questions, presence/absence of
      international study or work history). Explicitly framed as a soft risk signal for recruiters,
      not a hard English-level determination — should surface alongside the match score, not replace
      it.
      — GCP Data Engineer feedback (Kagan)

---

## Performance / workflow friction

- [ ] **Candidate generation is slow.** Search/shortlist generation for DevOps Engineer role took
      noticeably long. Worth profiling the pipeline for this role type to see if it's a
      query-volume issue, an external API bottleneck, or ranking-step latency.
      — DevOps Engineer feedback (Emine)

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
6. Everything else (tag taxonomy expansion, ATS enrichment, English confidence score, target
   profiles / example CV clarity, performance) — larger scope, sequence after the above.
