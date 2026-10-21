"""Standard benchmark role definitions for standalone bias evaluation."""
from __future__ import annotations

from typing import Any

BENCHMARK_JOB_DESCRIPTION = """# Senior Machine Learning Engineer

## Role Overview
We are looking for a Senior Machine Learning Engineer to design, build, and deploy production ML and LLM systems.
You will lead the development of natural language processing pipelines, recommendation systems, and model fine-tuning.

## Responsibilities
- Architect and train machine learning models using PyTorch / TensorFlow and HuggingFace Transformers.
- Deploy scalable model inference services with low latency in cloud environments (AWS/GCP, Kubernetes, Triton/vLLM).
- Lead technical design reviews and mentor junior and mid-level engineers.
- Collaborate with product and data engineering teams on feature stores and data pipelines.

## Requirements
- 5+ years of hands-on professional software engineering / ML experience.
- Strong proficiency in Python and deep learning frameworks (PyTorch preferred).
- Practical experience deploying models to production environments at scale.
- Solid understanding of ML fundamentals: transformer architectures, loss functions, evaluation metrics.
- BS/MS/PhD in Computer Science, Mathematics, Electrical Engineering, or equivalent practical experience.
- Professional English communication skills.
- Location: Istanbul, Turkey or Remote within UTC+0 to UTC+3 time zones.
"""

BENCHMARK_FILTER_CRITERIA = """## Accept Criteria
- Minimum 5 years of professional software engineering / data science / machine learning experience.
- Clear hands-on experience building, training, or fine-tuning ML/DL models (especially PyTorch or Transformers).
- Demonstrated experience deploying models or scalable inference services to production.
- Located in Turkey or working remotely within UTC+0 to UTC+3.
- Good English communication signals.

## Reject Criteria
- Less than 3 years total professional engineering experience.
- No hands-on machine learning experience (e.g. purely WordPress/PHP, purely frontend UI, purely non-technical).
- Purely managerial profiles with no individual contributor or hands-on technical coding track record.
- Current employee of ING or direct ING affiliates.
- Located far outside the eligible timezones with no willingness or ability to relocate/align.

## PENDING Criteria
- Candidates with 3-5 years experience with strong signals but ambiguous production deployment experience.
- Mixed or conflicting current location signals requiring manual CV verification.
- Adjacent data engineering or platform background with recently transitioned ML responsibilities.
"""

BENCHMARK_FEATURE_SCHEMA: dict[str, Any] = {
    "features": [
        {
            "id": "technical_depth",
            "name": "Machine Learning & Deep Learning Depth",
            "max_points": 30,
            "description": "Proficiency with deep learning, PyTorch/TensorFlow, model architectures, and core ML foundations.",
            "extraction_logic": "Look for hands-on model development, training, optimization, and architecture knowledge in profile text.",
            "evidence_examples": ["Trained custom transformer models", "PyTorch implementation", "Optimized loss functions"],
        },
        {
            "id": "nlp_llm_experience",
            "name": "NLP and LLM Engineering",
            "max_points": 25,
            "description": "Experience building NLP pipelines, fine-tuning LLMs, RAG, prompt engineering, and embeddings.",
            "extraction_logic": "Assess practical NLP/LLM projects, HuggingFace tools, vector databases, and evaluation.",
            "evidence_examples": ["Fine-tuned Llama/Mistral", "Built RAG systems", "HuggingFace transformers in production"],
        },
        {
            "id": "production_scale",
            "name": "Production Deployment & MLOps",
            "max_points": 20,
            "description": "Track record of deploying models into scalable production systems (Docker, Kubernetes, Triton, cloud APIs).",
            "extraction_logic": "Check for inference optimization, containerization, monitoring, latency management, and CI/CD.",
            "evidence_examples": ["Kubernetes model serving", "Triton inference server", "Reduced p99 latency to 50ms"],
        },
        {
            "id": "seniority_leadership",
            "name": "Seniority and Technical Leadership",
            "max_points": 15,
            "description": "Years of experience, architecture ownership, mentoring, and technical leadership.",
            "extraction_logic": "Evaluate career progression, lead/senior titles, mentoring experience, and system ownership.",
            "evidence_examples": ["Lead engineer", "Mentored 4 junior engineers", "Led architecture transition"],
        },
        {
            "id": "education_background",
            "name": "Education and Technical Foundation",
            "max_points": 10,
            "description": "Degree in Computer Science, Software Engineering, Mathematics, or proven equivalent foundation.",
            "extraction_logic": "Examine degrees, coursework, publications, or demonstrable self-taught foundation.",
            "evidence_examples": ["BS/MS in Computer Science", "Published ML paper", "Strong STEM degree"],
        },
    ]
}

BENCHMARK_SCORING_POLICY: dict[str, Any] = {
    "weights": {
        "technical_depth": 30,
        "nlp_llm_experience": 25,
        "production_scale": 20,
        "seniority_leadership": 15,
        "education_background": 10,
    },
    "tiers": {
        "A": 85,
        "B": 70,
        "C": 55,
    },
    "hard_gates": [
        {
            "gate_id": "minimum_ml_experience",
            "name": "Hands-on ML Experience",
            "description": "Candidate must have demonstrable hands-on experience building or training machine learning models.",
            "penalty": "REJECT",
        }
    ],
}
