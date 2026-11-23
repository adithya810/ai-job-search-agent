"""Unit tests for the Data Analyst Job Search Agent."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

from job_agent.browser import detect_anti_bot_challenge
from job_agent.dedup import deduplicate_jobs
from job_agent.exporters import (
    build_report_payload,
    export_csv,
    export_dashboard_html,
    export_json,
)
from job_agent.models import JobListing, SearchConfig, SiteRunStatus
from job_agent.providers.linkedin import (
    parse_linkedin_detail_description,
    parse_linkedin_guest_cards,
)
from job_agent.providers.naukri import (
    build_naukri_search_url,
    parse_naukri_cards_payload,
)
from job_agent.providers.ziprecruiter import (
    build_ziprecruiter_search_url,
    parse_ziprecruiter_cards_payload,
)
from job_agent.scorer import score_jobs, summarize_skills

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"


SAMPLE_LINKEDIN_HTML = """<!DOCTYPE html>
<li>
  <div class="base-card base-search-card" data-entity-urn="urn:li:jobPosting:999111222">
    <a class="base-card__full-link" href="https://in.linkedin.com/jobs/view/data-analyst-at-acme-999111222?trackingId=abc">
      <span>Data Analyst</span>
    </a>
    <h3 class="base-search-card__title">  Data Analyst  </h3>
    <h4 class="base-search-card__subtitle">  Acme Analytics  </h4>
    <span class="job-search-card__location">  Bengaluru, Karnataka, India  </span>
    <time datetime="2026-11-20">3 days ago</time>
  </div>
</li>
"""

SAMPLE_LINKEDIN_DETAIL_HTML = """
<div class="show-more-less-html__markup">
  <p>We are hiring a Data Analyst (2-4 years) for a Hybrid role in Bengaluru.</p>
  <ul>
    <li>Strong SQL and PostgreSQL skills</li>
    <li>Hands-on Python (Pandas) and Power BI dashboards</li>
    <li>Advanced Excel and A/B Testing experience</li>
  </ul>
