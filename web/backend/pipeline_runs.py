"""Atomic reservation of candidate-pipeline runs."""
from __future__ import annotations

import sqlite3


class PipelineRunAlreadyRunning(Exception):
    """Raised when a campaign already has a run with status=Running."""


def reserve_pipeline_run(
    conn: sqlite3.Connection,
    *,
    campaign_id: int,
    run_type: str,
    command: str,
    campaign_dir: str,
    artifact_path: str,
    started_at: str,
    created_by_user_id: int,
) -> int:
    """Atomically check for and insert the only Running row for a campaign."""
    try:
        conn.execute("BEGIN IMMEDIATE")
        running_row = conn.execute(
            """
            SELECT id
            FROM pipeline_runs
            WHERE campaign_id = ? AND status = 'Running'
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (campaign_id,),
        ).fetchone()
        if running_row:
            conn.rollback()
            raise PipelineRunAlreadyRunning

        cursor = conn.execute(
            """
            INSERT INTO pipeline_runs (
                campaign_id,
                run_type,
                status,
                command,
                campaign_dir,
                artifact_path,
                started_at,
                created_by_user_id
            )
            VALUES (?, ?, 'Running', ?, ?, ?, ?, ?)
            """,
            (
                campaign_id,
                run_type,
                command,
                campaign_dir,
                artifact_path,
                started_at,
                created_by_user_id,
            ),
        )
        if cursor.lastrowid is None:
            raise RuntimeError("Pipeline run insert did not return an id")
        run_id = cursor.lastrowid
        conn.commit()
        return run_id
    except PipelineRunAlreadyRunning:
        raise
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
