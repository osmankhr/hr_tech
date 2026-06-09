# Candidate Pool

A generalizable pipeline for candidate discovery: uses Claude (headless) to generate search queries from your job description, searches [Exa.ai](https://exa.ai) for matching people, then uses Claude again to filter results against plain-language criteria.

**Pipeline:** generate queries → search → filter → report

## Structure

```
candidate_pool/
├── scripts/
│   ├── run_campaign.py       # Orchestrator — runs all phases
│   ├── generate_queries.py   # Claude headless query generation
│   ├── search.py             # Exa.ai search (parameterized)
│   ├── filter.py             # Claude headless AI filtering
│   └── report.py             # Excel / CSV / JSON output
└── campaigns/
    └── <campaign_name>/
        ├── campaign.yaml         # Config: locations, model, limits (no queries needed)
        ├── input/
        │   ├── job_description.md    # Role description (required)
        │   ├── filter_criteria.md    # Plain-language filtering rules for Claude
        │   └── seed_cvs/             # Optional: PDF CVs of ideal candidates
        │       └── example_cv.pdf
        ├── data/                 # Created at runtime
        │   ├── generated_queries.yaml   # Auto-generated, inspect/edit freely
        │   ├── <location>/raw_results.json
        │   └── filtered_results.json
        ├── output/               # Created at runtime
        │   ├── shortlist.json    # All fields preserved for downstream scoring
        │   ├── shortlist_YYYYMMDD.csv
        │   └── shortlist_YYYYMMDD.xlsx
        └── logs/
```

## Setup

```bash
cd candidate_pool
cp .env.example .env
# Add your EXA_API_KEY to .env
uv sync
```

## Running a campaign

```bash
# Full pipeline (generate queries → search → filter → report)
python scripts/run_campaign.py campaigns/example_2026-06-09/

# Individual phases
python scripts/run_campaign.py campaigns/example_2026-06-09/ --queries-only   # inspect generated queries
python scripts/run_campaign.py campaigns/example_2026-06-09/ --search-only
python scripts/run_campaign.py campaigns/example_2026-06-09/ --filter-only
python scripts/run_campaign.py campaigns/example_2026-06-09/ --report-only

# Regenerate queries even if cached
python scripts/run_campaign.py campaigns/example_2026-06-09/ --force-queries
```

Or use the Claude Code skill: `/candidate-pool campaigns/example_2026-06-09/`

## Creating a new campaign

1. Copy the example: `cp -r campaigns/example_2026-06-09 campaigns/my_role_2026-06-10`
2. Edit `campaign.yaml` — set your locations and hints (no queries needed)
3. Edit `input/job_description.md` and `input/filter_criteria.md`
4. Optionally add PDF CVs of ideal candidates to `input/seed_cvs/`
5. Run: `python scripts/run_campaign.py campaigns/my_role_2026-06-10/`

Queries are generated automatically from your input files. After `--queries-only` you can review and edit `data/generated_queries.yaml` before running the search.

## campaign.yaml reference

```yaml
name: "Campaign Name"
locations:
  - name: turkey
    hint: "Focus on Turkey-based professionals"   # optional
  - name: us
    hint: "Focus on Turkish diaspora abroad"      # optional
search:
  num_queries_per_location: 6   # Claude generates this many queries per location
  num_results_per_query: 30
  category: people
  contents:
    text: true
    highlights:
      num_sentences: 10
      highlights_per_url: 3
query_generation:
  model: claude-sonnet-4-5
filter:
  max_candidates: 100   # top-N by Exa score sent to Claude
  model: claude-sonnet-4-5
dedup:                  # optional
  existing_pool_path: "input/existing_pool.json"
output:
  formats: [excel, csv, json]
  keep_rejected: true
```

## How filtering works

For each candidate Claude receives:
- The full `filter_criteria.md` as instructions
- A candidate summary (URL, title, location, highlights, text excerpt up to 3 000 chars)

Claude returns a structured decision:
```json
{
  "recommendation": "ACCEPT | REJECT | PENDING",
  "confidence": "HIGH | MEDIUM | LOW",
  "key_strength": "...",
  "main_concern": "...",
  "reasoning": "..."
}
```

The `shortlist.json` output preserves **all Exa fields** plus the AI review, so it can be fed directly into a downstream CV scoring task.

## Dependencies

- `EXA_API_KEY` — [exa.ai](https://exa.ai) API key
- `claude` CLI — Claude Code must be installed and authenticated
