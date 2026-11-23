"""Unit and end-to-end tests for Exa, Firecrawl, MCP (client + server), and >3y / <=48h filters."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock

from job_agent.connectors.exa import ExaConnector, ExaProvider, parse_exa_results
from job_agent.connectors.firecrawl import (
    FirecrawlConnector,
    FirecrawlProvider,
    parse_firecrawl_results,
)
from job_agent.connectors.mcp_client import StdioMCPClient, parse_mcp_tool_results
from job_agent.connectors.normalize import infer_source_from_url, parse_title_and_company
from job_agent.filters import (
    estimate_age_hours,
    filter_jobs,
    meets_experience_requirement,
    meets_freshness_requirement,
    parse_experience_bounds,
)
from job_agent.models import JobListing, SearchConfig
from job_agent.providers.naukri import build_naukri_search_url
from job_agent.providers.ziprecruiter import build_ziprecruiter_search_url

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"


class TestFiltersAndConnectorsAndMCP(unittest.TestCase):
    def setUp(self) -> None:
        self.config = SearchConfig.from_file(CONFIG_PATH)
        self.fixed_now = datetime(2026, 11, 23, 12, 0, 0, tzinfo=timezone.utc)

    def test_experience_filter_strict_more_than_3_years(self) -> None:
        self.assertEqual(parse_experience_bounds("3-5 years of experience"), (3, 5))
        self.assertEqual(parse_experience_bounds("Minimum 4 years in analytics"), (4, None))
        self.assertEqual(parse_experience_bounds("More than 3 years of SQL"), (4, None))
        self.assertEqual(parse_experience_bounds("1 to 3 yrs"), (1, 3))

        cases = [
            ("Senior Data Analyst", "3-5 years", "", True),
            ("Senior Data Analyst", "4+ years", "", True),
            ("Data Analyst", "", "Requires more than 3 years of SQL and Python", True),
            ("Data Analyst", "2-4 years", "", False),
            ("Data Analyst", "1-3 years", "", False),
            ("Junior Data Analyst", "", "SQL and Excel", False),
            ("Data Analyst", "", "No experience years mentioned", False),
        ]
        for title, exp, desc, expected in cases:
            job = JobListing(
                job_id="x",
                source="linkedin",
                title=title,
                company="TestCo",
                location="Bengaluru",
                url="https://example.com/job",
                experience=exp,
                description=desc,
            )
            ok, _ = meets_experience_requirement(job, 3, strict=True)
            self.assertEqual(ok, expected, f"Failed for {title=} {exp=} {desc=}")

    def test_freshness_filter_48_hours(self) -> None:
        self.assertAlmostEqual(estimate_age_hours("6 hours ago", now=self.fixed_now), 6.0)
        self.assertAlmostEqual(estimate_age_hours("1 day ago", now=self.fixed_now), 24.0)
        self.assertAlmostEqual(estimate_age_hours("2026-11-22", now=self.fixed_now), 24.0)
        self.assertAlmostEqual(estimate_age_hours("2026-11-21", now=self.fixed_now), 48.0)
        self.assertAlmostEqual(estimate_age_hours("2026-11-20", now=self.fixed_now), 72.0)

        fresh_job = JobListing(
            job_id="1",
            source="linkedin",
            title="Senior Data Analyst",
            company="FreshCo",
            location="Hyderabad",
            url="https://in.linkedin.com/jobs/view/1",
            posted_date="2026-11-22",
            experience="4-6 years",
        )
        stale_job = JobListing(
            job_id="2",
            source="linkedin",
            title="Senior Data Analyst",
            company="OldCo",
            location="Hyderabad",
            url="https://in.linkedin.com/jobs/view/2",
            posted_date="2026-11-18",
            experience="5+ years",
        )
        junior_fresh = JobListing(
            job_id="3",
            source="naukri",
            title="Junior Data Analyst",
            company="StartCo",
            location="Pune",
            url="https://www.naukri.com/job/3",
            posted_date="5 hours ago",
            experience="1-2 years",
        )

        self.assertTrue(meets_freshness_requirement(fresh_job, 48, now=self.fixed_now)[0])
        self.assertFalse(meets_freshness_requirement(stale_job, 48, now=self.fixed_now)[0])

        kept, stats = filter_jobs([fresh_job, stale_job, junior_fresh], self.config, now=self.fixed_now)
        self.assertEqual([j.job_id for j in kept], ["1"])
        self.assertEqual(stats["rejected_freshness"], 1)
        self.assertEqual(stats["rejected_experience"], 1)

    def test_provider_url_freshness_and_experience_params(self) -> None:
        naukri_url = build_naukri_search_url(
            "Data Analyst",
            "Bengaluru, Karnataka, India",
            max_age_hours=48,
            min_experience_years=3,
        )
        self.assertIn("jobAge=2", naukri_url)
        self.assertIn("experience=3", naukri_url)

        zip_url = build_ziprecruiter_search_url("Data Analyst", "India", max_age_hours=48)
        self.assertIn("days=2", zip_url)

    def test_exa_connector_parsing_and_provider_mock(self) -> None:
        sample = [
            {
                "url": "https://www.naukri.com/job-listings-senior-data-analyst-998877",
                "title": "Senior Data Analyst - FinPulse India | Naukri.com",
                "publishedDate": "2026-11-22T10:00:00Z",
                "text": "Hiring in Bengaluru. Requires 4-6 years of SQL, Python, Power BI, and Tableau.",
            }
        ]
        jobs = parse_exa_results(sample, query_matched="Data Analyst", location_searched="Bengaluru")
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].source, "naukri")
        self.assertEqual(jobs[0].title, "Senior Data Analyst")
        self.assertEqual(jobs[0].company, "FinPulse India")
        self.assertEqual(jobs[0].posted_date, "2026-11-22")

        mock_conn = MagicMock(spec=ExaConnector)
        mock_conn.is_configured = True
        mock_conn.search.return_value = sample
        provider = ExaProvider(self.config, connector=mock_conn)
        found, status = provider.search_public(["Data Analyst"], ["Bengaluru"], 5)
        self.assertEqual(status.status, "ok")
        self.assertEqual(len(found), 1)
        # Verify start_published_date was passed to Exa
        _, kwargs = mock_conn.search.call_args
        self.assertIsNotNone(kwargs.get("start_published_date"))

        # Missing API key returns clean status
        empty_conn = ExaConnector(api_key="")
        empty_conn.api_key = ""
        _, st_missing = ExaProvider(self.config, connector=empty_conn).search_public(
            ["Data Analyst"], ["India"], 5
        )
        self.assertEqual(st_missing.status, "missing_api_key")

    def test_firecrawl_connector_parsing_and_provider_mock(self) -> None:
        sample = [
            {
                "url": "https://www.ziprecruiter.com/c/CloudCo/Job/Senior-Data-Analyst/-in-Remote",
                "title": "CloudCo hiring Senior Data Analyst in Remote | ZipRecruiter",
                "markdown": "5+ years experience with SQL, Python, Excel, and Power BI. Remote India.",
            }
        ]
        jobs = parse_firecrawl_results(sample, query_matched="Data Analyst", location_searched="India")
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].source, "ziprecruiter")
        self.assertEqual(jobs[0].title, "Senior Data Analyst")
        self.assertEqual(jobs[0].company, "CloudCo")

        mock_conn = MagicMock(spec=FirecrawlConnector)
        mock_conn.is_configured = True
        mock_conn.search.return_value = sample
        provider = FirecrawlProvider(self.config, connector=mock_conn)
        found, status = provider.search_public(["Data Analyst"], ["Hyderabad"], 5)
        self.assertEqual(status.status, "ok")
        self.assertEqual(len(found), 1)
        _, kwargs = mock_conn.search.call_args
        self.assertEqual(kwargs.get("tbs"), "qdr:w")

    def test_mcp_result_parser_and_live_stdio_roundtrip(self) -> None:
        # 1. Test parsing JSON tool output (Exa MCP / Firecrawl MCP style)
        tool_res = {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "results": [
                                {
                                    "url": "https://in.linkedin.com/jobs/view/senior-data-analyst-at-nova-12345",
                                    "title": "Senior Data Analyst at Nova Data | LinkedIn",
                                    "publishedDate": "2026-11-22",
                                    "text": "Hyderabad role, 4+ years experience in SQL and Power BI.",
                                }
                            ]
                        }
                    ),
                }
            ]
        }
        parsed = parse_mcp_tool_results(tool_res, server_name="exa")
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].source, "linkedin")
        self.assertEqual(parsed[0].company, "Nova Data")
        self.assertEqual(infer_source_from_url(parsed[0].url), "linkedin")
        self.assertEqual(parse_title_and_company("Data Analyst @ Razorpay")[1], "Razorpay")

        # 2. Live end-to-end stdio JSON-RPC round-trip against our own `mcp-serve`
        with StdioMCPClient(
            command=sys.executable,
            args=["-m", "job_agent", "--config", str(CONFIG_PATH), "mcp-serve"],
        ) as client:
            tools = client.list_tools()
            tool_names = {t["name"] for t in tools}
            self.assertEqual(
                tool_names,
                {
                    "search_jobs",
                    "search_web_exa",
                    "search_web_firecrawl",
                    "scrape_job_webpage",
                    "get_saved_jobs",
                },
            )
            call_res = client.call_tool("get_saved_jobs", {"min_score": 0, "limit": 3})
            self.assertFalse(call_res.get("isError", False))
            payload = json.loads(call_res["content"][0]["text"])
            self.assertIn("jobs", payload)

    def test_resume_matcher_and_apply_queue_export(self) -> None:
        import tempfile
        from job_agent.apply_assistant import export_apply_queue
        from job_agent.resume_matcher import ResumeProfile, match_jobs_to_resumes

        profiles = [
            ResumeProfile(
                profile_id="da",
                track="Data Analyst / Power BI & ETL",
                name="Adithya_Krishna.docx",
                drive_file_id="id1",
                drive_url="https://drive.google.com/file/d/id1/view",
                local_path="/home/antigravity/Adithya_Krishna.docx",
                years_experience=4.5,
                skills=["Power BI", "DAX", "Power Query", "SQL", "SQL Server / SSMS", "ETL / Data Pipelines", "Excel", "Python"],
            ),
            ResumeProfile(
                profile_id="genai",
                track="Gen AI & Agentic Analytics",
                name="Adithya_Krishna.pdf",
                drive_file_id="id2",
                drive_url="https://drive.google.com/file/d/id2/view",
                local_path="/home/antigravity/job-search-agent/resumes/resume_2026-10-26.pdf",
                years_experience=4.5,
                skills=["Power BI", "SQL", "Python", "Generative AI / LLMs", "Agentic AI / Workflows", "MCP / AI Connectors", "Machine Learning"],
            ),
        ]
        strong_job = JobListing(
            job_id="100",
            source="linkedin",
            title="Power BI Data Analyst",
            company="AnalyticsCo",
            location="Hyderabad, Telangana, India",
            url="https://in.linkedin.com/jobs/view/100",
            posted_date="2026-11-23",
            experience="3-5 years",
            description="Requires Power BI, DAX, Power Query, SQL Server, ETL pipelines, and Excel.",
            fingerprint="fp100",
        )
        weak_job = JobListing(
            job_id="101",
            source="linkedin",
            title="Principal Java Kubernetes Engineer",
            company="OtherCo",
            location="Bengaluru",
            url="https://in.linkedin.com/jobs/view/101",
            posted_date="2026-11-23",
            experience="10+ years",
            description="Requires Java, Scala, Kubernetes, Docker, SAP, and Salesforce.",
            fingerprint="fp101",
        )

        all_m, qualified = match_jobs_to_resumes([strong_job, weak_job], profiles, min_match_pct=80)
        self.assertEqual(len(all_m), 2)
        self.assertEqual([r.job_id for r in qualified], ["100"])
        self.assertGreaterEqual(qualified[0].resume_match_pct, 90)
        self.assertEqual(qualified[0].best_resume_id, "da")

        with tempfile.TemporaryDirectory() as tmp:
            j_path, c_path = export_apply_queue(qualified, all_m, profiles, Path(tmp), min_match_pct=80)
            self.assertTrue(j_path.exists())
            self.assertTrue(c_path.exists())


if __name__ == "__main__":
    unittest.main()
