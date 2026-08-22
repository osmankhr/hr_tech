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

- [ ] **Name-matching breaks the profile link for non-exact-match full names.** Top-ranked
      candidate for the Chapter Lead search was displayed as "GS" with an 89% match, but the
      candidate's full name is actually "GUS" — the profile link didn't resolve and the candidate
      had to be found via manual search instead. Check whatever name-normalization/matching step
      produces the display name and the profile URL; they're drifting out of sync for at least one
      real case.
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

- [ ] **Similarity/match score is a black box.** Recruiters have no visibility into what drives the
      %, and it's producing results that look wrong on inspection:
      - Chapter Lead search: top candidate scored 89% despite having no engineering background —
        higher than expected once the reviewer actually read the profile.
      - Same search: internal manager-based reference similarities were shown (UU 74%, MY 50%,
        ES 41%, OK 38%) but two people the reviewer expected to rank highly as reference points for
        this specific role — MC and SM — didn't appear in results at all.
      Needs: (1) expose the scoring breakdown (title match / skills / experience / org data weights)
      in the UI or an explain endpoint, (2) investigate specifically why MC and SM were excluded —
      that's a concrete, debuggable case, not just a vague "scores feel off" complaint.
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
4. Similarity score transparency + investigate the MC/SM exclusion case specifically
5. Name-matching bug (GS/GUS profile link) — likely narrow fix, but breaks trust when it happens
6. Everything else (tag taxonomy expansion, ATS enrichment, English confidence score, target
   profiles / example CV clarity, performance) — larger scope, sequence after the above.
