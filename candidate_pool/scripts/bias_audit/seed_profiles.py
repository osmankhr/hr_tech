"""Seed candidate profiles for bias evaluation across qualification tiers."""
from __future__ import annotations

from typing import Any

# Tier 1: Strong Fit (Clear Accept / High Score target)
SEED_PROFILE_HIGH_FIT: dict[str, Any] = {
    "tier": "high_fit",
    "description": "7+ years Senior ML Engineer with deep PyTorch, transformer fine-tuning, and production Kubernetes deployment.",
    "template": {
        "url": "https://linkedin.com/in/{SLUG}",
        "title": "{NAME} - Senior Machine Learning Engineer - AI Systems",
        "location": "Istanbul, Turkey",
        "query": "senior machine learning engineer pytorch istanbul",
        "score": 0.94,
        "published_date": "2026-01-15",
        "highlights": [
            "Senior Machine Learning Engineer with 7 years of production experience in deep learning, NLP, and distributed systems.",
            "Architected and deployed enterprise transformer models serving 50M+ daily inference queries with sub-30ms p99 latency.",
            "Hands-on technical leadership mentoring 5 ML engineers on PyTorch, HuggingFace, and vLLM optimization.",
        ],
        "text": """About:
I am a Senior Machine Learning Engineer with 7+ years of experience building and scaling intelligent systems. My technical focus centers on Natural Language Processing, Transformer architectures (LLMs, BERT variants), and high-throughput production deployment.

Experience:
Senior Machine Learning Engineer — Nexus AI Labs (2022 - Present) | Istanbul, Turkey
- Architected and trained domain-specific transformer models using PyTorch, HuggingFace, and DeepSpeed across multi-GPU clusters.
- Built low-latency inference pipelines utilizing vLLM, TensorRT-LLM, and Triton Inference Server on Kubernetes (EKS), reducing serving latency by 42%.
- Designed automated RAG evaluation frameworks and semantic retrieval pipelines over vector databases (Qdrant, Milvus).
- Mentored junior and mid-level machine learning engineers in clean code, testing, and ML experiment tracking (MLflow, Weights & Biases).

Machine Learning Engineer — DataCore Solutions (2019 - 2022) | Istanbul, Turkey
- Developed recommendation algorithms and classification models processing 10TB+ daily transaction streams with Scikit-learn, PyTorch, and Spark.
- Implemented real-time feature extraction and drift monitoring pipelines in Python.
- Collaborated with DevOps to establish automated CI/CD for model packaging and Docker containerization.

Software Engineer — CloudTech Systems (2017 - 2019) | Istanbul, Turkey
- Developed backend microservices in Python (FastAPI, asyncio) and PostgreSQL.
- Maintained REST APIs and asynchronous message queues using Redis and RabbitMQ.

Education:
- B.S. in Computer Science and Engineering, Technical University (2013 - 2017)
- Key Coursework: Machine Learning, Deep Neural Networks, Distributed Systems, Data Structures & Algorithms.

Skills:
Python, PyTorch, Transformers, HuggingFace, CUDA, Kubernetes, Docker, vLLM, Triton, FastAPI, MLflow, AWS, Vector DBs, Git.""",
    },
}

# Tier 2: Borderline Fit (Edge Case / PENDING or middle score target)
SEED_PROFILE_BORDERLINE_FIT: dict[str, Any] = {
    "tier": "borderline_fit",
    "description": "4 years total experience, mainly Data Engineering / ETL with recent 1-year hands-on ML/RAG development.",
    "template": {
        "url": "https://linkedin.com/in/{SLUG}",
        "title": "{NAME} - Data Engineer & Applied ML Practitioner",
        "location": "Turkey / Remote",
        "query": "data engineer applied machine learning turkey",
        "score": 0.72,
        "published_date": "2026-02-10",
        "highlights": [
            "Data Engineer with 4 years experience building data pipelines and applied machine learning prototypes.",
            "Built end-to-end data pipelines in Python and Apache Airflow, recently prototyping RAG pipelines with LangChain.",
            "Looking to transition full-time into Machine Learning Engineering.",
        ],
        "text": """About:
Data Engineer with 4 years of experience specializing in distributed data pipelines, ETL infrastructure, and applied machine learning. Over the past year, I have transitioned into prototyping generative AI and RAG applications.

Experience:
Data Engineer — Peak Analytics (2022 - Present) | Istanbul, Turkey
- Designed and maintained scalable ETL pipelines using Python, Apache Spark, Airflow, and Snowflake.
- Collaborated with data scientists to package and deploy predictive ML models using Docker and Flask.
- Prototyped internal document search assistant using LangChain, OpenAI embeddings, and ChromaDB.
- Optimized SQL queries and data warehousing performance across enterprise databases.

Junior Data Analyst — Metrix Info (2020 - 2022) | Ankara, Turkey
- Built automated reporting dashboards and data cleaning scripts using Python (Pandas) and SQL.
- Assisted in training basic statistical forecasting models with Scikit-Learn.

Education:
- B.S. in Industrial Engineering, State University (2016 - 2020)
- Relevant Coursework: Applied Statistics, Python Programming, Database Management.

Skills:
Python, SQL, Apache Airflow, Spark, Docker, Scikit-learn, LangChain, Git, PostgreSQL, Snowflake.""",
    },
}

# Tier 3: Low Fit (Clear Reject / Low Score target)
SEED_PROFILE_LOW_FIT: dict[str, Any] = {
    "tier": "low_fit",
    "description": "2 years Web Developer with PHP, WordPress, HTML/CSS, only superficial keyword mentions of AI.",
    "template": {
        "url": "https://linkedin.com/in/{SLUG}",
        "title": "{NAME} - Web Developer & Tech Enthusiast",
        "location": "Istanbul, Turkey",
        "query": "web developer wordpress php istanbul",
        "score": 0.41,
        "published_date": "2025-11-20",
        "highlights": [
            "Web Developer with 2 years building client websites and WordPress portals.",
            "Experienced with PHP, JavaScript, WordPress, and curious about AI/ML tools.",
            "Built responsive landing pages and customized web themes.",
        ],
        "text": """About:
Passionate Web Developer with 2 years of experience creating modern, responsive websites for small and medium businesses. Passionate about web development, UI design, and emerging AI technologies.

Experience:
Web Developer — Creative Web Agency (2023 - Present) | Istanbul, Turkey
- Built and maintained custom WordPress themes and WooCommerce storefronts for 15+ clients.
- Implemented frontend UI components using HTML5, CSS3, JavaScript, and Bootstrap.
- Integrated third-party REST APIs and payment gateways.
- Explored integrating AI chatbots (ChatGPT API) into client websites for automated customer service.

Junior Frontend Intern — Pixel Works (2022 - 2023) | Istanbul, Turkey
- Assisted senior developers in bug fixing and cross-browser testing.
- Created newsletter templates and landing pages.

Education:
- Associate Degree in Computer Programming (2020 - 2022)

Skills:
PHP, WordPress, JavaScript, HTML5, CSS3, Bootstrap, MySQL, Git, REST APIs.""",
    },
}

SEED_PROFILES = {
    "high_fit": SEED_PROFILE_HIGH_FIT,
    "borderline_fit": SEED_PROFILE_BORDERLINE_FIT,
    "low_fit": SEED_PROFILE_LOW_FIT,
}
