# Candidate Pool — Claude Token/Cost Reduction

Every `claude --print` subprocess call in this pipeline (`filter.py`, `generate_queries.py`,
`ranking/agents/agent_base.py`) is a one-shot text-in/JSON-out call that never uses tools. Without
extra flags, each call still paid for Claude Code's full default agentic system prompt + all
built-in tool definitions on top of the actual task prompt — measured at ~17,900 tokens of pure
overhead per call vs. ~170 tokens with `--tools "" --system-prompt "<minimal>"`. That overhead was
the dominant cost, not the candidate/job data, since filter.py and the ranking pipeline make one
subprocess call *per candidate* (up to `max_candidates`, commonly 40-200 per campaign).

## Done (2026-07-10)

- [x] **Strip unused system-prompt/tool overhead.** Added `--tools ""` and an explicit
      `--system-prompt` (replacing Claude Code's default) to every `claude` subprocess call in
      `filter.py`, `generate_queries.py`, and `ranking/agents/agent_base.py` (shared by
      `feature_designer_agent`, `scoring_designer_agent`, `candidate_scorer_agent`). No behavior
      change — verified JSON output/parsing still works via a live test run (2 candidates,
      `claude-haiku-4-5`) and `_extract_json` still handles markdown-fenced output. ~100x fewer
      fixed-overhead tokens per call, independent of model choice.

## Not done yet — next levers

- [ ] **Batch multiple candidates per call.** `filter.py` and `candidate_scorer_agent.py` currently
      make one `claude` call per candidate, re-sending the full filter criteria (filter.py) or
      feature schema + scoring policy (ranking) on every single call. Batching e.g. 8-10 candidates
      into one prompt (asking for a JSON array of per-candidate results) would amortize that fixed
      text across far fewer calls — the next-biggest lever after the overhead strip above. Needs a
      test run on a real campaign to confirm output quality/parsing holds up with multi-candidate
      responses (parsing gets more failure-prone: one bad candidate in a batch could corrupt/`null`
      the whole batch's JSON — needs a fallback path, e.g. per-candidate retry on batch parse
      failure).
- [ ] **Consider downgrading filter/ranking model from `claude-sonnet-5` to `claude-haiku-4-5`.**
      These are structured classification/extraction tasks (ACCEPT/REJECT/PENDING + location/title
      extraction; feature scoring against a fixed rubric), not open-ended reasoning — a smaller
      model is plausibly sufficient and meaningfully cheaper per token. Quality wasn't formally
      spot-checked against Sonnet outputs before switching campaign configs — do a side-by-side
      comparison on one campaign's candidates (same criteria, both models) before rolling out
      everywhere. Note: `query_generation`/feature-schema/scoring-policy design calls happen once
      per campaign (cached to disk after first run) — not worth downgrading those, the per-candidate
      calls are where the volume (and savings) is.