</div>
"""


class TestJobSearchAgent(unittest.TestCase):
    def setUp(self) -> None:
        self.config = SearchConfig.from_file(CONFIG_PATH)

    def test_parse_linkedin_guest_cards_and_detail(self) -> None:
        jobs = parse_linkedin_guest_cards(
            SAMPLE_LINKEDIN_HTML,
            query_matched="Data Analyst",
            location_searched="Bengaluru, Karnataka, India",
        )
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job.job_id, "999111222")
        self.assertEqual(job.title, "Data Analyst")
        self.assertEqual(job.company, "Acme Analytics")
        self.assertEqual(job.location, "Bengaluru, Karnataka, India")
        self.assertEqual(job.posted_date, "2026-11-20")
        self.assertEqual(job.url, "https://in.linkedin.com/jobs/view/data-analyst-at-acme-999111222")

        desc = parse_linkedin_detail_description(SAMPLE_LINKEDIN_DETAIL_HTML)
        self.assertIn("PostgreSQL", desc)
        self.assertIn("Power BI", desc)

    def test_naukri_and_ziprecruiter_url_and_payload_parsing(self) -> None:
        self.assertEqual(
            build_naukri_search_url("Data Analyst", "Bengaluru, Karnataka, India"),
            "https://www.naukri.com/data-analyst-jobs-in-bengaluru",
        )
        self.assertEqual(
            build_naukri_search_url("Data Analyst", "Remote India"),
            "https://www.naukri.com/data-analyst-jobs?wfhType=2",
        )
        naukri_jobs = parse_naukri_cards_payload(
            [
                {
                    "title": "Senior Data Analyst",
                    "company": "FinTech India",
                    "location": "Hyderabad",
                    "experience": "2-5 Yrs",
                    "salary": "10-15 Lacs PA",
                    "url": "https://www.naukri.com/job-listings-senior-data-analyst-12345678",
                    "skills": ["SQL", "Tableau", "Python"],
                }
            ]
        )
        self.assertEqual(len(naukri_jobs), 1)
        self.assertEqual(naukri_jobs[0].job_id, "12345678")
        self.assertEqual(naukri_jobs[0].raw_skills, ["SQL", "Tableau", "Python"])

        zip_url = build_ziprecruiter_search_url("Data Analyst", "India")
        self.assertIn("search=Data+Analyst", zip_url)
        zip_jobs = parse_ziprecruiter_cards_payload(
            [
                {
                    "title": "Remote Data Analyst",
                    "company": "Global Corp",
                    "location": "Remote",
                    "description": "Requires SQL, Excel, and Power BI.",
                    "url": "https://www.ziprecruiter.com/jobs/global-corp/remote-data-analyst",
                }
            ]
        )
        self.assertEqual(len(zip_jobs), 1)
        self.assertTrue(len(zip_jobs[0].job_id) == 12)

    def test_scoring_and_deduplication_and_exports(self) -> None:
        j1 = JobListing(
            job_id="1",
            source="linkedin",
            title="Data Analyst",
            company="Acme Analytics",
            location="Bengaluru, Karnataka, India",
            url="https://in.linkedin.com/jobs/view/1",
            description="2-4 years experience. Hybrid role using SQL, Python, Excel, Power BI, Tableau, and Snowflake.",
        )
        # Duplicate of j1 with shorter description (should lose to richer j1)
        j1_dup = JobListing(
            job_id="2",
            source="naukri",
            title="Data Analyst",
            company="Acme Analytics",
            location="Bengaluru",
            url="https://www.naukri.com/job/2",
            description="",
        )
        j2 = JobListing(
            job_id="3",
            source="ziprecruiter",
            title="Operations Specialist",
            company="Other Co",
            location="Pune, India",
            url="https://www.ziprecruiter.com/jobs/3",
            description="General administrative coordination.",
        )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            history = tmp_path / "seen.json"
            deduped = deduplicate_jobs([j1_dup, j1, j2], seen_history_path=history)
            self.assertEqual(len(deduped), 2)
            scored = score_jobs(deduped, self.config)
            self.assertEqual(scored[0].title, "Data Analyst")
            self.assertGreaterEqual(scored[0].match_score, 90)
            self.assertEqual(scored[0].work_mode, "Hybrid")
            self.assertIn("2-4 years", scored[0].experience)
            self.assertEqual(set(scored[0].matched_core_skills), {"SQL", "Python", "Excel", "Power BI", "Tableau"})
            self.assertLess(scored[1].match_score, 30)

            # Second run should mark already-seen fingerprints as is_new=False
            second_run = deduplicate_jobs([j1], seen_history_path=history)
            self.assertFalse(second_run[0].is_new)

            summary = summarize_skills(scored)
            self.assertEqual(summary["core"]["SQL"], 1)

            payload = build_report_payload(
                scored,
                [SiteRunStatus(site="linkedin", mode_used="public", status="ok", jobs_found=1, message="ok")],
                summary,
                mode="public",
                locations=["Bengaluru"],
                queries=["Data Analyst"],
            )
            csv_file = export_csv(scored, tmp_path / "jobs.csv")
            json_file = export_json(payload, tmp_path / "jobs.json")
            html_file = export_dashboard_html(payload, tmp_path / "dashboard.html")

            with csv_file.open(encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["title"], "Data Analyst")

            loaded = json.loads(json_file.read_text(encoding="utf-8"))
            self.assertEqual(loaded["summary"]["total_jobs"], 2)
            self.assertIn("Acme Analytics", html_file.read_text(encoding="utf-8"))

    def test_anti_bot_detection(self) -> None:
        self.assertIsNotNone(detect_anti_bot_challenge("<html>Just a moment... cf-turnstile</html>"))
        self.assertIsNotNone(detect_anti_bot_challenge("", url="https://www.linkedin.com/checkpoint/challenge/123"))
        self.assertIsNone(detect_anti_bot_challenge("<html><body>Normal Data Analyst job listing</body></html>"))


if __name__ == "__main__":
    unittest.main()
