import os
from fastapi import APIRouter, Depends, HTTPException, Body
from core.config import CANDIDATE_POOL_ENV_PATH, ALLOWED_INTEGRATION_ENV_KEYS
from core.auth import get_current_user
from services.settings_service import (
    _get_candidate_pool_env_path,
    _validate_env_secret_value,
    _write_dotenv_updates,
    _build_integrations_status_response,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/integrations")
def get_integration_settings(current_user=Depends(get_current_user)):
    """Return masked configuration status for Kaggle, GitHub, Hugging Face, and Exa API keys."""
    return _build_integrations_status_response()


@router.put("/integrations")
def update_integration_settings(
    payload: dict = Body(...),
    current_user=Depends(get_current_user),
):
    """Update or clear platform API credentials in candidate_pool/.env and process environment."""
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload must be a JSON object")

    raw_credentials = payload.get("credentials") or {}
    raw_clear_keys = payload.get("clear_keys") or []

    if not isinstance(raw_credentials, dict):
        raise HTTPException(status_code=400, detail="credentials must be an object")
    if not isinstance(raw_clear_keys, list):
        raise HTTPException(status_code=400, detail="clear_keys must be a list")

    updates: dict[str, str] = {}
    for key, val in raw_credentials.items():
        if key not in ALLOWED_INTEGRATION_ENV_KEYS:
            raise HTTPException(status_code=400, detail=f"Unsupported credential key: {key}")
        if val is None:
            continue
        cleaned = _validate_env_secret_value(key, str(val))
        if cleaned:
            updates[key] = cleaned

    clear_keys: set[str] = set()
    for key in raw_clear_keys:
        if key not in ALLOWED_INTEGRATION_ENV_KEYS:
            raise HTTPException(status_code=400, detail=f"Unsupported credential key in clear_keys: {key}")
        clear_keys.add(key)

    _write_dotenv_updates(_get_candidate_pool_env_path(), updates, clear_keys)

    # Synchronize in-memory environment so subprocesses spawned by run_pipeline see changes immediately.
    for key in clear_keys:
        os.environ.pop(key, None)
    for key, val in updates.items():
        os.environ[key] = val

    return {
        "success": True,
        **_build_integrations_status_response(),
    }
