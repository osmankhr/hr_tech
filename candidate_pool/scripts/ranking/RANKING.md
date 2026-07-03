# Ranking Pipeline Documentation

This document explains the ranking pipeline under `scripts/ranking`, including:
- End-to-end flow
- Agent inputs/outputs
- Deterministic manual grading formula
- Produced files and JSON schemas
- How to run ranking only

## 1. Purpose

The ranking pipeline scores candidates in two layers:
1. Agentic design and extraction
- Design features from job context
- Design scoring policy from features
- Extract per-candidate feature assessments
2. Deterministic manual grading
- Apply weighted scoring math consistently across all candidates

This creates a transparent and reproducible ranking while keeping role adaptation dynamic.

## 2. Main Modules

- `pipeline.py`: orchestrates full ranking run
- `agents/feature_designer_agent.py`: builds feature schema
- `agents/scoring_designer_agent.py`: builds scoring policy
- `agents/candidate_scorer_agent.py`: scores each candidate against schema
- `manual_grader.py`: deterministic final scoring
- `prompt_store.py`: default prompts and campaign-level prompt overrides
- `utils/json_utils.py`: JSON extraction and normalization helpers

## 3. End-to-End Flow

1. Load candidates from ranking input JSON list
2. Load job description and filter criteria markdown
3. Build or load cached feature schema
4. Build or load cached scoring policy
5. For each candidate:
- Agent computes feature assessments and gate flags
- Manual grader computes final score and category
6. Sort by manual score descending
7. Write outputs (`ranked_results.json`, `ranking_summary.json`)

## 4. Configuration (campaign.yaml)

The pipeline reads `ranking` config from campaign file.

Example keys:

```yaml
ranking:
  enabled: true
  model: claude-sonnet-4-5
  input_path: data/filtered_results.json
  output_path: data/ranked_results.json
  summary_path: data/ranking_summary.json
  feature_schema_path: data/ranking_feature_schema.json
  scoring_policy_path: data/ranking_scoring_policy.json
  max_features: 10
  max_candidates: 200
  candidate_text_chars: 5000
  only_accepted: false
  force_redesign: false
```

Notes:
- `force_redesign: true` regenerates feature schema and scoring policy even if cache files exist.
- `only_accepted: true` restricts ranking to candidates with `ai_review.recommendation == "ACCEPT"`.

## 5. Agent I/O Contracts

### 5.1 Feature Designer Agent

Input:
- `job_description` (string)
- `filter_criteria` (string)
- `max_features` (int)

Output (normalized schema written to `ranking_feature_schema.json`):

```json
{
  "capabilities": ["..."],
  "features": [
    {
      "id": "snake_case_id",
      "name": "Human readable",
      "description": "...",
      "reason": "...",
      "value_type": "numeric|binary|categorical",
      "max_points": 10,
      "extraction_logic": ["..."],
      "evidence_examples": ["..."]
    }
  ],
  "notes": ["..."],
  "raw_response": {}
}
```

Normalization behavior:
- Missing or invalid `max_points` becomes `10`
- Duplicate/empty `id` values are repaired
- If response is unusable, fallback default features are generated

### 5.2 Scoring Designer Agent

Input:
- `job_description` (string)
- `filter_criteria` (string)
- `feature_schema` (object)

Output (written to `ranking_scoring_policy.json`):

```json
{
  "weights": {
    "feature_id": 0
  },
  "hard_gates": [
    {
      "id": "must_have_1",
      "description": "...",
      "trigger_rule": "...",
      "penalty": "REJECT",
      "group": "must_have"
    }
  ],
  "scoring_rules": {
    "feature_id": {
      "min": 0,
      "max": 10,
      "rules": ["..."]
    }
  },
  "normalization": {
    "method": "weighted_sum",
    "notes": "..."
  },
  "sanity_checks": ["..."],
  "tiers": {
    "A": 85,
    "B": 70,
    "C": 55
  },
  "notes": ["..."],
  "raw_response": {}
}
```

Normalization behavior:
- `weights` are forced to include all feature ids and sum to `100`
- If no valid weights, equal split is used
- `tiers` are clamped to `0..100` and kept monotonic (`A >= B >= C`)
- Supports both hard gate shapes:
1. List of gate objects
2. Object `{ "must_have": [...], "reject_if": [...] }` (converted to list)

### 5.3 Candidate Scorer Agent

Input per candidate:
- Candidate profile summary object:
  - `url`, `title`, `location`, `query`, `published_date`, `ai_review`, `highlights`, `text_excerpt`
