"""
database.py — Thin SQLite wrapper for session metadata.

The database file lives on the qa-data Docker volume at /app/data/sessions.db.
All operations are synchronous (FastAPI background tasks handle concurrency).
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

DB_PATH = Path("/app/data/sessions.db")


# ------------------------------------------------------------------
# Initialisation
# ------------------------------------------------------------------

def init_db() -> None:
    """Create the sessions table if it does not already exist."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id       TEXT PRIMARY KEY,
                started_at       TEXT,
                ended_at         TEXT,
                os               TEXT,
                language         TEXT,
                audio_enabled    INTEGER DEFAULT 0,
                event_count      INTEGER DEFAULT 0,
                screenshot_count INTEGER DEFAULT 0,
                status           TEXT    DEFAULT 'captured',
                report_path      TEXT,
                name             TEXT,
                project          TEXT
            )
        """)
        # Migrate older databases that predate the name/project columns.
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)")}
        if "name" not in existing:
            conn.execute("ALTER TABLE sessions ADD COLUMN name TEXT")
        if "project" not in existing:
            conn.execute("ALTER TABLE sessions ADD COLUMN project TEXT")

        # Per-project context: free-form markdown the user maintains to tell the
        # AI what the project is, how it works, and what to expect.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                name       TEXT PRIMARY KEY,
                context    TEXT DEFAULT '',
                updated_at TEXT
            )
        """)
        conn.commit()


# ------------------------------------------------------------------
# Connection helper
# ------------------------------------------------------------------

@contextmanager
def _conn() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


# ------------------------------------------------------------------
# CRUD helpers
# ------------------------------------------------------------------

def upsert_session(manifest: dict) -> None:
    """Insert or replace a session record from a manifest dict.

    ``name``/``project`` are read from the manifest (rename writes them there),
    so re-ingesting an already-named session does not wipe its metadata.
    """
    row = {
        "name": None,
        "project": None,
        **manifest,
    }
    with _conn() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO sessions
                (session_id, started_at, ended_at, os, language,
                 audio_enabled, event_count, screenshot_count, status,
                 name, project)
            VALUES
                (:session_id, :started_at, :ended_at, :os, :language,
                 :audio_enabled, :event_count, :screenshot_count, 'captured',
                 :name, :project)
            """,
            row,
        )
        conn.commit()


def update_session_status(
    session_id: str,
    status: str,
    report_path: str | None = None,
) -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE sessions SET status = ?, report_path = ? WHERE session_id = ?",
            (status, report_path, session_id),
        )
        conn.commit()


def set_session_meta(
    session_id: str,
    name: str | None,
    project: str | None,
) -> None:
    """Set the friendly name and/or project for a session.

    Ensures a row exists first (a session discovered only on the filesystem may
    not yet be in the DB), then updates the two metadata columns.
    """
    with _conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO sessions (session_id, status) VALUES (?, 'captured')",
            (session_id,),
        )
        conn.execute(
            "UPDATE sessions SET name = ?, project = ? WHERE session_id = ?",
            (name, project, session_id),
        )
        conn.commit()


def get_project_context(name: str) -> str:
    """Return the stored context for a project (empty string if none)."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT context FROM projects WHERE name = ?", (name,)
        ).fetchone()
        return (row["context"] or "") if row else ""


def set_project_context(name: str, context: str) -> None:
    """Create/update a project's context markdown."""
    import datetime
    now = datetime.datetime.utcnow().isoformat() + "Z"
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO projects (name, context, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET context = excluded.context,
                                            updated_at = excluded.updated_at
            """,
            (name, context, now),
        )
        conn.commit()


def list_project_names() -> list[str]:
    """Distinct project names: those with saved context + those used by sessions."""
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT name FROM projects
            UNION
            SELECT DISTINCT project FROM sessions
            WHERE project IS NOT NULL AND project <> ''
            """
        ).fetchall()
        return sorted({r["name"] for r in rows if r["name"]})


def list_sessions() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM sessions ORDER BY started_at DESC"
        ).fetchall()
        return [dict(row) for row in rows]


def get_session(session_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        return dict(row) if row else None


def delete_session(session_id: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        conn.commit()
