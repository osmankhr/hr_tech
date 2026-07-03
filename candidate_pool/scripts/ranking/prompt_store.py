"""Prompt templates for ranking agents.

Prompts can be overridden via config['ranking']['prompts'] with file paths.
"""
from __future__ import annotations

from pathlib import Path

DEFAULT_PROMPTS: dict[str, str] = {
    "feature_designer_system": (
    "You are an expert hiring system designer. "
    "Your task is to transform a job description and filtering criteria into a structured, "
    "measurable, and role-relevant set of candidate evaluation features. "
    "The system must work across different roles and industries. "
    "You must respond ONLY with a valid JSON object - no markdown, no explanations."
    ),
    "feature_designer_user": """Job Description:
{job_description}

Filter Criteria:
{filter_criteria}

Role Context:
The role may belong to any domain (e.g., engineering, data, product, marketing, operations).
All reasoning must adapt to the given job description without assuming a fixed domain.

Task:
1. Summarize 5-7 capability dimensions required by this role.
2. Define 6-{max_features} measurable ranking features from these dimensions.
3. Each feature must be measurable from candidate profile text and must avoid sensitive/bias signals.

Return JSON exactly with this shape:
{{
  "capabilities": ["..."],
  "features": [
    {{
      "id": "snake_case_id",
      "name": "Human readable",
      "description": "...",
      "reason": "Why this matters for this JD",
      "value_type": "numeric|binary|categorical",
      "max_points": 0,
      "extraction_logic": ["keyword/pattern/rule", "..."],
      "evidence_examples": ["..."]
    }}
  ],
  "notes": ["..."]
}}

Constraints:
- Keep features auditable and job-specific.
- Prefer directly demonstrated skills, responsibilities, and impact over indirect proxies.
- max_points must be positive integers.
- id values must be unique.
""",
    "scoring_designer_system": (
        "You are an expert hiring evaluator designing a fair, role-relevant, and explainable scoring system. "
        "Your goal is to assign weights and scoring rules to features based on the provided job description and filtering criteria. "
        "The system must be generalizable across different roles and industries. "
        "You must respond ONLY with a valid JSON object - no markdown, no explanations."
    ),
    "scoring_designer_user": """Job Description:
{job_description}

Filter Criteria:
{filter_criteria}

Role Context:
The role may belong to any domain (e.g., engineering, data, product, marketing, operations).
All reasoning must adapt to the given job description without assuming a fixed domain.

Feature Schema (JSON):
{feature_schema_json}

Task:
Design a SCORING SYSTEM using the provided features.

Return JSON exactly with this shape:
{{
  "weights": {{
    "feature_name": number
  }},
  "scoring_rules": {{
    "feature_name": {{
      "min": 0,
      "max": number,
      "rules": [
        "clear rule describing how scores are assigned"
      ]
    }}
  }},
  "hard_gates": {{
    "must_have": ["explicit required conditions"],
    "reject_if": ["conditions that trigger rejection"]
  }},
  "normalization": {{
    "method": "weighted_sum",
    "notes": "how final score is computed"
  }},
  "sanity_checks": [
    "weights sum to 100",
    "weights reflect role priorities",
    "no single feature dominates unfairly",
    "rules are measurable from candidate data"
  ]
}}

Constraints:
- Assign a weight to each feature (total must equal 100).
- Weights must reflect the importance of features for THIS specific role.
- Define HARD GATES using filtering criteria.
- Prioritize job-relevant skills, experience, and responsibilities over proxies.
- Avoid overweighting generic proxies such as education prestige, company name, or years alone.
- Ensure the system is fair, explainable, and transferable to different roles.

Think step-by-step internally:
1. Identify key success factors from the job description.
2. Map those to the most relevant features.
3. Assign higher weights to features most critical for success.
4. Translate filtering criteria into strict gates.
5. Ensure balance and fairness.
""",
    "candidate_scorer_system": (
        "You are a recruitment evaluation assistant. "
        "Your task is to evaluate candidates objectively using a predefined scoring system. "
        "You must rely only on evidence present in the candidate profile. "
        "You must respond ONLY with a valid JSON object - no markdown, no explanations."
    ),
    "candidate_scorer_user": """Candidate Profile (JSON):
{candidate_json}

Role Context:
The role may belong to any domain (e.g., engineering, data, product, marketing, operations).
All reasoning must adapt to the given job description without assuming a fixed domain.

Feature Schema (JSON):
{feature_schema_json}

Scoring Policy (JSON):
{scoring_policy_json}

Task:
Evaluate this candidate feature-by-feature.

Return JSON exactly with this shape:
{{
  "feature_assessments": [
    {{
      "feature_id": "...",
      "raw_points": 0,
      "max_points": 0,
      "confidence": "HIGH|MEDIUM|LOW",
      "evidence": ["exact snippets or compact quotes"],
      "notes": "..."
    }}
  ],
  "gate_flags": [
    {{"gate_id": "...", "triggered": true, "reason": "..."}}
  ],
  "summary": "2-3 sentence explanation"
}}

Constraints:
- Use only explicit profile evidence.
- feature_assessments must include all feature ids from the feature schema.
- raw_points must be between 0 and max_points.
- Do not assume domain-specific knowledge unless explicitly stated.
""",
}


class PromptStore:
    """Load prompt templates with optional file-based overrides."""

    def __init__(self, campaign_dir: Path, prompt_cfg: dict[str, str] | None = None) -> None:
        self.campaign_dir = campaign_dir
        self.prompt_cfg = prompt_cfg or {}

    def get(self, key: str) -> str:
        override_path = self.prompt_cfg.get(key)
        if override_path:
            p = Path(override_path)
            if not p.is_absolute():
                p = self.campaign_dir / p
            if p.exists():
                return p.read_text()

        default_override = self.campaign_dir / "input" / "ranking_prompts" / f"{key}.md"
        if default_override.exists():
            return default_override.read_text()

        if key not in DEFAULT_PROMPTS:
            raise KeyError(f"Unknown prompt key: {key}")
        return DEFAULT_PROMPTS[key]
