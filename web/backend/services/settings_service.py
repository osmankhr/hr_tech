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


def _get_global_contacted_file() -> Path | None:
    """Locate the current global contacted candidates spreadsheet if present."""
    env_path = os.environ.get("CONTACTED_CANDIDATES_PATH")
    if env_path:
        p = Path(env_path).resolve()
        if p.exists() and p.is_file():
            return p

    candidates = [
        core.config.GLOBAL_CONTACTED_DIR / "contacted_candidates.xlsx",
        core.config.GLOBAL_CONTACTED_DIR / "contacted_candidates.xls",
        core.config.GLOBAL_CONTACTED_DIR / "contacted_candidates.csv",
        core.config.GLOBAL_CONTACTED_DIR / "contacted.xlsx",
        core.config.GLOBAL_CONTACTED_DIR / "contacted.csv",
    ]
    for p in candidates:
        if p.exists() and p.is_file():
            return p
    return None


def get_contacted_candidates_status() -> dict:
    """Return status and metadata about the company-wide contacted candidates list."""
    from datetime import datetime, timezone

    file_path = _get_global_contacted_file()
    if not file_path:
        return {
            "configured": False,
            "filename": None,
            "file_size_bytes": 0,
            "updated_at": None,
            "total_names": 0,
            "total_urls": 0,
            "comparison_report_available": core.config.COMPARISON_REPORT_XLSX.exists(),
            "comparison_report_filename": (
                core.config.COMPARISON_REPORT_XLSX.name
                if core.config.COMPARISON_REPORT_XLSX.exists()
                else None
            ),
        }

    total_names = 0
    total_urls = 0
    try:
        scripts_dir = str(core.config.CANDIDATE_POOL_ROOT / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from contacted_candidates import ContactedCandidatesStore

        store = ContactedCandidatesStore(file_path)
        total_names = len(store.contacted_names)
        total_urls = len(store.contacted_urls)
    except Exception as e:
        logger.warning("Could not parse contacted file %s: %s", file_path, e)

    stat = file_path.stat()
    return {
        "configured": True,
        "filename": file_path.name,
        "file_size_bytes": stat.st_size,
        "updated_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        "total_names": total_names,
        "total_urls": total_urls,
        "comparison_report_available": core.config.COMPARISON_REPORT_XLSX.exists(),
        "comparison_report_filename": (
            core.config.COMPARISON_REPORT_XLSX.name
            if core.config.COMPARISON_REPORT_XLSX.exists()
            else None
        ),
    }


def save_global_contacted_file(file_obj, filename: str) -> dict:
    """Safely write an uploaded Excel or CSV contacted candidates list."""
    import re
    from fastapi import UploadFile

    if not filename:
        raise HTTPException(status_code=400, detail="Missing filename")

    raw_name = Path(filename).name
    safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", raw_name)
    ext = Path(safe_name).suffix.lower()
    if ext not in (".xlsx", ".xls", ".csv"):
        raise HTTPException(
            status_code=400,
            detail="Unsupported format. Only Excel (.xlsx, .xls) and CSV (.csv) files are allowed.",
        )

    core.config.GLOBAL_CONTACTED_DIR.mkdir(parents=True, exist_ok=True)
    target_path = (core.config.GLOBAL_CONTACTED_DIR / f"contacted_candidates{ext}").resolve()

    MAX_BYTES = 25 * 1024 * 1024  # 25 MB limit
    size = 0

    # Clean up any existing alternative extensions to avoid stale files
    for old_ext in (".xlsx", ".xls", ".csv"):
        (core.config.GLOBAL_CONTACTED_DIR / f"contacted_candidates{old_ext}").unlink(missing_ok=True)

    with open(target_path, "wb") as buffer:
        while True:
            chunk = file_obj.read(8192)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_BYTES:
                buffer.close()
                target_path.unlink(missing_ok=True)
                raise HTTPException(status_code=400, detail="File exceeds 25 MB size limit")
            buffer.write(chunk)

    # Validate file by attempting to parse candidates from it
    try:
        scripts_dir = str(core.config.CANDIDATE_POOL_ROOT / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from contacted_candidates import ContactedCandidatesStore

        store = ContactedCandidatesStore(target_path)
        if store.is_empty():
            target_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=400,
                detail="No candidate names or URLs could be identified in the uploaded file. Please check column headers.",
            )
    except HTTPException:
        raise
    except Exception as e:
        target_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Failed to parse file: {e}")

    # Set environment variable so every campaign pipeline execution uses it
    os.environ["CONTACTED_CANDIDATES_PATH"] = str(target_path)
    return get_contacted_candidates_status()


def delete_global_contacted_file() -> dict:
    """Remove all global contacted candidates spreadsheets."""
    removed = False
    for ext in (".xlsx", ".xls", ".csv"):
        p = core.config.GLOBAL_CONTACTED_DIR / f"contacted_candidates{ext}"
        if p.exists():
            p.unlink(missing_ok=True)
            removed = True
    os.environ.pop("CONTACTED_CANDIDATES_PATH", None)
    return get_contacted_candidates_status()

