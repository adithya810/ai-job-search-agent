"""SQLite persistent storage (`jobs_history.db`) for deduplication and run telemetry."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Any

from .models import JobListing


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS seen_jobs (
    fingerprint TEXT PRIMARY KEY,
    job_id TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT NOT NULL,
    work_mode TEXT NOT NULL DEFAULT '',
    experience TEXT NOT NULL DEFAULT '',
    posted_date TEXT NOT NULL DEFAULT '',
    relevance_score REAL NOT NULL DEFAULT 0,
    resume_match_pct INTEGER NOT NULL DEFAULT 0,
    best_resume_track TEXT NOT NULL DEFAULT '',
    fit_reason TEXT NOT NULL DEFAULT '',
    first_seen_at TEXT NOT NULL,
    notified_at TEXT DEFAULT NULL
);

CREATE INDEX IF NOT EXISTS idx_seen_jobs_url ON seen_jobs(url);
CREATE INDEX IF NOT EXISTS idx_seen_jobs_source_id ON seen_jobs(source, job_id);

CREATE TABLE IF NOT EXISTS runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ran_at TEXT NOT NULL,
    fetched_count INTEGER NOT NULL DEFAULT 0,
    new_count INTEGER NOT NULL DEFAULT 0,
    qualifying_count INTEGER NOT NULL DEFAULT 0,
    digest_delivered INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT ''
);
"""


class JobHistoryDB:
    """SQLite persistence layer tracking previously seen job URLs, IDs, and weekly runs."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)

    def is_seen(self, job: JobListing) -> bool:
        """Return True if the job URL, (source, job_id), or fingerprint is already stored."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM seen_jobs
                WHERE fingerprint = ?
                   OR (url != '' AND url = ?)
                   OR (job_id != '' AND source = ? AND job_id = ?)
                LIMIT 1
                """,
                (job.fingerprint, job.url, job.source, job.job_id),
            ).fetchone()
            return row is not None

    def filter_unseen(self, jobs: list[JobListing]) -> list[JobListing]:
        """Return only jobs that have never been seen in `jobs_history.db`."""
        return [j for j in jobs if not self.is_seen(j)]

    def record_jobs(
        self,
        records: list[dict[str, Any]],
        *,
        mark_notified: bool = False,
    ) -> int:
        """Persist newly processed jobs into `seen_jobs`."""
        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        notified_val = now_iso if mark_notified else None
        inserted = 0
        with self._connect() as conn:
            for rec in records:
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO seen_jobs (
                        fingerprint, job_id, source, url, title, company, location,
                        work_mode, experience, posted_date, relevance_score,
                        resume_match_pct, best_resume_track, fit_reason,
                        first_seen_at, notified_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        rec.get("fingerprint", ""),
                        rec.get("job_id", ""),
                        rec.get("source", ""),
                        rec.get("url", ""),
                        rec.get("title", ""),
                        rec.get("company", ""),
                        rec.get("location", ""),
                        rec.get("work_mode", ""),
                        rec.get("experience", ""),
                        rec.get("posted_date", ""),
                        float(rec.get("relevance_score", 0.0)),
                        int(rec.get("resume_match_pct", 0)),
                        rec.get("best_resume_track", ""),
                        rec.get("fit_reason", ""),
                        now_iso,
                        notified_val,
                    ),
                )
                if cur.rowcount:
                    inserted += 1
        return inserted

    def log_run(
        self,
        *,
        fetched_count: int,
        new_count: int,
        qualifying_count: int,
        digest_delivered: bool,
        status: str,
        notes: str = "",
    ) -> int:
        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO runs (
                    ran_at, fetched_count, new_count, qualifying_count,
                    digest_delivered, status, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now_iso,
                    fetched_count,
                    new_count,
                    qualifying_count,
                    1 if digest_delivered else 0,
                    status,
                    notes,
                ),
            )
            return int(cur.lastrowid or 0)

    def stats(self) -> dict[str, Any]:
        with self._connect() as conn:
            total_seen = conn.execute("SELECT COUNT(*) FROM seen_jobs").fetchone()[0]
            total_notified = conn.execute(
                "SELECT COUNT(*) FROM seen_jobs WHERE notified_at IS NOT NULL"
            ).fetchone()[0]
            total_runs = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
            last_run = conn.execute(
                "SELECT ran_at, status, qualifying_count FROM runs ORDER BY run_id DESC LIMIT 1"
            ).fetchone()
        return {
            "db_path": str(self.db_path),
            "total_seen_jobs": total_seen,
            "total_notified_jobs": total_notified,
            "total_runs": total_runs,
            "last_run": dict(last_run) if last_run else None,
        }
