import sys
import os
import logging
from pathlib import Path
from fastapi import HTTPException
import core.config
from core.config import ALLOWED_INTEGRATION_ENV_KEYS

logger = logging.getLogger(__name__)

def _get_candidate_pool_env_path() -> Path:
    main_mod = sys.modules.get("main")
    if main_mod is not None and hasattr(main_mod, "CANDIDATE_POOL_ENV_PATH"):
        return getattr(main_mod, "CANDIDATE_POOL_ENV_PATH")
    return core.config.CANDIDATE_POOL_ENV_PATH

def _read_dotenv_dict(env_path: Path) -> dict[str, str]:
    """Parse key=value pairs from a .env file without executing or expanding shell expressions."""
    values: dict[str, str] = {}
    if not env_path.exists():
        return values

    try:
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
                val = val[1:-1]
            if key:
                values[key] = val
    except Exception:
        logger.exception("Failed to read .env file at %s", env_path)
    return values


def _mask_secret_value(key: str, raw_value: str) -> str:
    """Return a safe masked representation of a secret so raw API keys are never exposed via GET."""
    cleaned = (raw_value or "").strip()
    if not cleaned:
        return ""
    # KAGGLE_USERNAME is an account handle (non-secret identifier), safe to display to the user.
    if key == "KAGGLE_USERNAME":
        return cleaned
    if len(cleaned) <= 6:
        return "••••••••"
    return f"••••••••{cleaned[-4:]}"


def _validate_env_secret_value(key: str, value: str) -> str:
    """Validate an environment variable value to prevent newline/.env injection."""
    if not isinstance(value, str):
        raise HTTPException(status_code=400, detail=f"Invalid value type for {key}")
    if any(ch in value for ch in ("\n", "\r", "\x00")):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid control characters in {key}",
        )
    trimmed = value.strip()
    if len(trimmed) > 512:
        raise HTTPException(
            status_code=400,
            detail=f"{key} exceeds maximum allowed length (512 characters)",
        )
    return trimmed


def _write_dotenv_updates(
    env_path: Path,
    updates: dict[str, str],
    clear_keys: set[str],
) -> None:
    """Safely update or remove specific allowlisted keys in a .env file while preserving other lines."""
    env_path.parent.mkdir(parents=True, exist_ok=True)
    existing_lines = (
        env_path.read_text(encoding="utf-8").splitlines()
        if env_path.exists()
        else []
    )

    handled_keys: set[str] = set()
    new_lines: list[str] = []

    for raw_line in existing_lines:
        stripped = raw_line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, _, _ = stripped.partition("=")
            key = key.strip()
            if key in ALLOWED_INTEGRATION_ENV_KEYS:
                if key in clear_keys:
                    handled_keys.add(key)
                    continue
                if key in updates:
                    new_lines.append(f"{key}={updates[key]}")
                    handled_keys.add(key)
                    continue
        new_lines.append(raw_line)

    for key in ALLOWED_INTEGRATION_ENV_KEYS:
        if key in updates and key not in handled_keys and key not in clear_keys:
            new_lines.append(f"{key}={updates[key]}")

    content = "\n".join(new_lines)
    if content and not content.endswith("\n"):
        content += "\n"
    env_path.write_text(content, encoding="utf-8")


def _build_integrations_status_response() -> dict:
    """Build masked status payload for all supported platform integrations."""
    dotenv_vals = _read_dotenv_dict(_get_candidate_pool_env_path())
    keys_status = {}
    for key in ALLOWED_INTEGRATION_ENV_KEYS:
        raw_val = dotenv_vals.get(key) or os.environ.get(key) or ""
        raw_val = raw_val.strip()
        keys_status[key] = {
            "configured": bool(raw_val),
            "masked": _mask_secret_value(key, raw_val),
        }

    kaggle_official_ready = (
        keys_status["KAGGLE_API_TOKEN"]["configured"]
        or (
            keys_status["KAGGLE_USERNAME"]["configured"]
            and keys_status["KAGGLE_KEY"]["configured"]
        )
    )
    return {
        "keys": keys_status,
        "platforms": {
            "exa": {
                "ready": keys_status["EXA_API_KEY"]["configured"],
                "mode": "primary_search",
            },
            "kaggle": {
                "ready": kaggle_official_ready or keys_status["EXA_API_KEY"]["configured"],
                "official_api_configured": kaggle_official_ready,
                "exa_fallback_configured": keys_status["EXA_API_KEY"]["configured"],
            },
            "github": {
                "ready": True,
                "token_configured": keys_status["GITHUB_TOKEN"]["configured"],
            },
            "huggingface": {
                "ready": True,
                "token_configured": keys_status["HF_TOKEN"]["configured"],
            },
        },
    }
