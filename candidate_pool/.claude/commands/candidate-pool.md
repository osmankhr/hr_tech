Run a candidate pool search-and-filter campaign.

## What this skill does

1. **Lists** available campaigns if no argument is given
2. **Runs** the full pipeline (generate queries → search → filter → report) for a given campaign
3. **Reports** results: candidate counts, output file locations

## Usage

```
/candidate-pool                                    # list available campaigns
/candidate-pool campaigns/my-campaign/             # run full pipeline
/candidate-pool campaigns/my-campaign/ --queries-only     # inspect generated queries
/candidate-pool campaigns/my-campaign/ --force-queries    # regenerate queries
/candidate-pool campaigns/my-campaign/ --search-only
/candidate-pool campaigns/my-campaign/ --filter-only
/candidate-pool campaigns/my-campaign/ --report-only
```

## Instructions for Claude

When invoked:

1. Parse the argument (if any) after `/candidate-pool`.

2. If no argument or the argument is "list":
   - Run: `ls campaigns/`
   - Display the available campaign directories.

3. If a campaign path is given:
   a. Verify the path exists and contains `campaign.yaml`.
   b. Check that `EXA_API_KEY` is set (`cat .env` or check environment).
   c. Run from this directory:
      ```
      python scripts/run_campaign.py <campaign_path> [flags]
      ```
   d. Stream the log output to the user.
   e. After completion, show:
      - Number of candidates found per location
      - Number accepted / rejected / pending
      - Paths to output files (shortlist.json, CSV, Excel)

4. If the user asks to **create a new campaign**:
   a. Ask for: campaign name, target locations (with optional hints), and filtering criteria.
      No search queries needed — Claude generates them automatically.
   b. Create the campaign folder: `campaigns/<name>_<YYYY-MM-DD>/`
   c. Copy the structure from `campaigns/example_2026-06-09/`
   d. Fill in `campaign.yaml` (locations + hints), `input/job_description.md`, `input/filter_criteria.md`
   e. Ask if the user wants to add seed CVs to `input/seed_cvs/` (PDFs of ideal candidates)

## Prerequisites

- `EXA_API_KEY` set in `.env`
- `claude` CLI on PATH (for headless query generation and filtering)
- Dependencies installed: `uv sync`
