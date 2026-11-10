import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Core modules
from core.config import (
    BACKEND_DIR,
    DB_PATH,
    CANDIDATE_POOL_ROOT,
    CANDIDATE_POOL_CAMPAIGNS_DIR,
    CANDIDATE_POOL_ENV_PATH,
    ALLOWED_COMMUNITY_PLATFORMS,
    DEFAULT_ACTIVITY_DAYS,
    ALLOWED_INTEGRATION_ENV_KEYS,
    UPLOAD_DIR,
    FRONTEND_DIST,
    MAX_WORKERS_CAP,
    CORS_ORIGINS,
)
from core.database import (
    get_connection,
    ensure_pipeline_tables,
)
from core.auth import (
    public_user,
    get_current_user,
    require_admin,
    _get_current_user_from_raw_token,
    _get_owned_campaign,
)

# Services
from services.campaign_service import (
    _slugify,
    _build_location_filter_clause,
    is_ing_affiliated,
    _build_mandatory_criteria_clause,
    _parse_platforms_json,
    _validate_activity_days,
    _build_campaign_yaml,
    _strip_location_clause,
    _read_pipeline_config_files,
    _pipeline_results_summary,
    _extract_years_experience,
    _next_candidate_code,
    _candidate_status_from_review,
    _pipeline_stage_from_status,
    _build_csv_rows,
    _remove_pipeline_campaign_dir,
    _run_pipeline_in_background,
    _parse_template_locations,
    _save_uploaded_sample_cv,
    _sync_pipeline_config_for_campaign,
    _load_best_available_pipeline_candidates,
    _link_skill_names_to_campaign,
    SEARCH_CSV_EXCLUDED_FIELDS,
    RANKED_CSV_EXCLUDED_FIELDS,
)
from services.settings_service import (
    _read_dotenv_dict,
    _mask_secret_value,
    _validate_env_secret_value,
    _write_dotenv_updates,
    _build_integrations_status_response,
)

# Routers
from routers.auth_routes import (
    router as auth_router,
    create_user,
    signin,
    signout,
    me,
    list_users,
)
from routers.campaigns_routes import (
    router as campaigns_router,
    list_campaigns,
    list_active_campaigns,
    list_past_campaigns,
    create_campaign,
    get_campaign,
    update_campaign,
    delete_campaign,
    create_campaign_template,
    list_campaign_templates,
)
from routers.candidates_routes import (
    router as candidates_router,
    list_campaign_rankings,
    list_campaign_candidates,
    list_candidates,
    list_skills,
    refresh_candidates,
    get_candidate,
    update_candidate,
    get_candidate_activities,
    get_candidate_comments,
    add_candidate_comment,
)
from routers.pipeline_routes import (
    router as pipeline_router,
    _resolve_pipeline_dir,
    _resolve_ranked_results_artifact,
    _resolve_search_results_files,
    setup_pipeline_campaign,
    get_pipeline_config_versions,
    update_pipeline_config,
    list_pipeline_runs,
    stream_pipeline_events,
    run_pipeline,
    import_ranked_results,
    export_campaign_excel,
    get_scoring_explainer,
    get_usage_summary_endpoint,
    get_search_results_status,
    export_search_csv,
    get_ranked_results_status,
    export_ranked_csv,
)
from routers.settings_routes import (
    router as settings_router,
    get_integration_settings,
    update_integration_settings,
)

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_pipeline_tables()
    yield


# FastAPI Application Factory
app = FastAPI(
    title="AI HR Search API",
    description="Automated candidate sourcing, evaluation, and pipeline management backend",
    version="2.0.0",
    lifespan=lifespan,
)

# Cross-Origin Resource Sharing (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Mount Modular Feature Routers
app.include_router(auth_router)
app.include_router(campaigns_router)
app.include_router(candidates_router)
app.include_router(pipeline_router)
app.include_router(settings_router)

# Mount Frontend SPA Dist (Fallback Catch-All)
# nginx strips the public /hr prefix before proxying here, so this serves the
# built frontend at the app root both in production and in local development.
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
