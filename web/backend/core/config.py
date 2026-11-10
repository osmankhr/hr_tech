from pathlib import Path
import os

BACKEND_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BACKEND_DIR / "hr_candidate_search_demo.db"
CANDIDATE_POOL_ROOT = BACKEND_DIR.parent.parent / "candidate_pool"
CANDIDATE_POOL_CAMPAIGNS_DIR = CANDIDATE_POOL_ROOT / "campaigns"
CANDIDATE_POOL_ENV_PATH = CANDIDATE_POOL_ROOT / ".env"

# Supported external community platforms that can be toggled per campaign alongside Exa search.
ALLOWED_COMMUNITY_PLATFORMS = ("github", "huggingface", "kaggle")
DEFAULT_ACTIVITY_DAYS = 180

# Explicit allowlist of environment variable keys manageable via /api/settings/integrations.
ALLOWED_INTEGRATION_ENV_KEYS = (
    "KAGGLE_API_TOKEN",
    "KAGGLE_USERNAME",
    "KAGGLE_KEY",
    "GITHUB_TOKEN",
    "HF_TOKEN",
    "EXA_API_KEY",
)
UPLOAD_DIR = BACKEND_DIR / "uploaded_cvs"
FRONTEND_DIST = BACKEND_DIR.parent / "frontend" / "dist"
MAX_WORKERS_CAP = 20

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

CORS_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "HR_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000,http://127.0.0.1:8000",
    ).split(",")
    if origin.strip()
]
