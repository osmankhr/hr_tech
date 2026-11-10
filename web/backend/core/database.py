import sys
import sqlite3
import core.config

def _get_db_path():
    main_mod = sys.modules.get("main")
    if main_mod is not None and hasattr(main_mod, "DB_PATH"):
        return getattr(main_mod, "DB_PATH")
    return core.config.DB_PATH

def get_connection():
    """Create and configure a SQLite connection in WAL mode with foreign keys enabled."""
    conn = sqlite3.connect(_get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL lets readers proceed while a write is in progress instead of locking
    # the whole file (the default rollback-journal mode), which is what was
    # causing "database is locked" 500s under concurrent multi-user access.
    # This is a one-time, persistent, file-level setting; re-issuing it on
    # every connection is a cheap no-op once already in WAL mode.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def ensure_pipeline_tables():
    """Ensure all required pipeline, template, ranking, and versioning tables exist."""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS pipeline_campaign_configs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER NOT NULL UNIQUE,
            pipeline_dir TEXT NOT NULL,
            campaign_yaml_path TEXT NOT NULL,
            job_description_path TEXT NOT NULL,
            filter_criteria_path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS pipeline_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER NOT NULL,
            run_type TEXT NOT NULL CHECK(run_type IN ('full', 'queries', 'search', 'filter', 'rank', 'report', 'import')),
            status TEXT NOT NULL CHECK(status IN ('Queued', 'Running', 'Completed', 'Failed')),
            command TEXT,
            campaign_dir TEXT,
            artifact_path TEXT,
            error_message TEXT,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            created_by_user_id INTEGER,
            FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
            FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS candidate_rankings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER NOT NULL,
            candidate_id INTEGER NOT NULL,
            manual_score REAL,
            category TEXT,
            rank INTEGER,
            feature_contributions_json TEXT,
            gate_penalty REAL,
            ai_adjustment REAL,
            raw_agent_json TEXT,
            raw_manual_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (campaign_id, candidate_id),
            FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
            FOREIGN KEY (candidate_id) REFERENCES candidates(id) ON DELETE CASCADE
        );

        -- Full history of pipeline_campaign_configs snapshots. pipeline_campaign_configs itself
        -- stays a single current-pointer row per campaign (unchanged since its original design);
        -- this table only ever gets new rows appended, so no existing row/constraint has to
        -- change to add version history. The current version is always the one with the
        -- highest version_number for a campaign_id.
        CREATE TABLE IF NOT EXISTS pipeline_config_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER NOT NULL,
            version_number INTEGER NOT NULL,
            pipeline_dir TEXT NOT NULL,
            campaign_yaml_path TEXT NOT NULL,
            job_description_path TEXT NOT NULL,
            filter_criteria_path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE (campaign_id, version_number),
            FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS pipeline_campaign_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            template_name TEXT NOT NULL,
            pipeline_description TEXT,
            locations_json TEXT NOT NULL,
            job_description TEXT NOT NULL,
            filter_criteria TEXT NOT NULL,
            source_campaign_id INTEGER,
            created_by_user_id INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (source_campaign_id) REFERENCES campaigns(id) ON DELETE SET NULL,
            FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS idx_pipeline_runs_campaign ON pipeline_runs(campaign_id, started_at DESC);
        CREATE INDEX IF NOT EXISTS idx_candidate_rankings_campaign ON candidate_rankings(campaign_id, rank ASC);
        CREATE INDEX IF NOT EXISTS idx_pipeline_campaign_templates_owner ON pipeline_campaign_templates(created_by_user_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_pipeline_config_versions_campaign ON pipeline_config_versions(campaign_id, version_number DESC);
    """)

    # One-time backfill: every campaign configured before pipeline_config_versions existed gets
    # its current pipeline_campaign_configs row recorded as version 1. Safe to run on every
    # startup -- WHERE NOT IN skips campaigns that already have history.
    conn.execute("""
        INSERT INTO pipeline_config_versions (
            campaign_id, version_number, pipeline_dir,
            campaign_yaml_path, job_description_path, filter_criteria_path, created_at
        )
        SELECT campaign_id, 1, pipeline_dir, campaign_yaml_path, job_description_path,
               filter_criteria_path, created_at
        FROM pipeline_campaign_configs
        WHERE campaign_id NOT IN (SELECT campaign_id FROM pipeline_config_versions)
    """)

    # Backward-compatible columns for run summary metrics and template platform configs.
    for alter_sql in [
        "ALTER TABLE pipeline_runs ADD COLUMN accepted_candidates INTEGER",
        "ALTER TABLE pipeline_runs ADD COLUMN ranked_candidates INTEGER",
        "ALTER TABLE candidates ADD COLUMN english_confidence TEXT",
        "ALTER TABLE candidates ADD COLUMN english_confidence_reason TEXT",
        "ALTER TABLE pipeline_campaign_templates ADD COLUMN platforms_json TEXT",
        "ALTER TABLE pipeline_campaign_templates ADD COLUMN activity_days INTEGER",
    ]:
        try:
            conn.execute(alter_sql)
        except sqlite3.OperationalError:
            pass

    # candidate_profile_summary is a VIEW with a fixed column list baked in at CREATE time —
    # unlike a table, it doesn't pick up new candidates columns automatically, so it has to be
    # dropped and recreated whenever a column is added to candidates that the view should expose.
    conn.executescript("""
        DROP VIEW IF EXISTS candidate_profile_summary;

        CREATE VIEW candidate_profile_summary AS
        SELECT
            cand.id,
            cand.candidate_code,
            cand.full_name,
            cand.email,
            cand.current_title,
            cand.location,
            cand.source,
            cand.profile_url,
            cand.score,
            cand.status,
            cand.years_experience,
            cand.english_confidence,
            cand.english_confidence_reason,
            cand.last_updated,
            cand.notes,
            cand.first_contacted_at,
            cu.full_name AS created_by_name,
            uu.full_name AS updated_by_name,
            fu.full_name AS first_contacted_by_name,
            GROUP_CONCAT(DISTINCT s.name) AS skills
        FROM candidates cand
        LEFT JOIN users cu ON cu.id = cand.created_by_user_id
        LEFT JOIN users uu ON uu.id = cand.updated_by_user_id
        LEFT JOIN users fu ON fu.id = cand.first_contacted_by_user_id
        LEFT JOIN candidate_skills cs ON cs.candidate_id = cand.id
        LEFT JOIN skills s ON s.id = cs.skill_id
        GROUP BY cand.id;
    """)

    conn.commit()
    conn.close()
