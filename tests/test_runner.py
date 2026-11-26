"""Unit tests for Phase 1-3 autonomous runner, SQLite history DB, IST scheduler, and exclusions."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from zoneinfo import ZoneInfo

import agent_runner
from job_agent.models import JobListing
from job_agent.storage import JobHistoryDB

IST = ZoneInfo("Asia/Kolkata")


class TestAutonomousRunner(unittest.TestCase):
    def test_sqlite_history_deduplication_and_run_logging(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = JobHistoryDB(Path(tmp) / "jobs_history.db")
            j1 = JobListing(
                job_id="101",
                source="linkedin",
                title="Senior Data Analyst",
                company="Acme",
                location="Hyderabad",
                url="https://in.linkedin.com/jobs/view/101",
                fingerprint="fp101",
            )
            j2 = JobListing(
                job_id="102",
                source="linkedin",
                title="Power BI Developer",
                company="Beta",
                location="Bengaluru",
                url="https://in.linkedin.com/jobs/view/102",
                fingerprint="fp102",
            )
            self.assertEqual(len(db.filter_unseen([j1, j2])), 2)
            inserted = db.record_jobs(
                [
                    {
                        "fingerprint": j1.fingerprint,
                        "job_id": j1.job_id,
                        "source": j1.source,
                        "url": j1.url,
                        "title": j1.title,
                        "company": j1.company,
                        "location": j1.location,
                        "relevance_score": 8.4,
                        "resume_match_pct": 84,
                    }
                ],
                mark_notified=True,
            )
            self.assertEqual(inserted, 1)
            unseen = db.filter_unseen([j1, j2])
            self.assertEqual([j.job_id for j in unseen], ["102"])

            run_id = db.log_run(
                fetched_count=2,
                new_count=1,
                qualifying_count=1,
                digest_delivered=True,
                status="ok",
                notes="test run",
            )
            self.assertGreaterEqual(run_id, 1)
            st = db.stats()
            self.assertEqual(st["total_seen_jobs"], 1)
            self.assertEqual(st["total_notified_jobs"], 1)
            self.assertEqual(st["total_runs"], 1)

    def test_next_monday_ist_schedule_calculation(self) -> None:
        # Monday Nov 23, 2026 at 17:55 IST (past 11:00 AM) -> next runs must ONLY be Monday 11:00 AM IST
        now_past = datetime(2026, 11, 23, 17, 55, tzinfo=IST)
        runs_past = agent_runner.next_monday_ist_runs(3, now_ist=now_past)
        self.assertEqual(
            runs_past,
            [
                "2026-11-30 11:00 IST (Monday)",
                "2026-12-07 11:00 IST (Monday)",
                "2026-12-14 11:00 IST (Monday)",
            ],
        )

        # Monday Nov 23, 2026 at 09:30 IST (before 11:00 AM) -> next run is 11:00 AM today
        now_before = datetime(2026, 11, 23, 9, 30, tzinfo=IST)
        runs_before = agent_runner.next_monday_ist_runs(2, now_ist=now_before)
        self.assertEqual(
            runs_before,
            [
                "2026-11-23 11:00 IST (Monday)",
                "2026-11-30 11:00 IST (Monday)",
            ],
        )

    def test_user_profile_model_and_schedule_defaults(self) -> None:
        prof = agent_runner.UserProfile.model_validate_json(
            (Path(__file__).resolve().parent.parent / "profile.json").read_text(encoding="utf-8")
        )
        self.assertEqual(prof.model, "hydrogen-medium")
        self.assertEqual(prof.reasoning_effort, "medium")
        self.assertEqual(prof.schedule_cron_ist, "0 11 * * 1")

    def test_exclusions_filter(self) -> None:
        intern_job = JobListing(
            job_id="1",
            source="linkedin",
            title="Data Analyst Intern (Unpaid)",
            company="Startup",
            location="India",
            url="https://example.com/1",
        )
        valid_job = JobListing(
            job_id="2",
            source="linkedin",
            title="Senior Power BI Data Analyst",
            company="EnterpriseCo",
            location="Hyderabad",
            url="https://example.com/2",
            description="4+ years Power BI, SQL, Azure Databricks.",
        )
        exclusions = ["unpaid internship", "unpaid", "intern", "fresher"]
        self.assertIsNotNone(agent_runner.matches_exclusions(intern_job, exclusions))
        self.assertIsNone(agent_runner.matches_exclusions(valid_job, exclusions))


if __name__ == "__main__":
    unittest.main()