- `feature_schema`
- `scoring_policy`

Output per candidate (stored under `ranking.agent` in ranked results):

```json
{
  "feature_assessments": [
    {
      "feature_id": "...",
      "raw_points": 7.5,
      "max_points": 10,
      "confidence": "HIGH|MEDIUM|LOW",
      "evidence": ["..."],
      "notes": "..."
    }
  ],
  "gate_flags": [
    {
      "gate_id": "...",
      "triggered": true,
      "reason": "..."
    }
  ],
  "summary": "...",
  "raw_response": {}
}
```

Normalization behavior:
- Guarantees one `feature_assessments` entry per schema feature
- Clamps `raw_points` to `[0, max_points]`
- Invalid fields are defaulted safely

## 6. Deterministic Manual Grading

Manual grading uses policy weights and candidate assessments to compute final score.

For each feature:

`contribution = weight * clamp(raw_points / max_points, 0, 1)`

Then:

`total = sum(contributions) + gate_penalty + ai_adjustment`

`manual_score = clamp(total, 0, 100)`

Category assignment:
- If any triggered gate has penalty `REJECT` -> `D`
- Else compare against policy tiers (`A`, `B`, `C`), else `D`

Default AI adjustment mapping:
- `ACCEPT`: `+3`
- `PENDING`: `0`
- `REJECT`: `-5`

These can be overridden with `ranking.ai_review_adjustments` in campaign config.

## 7. Output Files

Typical outputs under `<campaign_dir>/data`:

- `ranking_feature_schema.json`
- `ranking_scoring_policy.json`
- `ranked_results.json`
- `ranking_summary.json`

### 7.1 ranked_results.json structure

The file is a list of candidates. Each candidate keeps original fields and adds:

```json
{
  "ranking": {
    "manual": {
      "manual_score": 78.2,
      "category": "B",
      "feature_contributions": {
        "feature_id": 12.5
      },
      "gate_penalty": 0,
      "ai_adjustment": 3,
      "triggered_gates": [
        {
          "gate_id": "...",
          "penalty": "REJECT|MINUS_10|UNKNOWN",
          "reason": "..."
        }
      ],
      "rank": 1
    },
    "agent": {
      "feature_assessments": [
        {
          "feature_id": "...",
          "raw_points": 0,
          "max_points": 10,
          "confidence": "LOW",
          "evidence": [],
          "notes": "..."
        }
      ],
      "gate_flags": [
        {
          "gate_id": "...",
          "triggered": false,
          "reason": "..."
        }
      ],
      "summary": "..."
    }
  }
}
```

### 7.2 ranking_summary.json structure

```json
{
  "total_ranked": 200,
  "tiers": {
    "A": 10,
    "B": 45,
    "C": 88,
    "D": 57
  },
  "top_10": [
    {
      "rank": 1,
      "title": "...",
      "url": "...",
      "score": 92.1,
      "category": "A"
    }
  ]
}
```

## 8. Prompt Overrides

You can override prompt templates using campaign config:

```yaml
ranking:
  prompts:
    feature_designer_system: input/ranking_prompts/feature_designer_system.md
    feature_designer_user: input/ranking_prompts/feature_designer_user.md
    scoring_designer_system: input/ranking_prompts/scoring_designer_system.md
    scoring_designer_user: input/ranking_prompts/scoring_designer_user.md
    candidate_scorer_system: input/ranking_prompts/candidate_scorer_system.md
    candidate_scorer_user: input/ranking_prompts/candidate_scorer_user.md
```

Resolution order for each prompt key:
1. Path in `ranking.prompts`
2. `<campaign_dir>/input/ranking_prompts/<key>.md`
3. Built-in defaults in `prompt_store.py`

## 9. Run Commands

Ranking only (through orchestrator):

```bash
uv run python scripts/run_campaign.py campaigns/example_2026-06-09 --rank-only
```

Ranking only with forced schema/policy regeneration:

```bash
uv run python scripts/run_campaign.py campaigns/example_2026-06-09 --rank-only --force-ranking-redesign
```

Standalone ranking entrypoint:

```bash
uv run python scripts/rank.py campaigns/example_2026-06-09
uv run python scripts/rank.py campaigns/example_2026-06-09 --force-redesign
```

## 10. Current Behavior Summary

- Feature and scoring design run once per ranking execution (or are loaded from cache).
- Candidate scoring runs per candidate.
- Final score is deterministic once assessments are produced.
- This is currently a hybrid approach:
  - Agent-assisted extraction
  - Manual deterministic aggregation
