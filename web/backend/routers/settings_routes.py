import os
from fastapi import APIRouter, Depends, HTTPException, Body, UploadFile, File
from fastapi.responses import FileResponse
from core.config import (
    CANDIDATE_POOL_ENV_PATH,
    ALLOWED_INTEGRATION_ENV_KEYS,
    COMPARISON_REPORT_XLSX,
    COMPARISON_REPORT_CSV,
)
from core.auth import get_current_user
from services.settings_service import (
    _get_candidate_pool_env_path,
    _validate_env_secret_value,
    _write_dotenv_updates,
    _build_integrations_status_response,
    _get_global_contacted_file,
    get_contacted_candidates_status,
    save_global_contacted_file,
    delete_global_contacted_file,
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


@router.get("/contacted-candidates")
def get_contacted_candidates(current_user=Depends(get_current_user)):
    """Return status and summary for company-wide contacted candidates spreadsheet."""
    return get_contacted_candidates_status()


@router.post("/contacted-candidates")
def upload_contacted_candidates(
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
):
    """Upload and activate a company-wide contacted candidates Excel (.xlsx/.xls) or CSV."""
    if not file or not file.filename:
        raise HTTPException(status_code=400, detail="No file uploaded")
    return save_global_contacted_file(file.file, file.filename)


@router.delete("/contacted-candidates")
def delete_contacted_candidates(current_user=Depends(get_current_user)):
    """Remove the active company-wide contacted candidates list."""
    return delete_global_contacted_file()


@router.get("/contacted-candidates/download")
def download_contacted_candidates(current_user=Depends(get_current_user)):
    """Download the active company-wide contacted candidates spreadsheet."""
    file_path = _get_global_contacted_file()
    if not file_path or not file_path.exists():
        raise HTTPException(status_code=404, detail="No contacted candidates file uploaded")

    media_type = (
        "text/csv"
        if file_path.suffix.lower() == ".csv"
        else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    return FileResponse(
        path=str(file_path),
        filename=file_path.name,
        media_type=media_type,
    )


@router.get("/contacted-candidates/comparison-report")
def download_comparison_report(current_user=Depends(get_current_user)):
    """Download the latest HR vs AI review benchmark comparison report."""
    if COMPARISON_REPORT_XLSX.exists():
        return FileResponse(
            path=str(COMPARISON_REPORT_XLSX),
            filename=COMPARISON_REPORT_XLSX.name,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    if COMPARISON_REPORT_CSV.exists():
        return FileResponse(
            path=str(COMPARISON_REPORT_CSV),
            filename=COMPARISON_REPORT_CSV.name,
            media_type="text/csv",
        )
    raise HTTPException(
        status_code=404,
        detail="No comparison report generated yet. Run a campaign to evaluate contacted candidate hits.",
    )

