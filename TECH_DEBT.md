# Technical Debt / Infra Follow-ups

Internal engineering/ops items — distinct from `FEEDBACK_FIXLIST.md`, which is
scoped to recruiter-reported feedback from `feedback.txt`. This file is for
things the team (Osman) flags directly about the system's own infrastructure.

- [ ] **Candidate ranking/filtering depends on n8n's Claude login profiles.**
      `candidate_pool/scripts/llm_provider.py` currently routes Claude CLI
      calls through `~/n8n-data/claude-profiles/{aiworkspacetr,richard}` (see
      `CLAUDE_PROFILE_CHAIN`, added 2026-09-07) — profiles that exist for and
      are owned by the separate n8n hackathon project, not hr_tech. This is an
      external dependency: if those profiles are renamed, re-logged-in,
      revoked, or the n8n project's needs change what's in them, hr_tech's
      ranking/filtering breaks for reasons invisible from inside this repo.
      hr_tech should have its own dedicated Claude CLI login(s)/profile(s),
      owned and documented in this project, instead of borrowing n8n's.
      — Osman, 2026-09-07 (raised right after the aiworkspacetr→richard
      fallback was added; the fallback is a working stopgap, not the fix for
      this)
