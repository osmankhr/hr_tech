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

- [ ] **Location filter appears inverted.** Running the identical search scoped to "Turkey only"
      vs. "global" returned *more* results for the Turkey-only scope than the global scope —
      opposite of expected. Re-check the location filter logic (likely a scope/exclusion mix-up
      rather than a ranking issue, since the count itself is wrong, not just the ordering).
      — MLE feedback (Kagan)

- [ ] **Name-matching breaks the profile link for non-exact-match full names.** Top-ranked
      candidate for the Chapter Lead search was displayed as "GS" with an 89% match, but the
      candidate's full name is actually "GUS" — the profile link didn't resolve and the candidate
      had to be found via manual search instead. Check whatever name-normalization/matching step
      produces the display name and the profile URL; they're drifting out of sync for at least one
      real case.
      — Data & AI Chapter Lead feedback (Kagan)

- [ ] **Auto-tagging applies NLP/LLM/Python tags independent of role content.** Confirmed on two
      separate roles (Chapter Lead, GCP Data Engineer) — tags get attached regardless of whether
      the job description or filter criteria actually call for them, forcing manual correction
      every time. This is the same root cause behind two other complaints below (search prioritizing
      NLP-tagged candidates when NLP wasn't requested; recruiters having to hand-edit tags per
      campaign). Worth fixing once, centrally, rather than per-symptom.
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

- [ ] **No way to exclude current ING employees from external search results.** ING Hubs Türkiye
      employees keep showing up in results without a clear filter to exclude them. Add a search
      criterion like "exclude current ING employer" (phrased in feedback as "güncel şirketi ING
      olmayan"). One reviewer worked around this by adding "not currently at ING" directly into the
      free-text prompt and got a larger, cleaner result set — suggests the underlying filtering
      capability exists via prompt but isn't exposed as a first-class filter.
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

1. Auto-tagging fix (root cause behind three separate complaints above)
2. Location filter bug (Turkey vs. global count inversion — concrete, reproducible)
3. Exclude-current-ING-employee filter (clear, scoped ask; workaround already found via prompt)
4. Similarity score transparency + investigate the MC/SM exclusion case specifically
5. Name-matching bug (GS/GUS profile link) — likely narrow fix, but breaks trust when it happens
6. Everything else (tag taxonomy expansion, ATS enrichment, English confidence score, target
   profiles / example CV clarity, performance) — larger scope, sequence after the above.
