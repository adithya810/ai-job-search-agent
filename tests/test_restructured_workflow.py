"""End-to-end unit & Playwright integration tests for the Restructured 6-Stage Agentic Workflow."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import openpyxl

PROJECT_ROOT = Path(__file__).resolve().parent.parent
UPLOADED_DIR = PROJECT_ROOT / "uploaded_agent"
if str(UPLOADED_DIR) not in sys.path:
    sys.path.insert(0, str(UPLOADED_DIR))

from agent_memory import AgentMemoryState, load_career_pages_from_excel
from auto_applier import attempt_auto_apply, is_status_applied
from excel_reporter import (
    PRIMARY_SHEET_NAME,
    STRUCTURED_HEADERS,
    get_queued_jobs_from_excel,
    load_applied_urls,
    update_applied_companies_excel,
    update_single_job_status_in_excel,
)
from job_agent.workflow import export_records_to_structured_excel
from matcher import evaluate_and_gate_jobs
from scrapers import run_sequential_48h_search


class TestRestructuredSixStageWorkflow(unittest.TestCase):
    def test_stage_01_and_02_resume_and_excel_memory_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_xlsx = tmp_path / "Company name.xlsx"
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.append(["Company Name", "Official Careers Portal", "Target Roles"])
            ws.append(["Deloitte", "https://usijobs.deloitte.com/careersUSI", "Data Analyst / MIS"])
            ws.append(["Acme Corp", "https://careers.acme.example/jobs", "Power BI Developer"])
            wb.save(input_xlsx)

            career_pages = load_career_pages_from_excel(input_xlsx)
            self.assertEqual(len(career_pages), 2)
            self.assertEqual(career_pages[0]["careers_url"], "https://usijobs.deloitte.com/careersUSI")
            self.assertEqual(career_pages[1]["company"], "Acme Corp")
            self.assertEqual(career_pages[1]["careers_url"], "https://careers.acme.example/jobs")

            state_file = tmp_path / "agent_memory_state.json"
            mem = AgentMemoryState.build_and_persist(excel_path=input_xlsx, state_path=state_file)
            self.assertTrue(state_file.exists())
            self.assertGreaterEqual(len(mem.resume_skills), 10)
            self.assertIn("Python", mem.resume_skills)
            self.assertIn("SQL", mem.resume_skills)
            self.assertIn("Power BI", mem.resume_skills)
            self.assertEqual(mem.freshness_window_hours, 48)
            self.assertEqual(mem.match_threshold_pct, 80.0)

    def test_stage_03_sequential_order_1_to_4_role_by_role(self) -> None:
        execution_trace: list[str] = []

        def fake_linkedin(queries, locations, max_per_query=5, easy_apply_only=False):
            tag = "li_easy" if easy_apply_only else "li_std"
            execution_trace.append(f"step1_{tag}:{queries[0]}")
            return [
                {
                    "portal": "LinkedIn Easy Apply" if easy_apply_only else "LinkedIn",
                    "title": f"{queries[0]} Role",
                    "company": "Deloitte",
                    "location": "Hyderabad",
                    "url": f"https://linkedin.example/jobs/{queries[0].replace(' ', '_')}_{tag}",
                    "posted_date": "1 day ago",
                    "easy_apply": easy_apply_only,
                }
            ]

        def fake_naukri(page, freshness_days=2, max_per_query=5, role_queries=None, locations=None):
            execution_trace.append(f"step2_naukri:{role_queries[0]}")
            return [
                {
                    "portal": "Naukri",
                    "title": f"{role_queries[0]} Specialist",
                    "company": "Infosys",
                    "location": "Bengaluru",
                    "url": f"https://naukri.example/jobs/{role_queries[0].replace(' ', '_')}",
                    "posted_date": "Today",
                }
            ]

        def fake_zip(page, locations, max_per_loc=5, queries=None):
            execution_trace.append(f"step3_zip:{queries[0]}")
            return [
                {
                    "portal": "ZipRecruiter",
                    "title": f"{queries[0]} Associate",
                    "company": "Accenture",
                    "location": "Gurugram",
                    "url": f"https://ziprecruiter.example/jobs/{queries[0].replace(' ', '_')}",
                    "posted_date": "Within 48 hours",
                }
            ]

        def fake_career_pages(page, target_companies, career_pages=None):
            execution_trace.append("step4_career_pages")
            return [
                {
                    "portal": "Company Career Page (Deloitte)",
                    "title": "Senior Data Analyst",
                    "company": "Deloitte",
                    "location": "Hyderabad",
                    "url": "https://careers.deloitte.example/job/999",
                    "posted_date": "Within 48 hours",
                }
            ]

        mem = AgentMemoryState(
            candidate_name="Adithya Krishna",
            seniority_years=4.5,
            target_roles=["Data Analyst", "Power BI Developer"],
            primary_skills=["Python", "SQL", "Power BI"],
            resume_skills=["Python", "SQL", "Power BI"],
            career_pages=[{"company": "Deloitte", "careers_url": "https://careers.deloitte.example"}],
        )

        with (
            patch("scrapers.search_linkedin_jobs", side_effect=fake_linkedin),
            patch("naukri_agent.search_naukri_api_and_portal", side_effect=fake_naukri),
            patch("scrapers.search_ziprecruiter_jobs", side_effect=fake_zip),
            patch("scrapers.search_official_company_sites", side_effect=fake_career_pages),
            patch("scrapers.discover_jobs_via_search", return_value=[]),
        ):
            res = run_sequential_48h_search(mem, page=object(), max_roles=2, max_per_role=2)

        self.assertEqual(
            execution_trace,
            [
                "step1_li_std:Data Analyst",
                "step1_li_easy:Data Analyst",
                "step2_naukri:Data Analyst",
                "step3_zip:Data Analyst",
                "step1_li_std:Power BI Developer",
                "step1_li_easy:Power BI Developer",
                "step2_naukri:Power BI Developer",
                "step3_zip:Power BI Developer",
                "step4_career_pages",
            ],
        )
        self.assertEqual(res["step_counts"]["step_1_linkedin"], 4)
        self.assertEqual(res["step_counts"]["step_2_naukri"], 2)
        self.assertEqual(res["step_counts"]["step_3_ziprecruiter"], 2)
        self.assertEqual(res["step_counts"]["step_4_company_career_pages"], 1)

    def test_stage_04_deduplication_48h_and_80_pct_gate(self) -> None:
        mem = AgentMemoryState(
            candidate_name="Adithya Krishna",
            seniority_years=4.5,
            target_roles=["Data Analyst", "Power BI Developer"],
            resume_skills=["Python", "SQL", "Power BI", "DAX", "Power Query", "Advanced Excel", "ETL Pipelines"],
            career_pages=[{"company": "Deloitte", "careers_url": "https://usijobs.deloitte.com"}],
        )
        raw_jobs = [
            # Duplicate 1 (no easy apply)
            {
                "portal_step": "Step 4: Company Career Page",
                "title": "Power BI Data Analyst",
                "company": "Deloitte",
                "location": "Hyderabad",
                "experience": "3-5 Years",
                "description": "Power BI, DAX, SQL, Python, Power Query, Excel.",
                "url": "https://deloitte.example/job/1",
                "posted_date": "1 day ago",
                "easy_apply": False,
            },
            # Duplicate 2 (same company + title, HAS Easy Apply -> should win dedup!)
            {
                "portal_step": "Step 1: LinkedIn",
                "title": "Power BI Data Analyst",
                "company": "Deloitte",
                "location": "Hyderabad",
                "experience": "3-5 Years",
                "description": "Power BI, DAX, SQL, Python, Power Query, Advanced Excel, ETL pipelines.",
                "url": "https://linkedin.example/jobs/view/1",
                "posted_date": "8 hours ago",
                "easy_apply": True,
            },
            # Stale (> 48h) -> should be rejected
            {
                "portal_step": "Step 2: Naukri.com",
                "title": "Data Analyst",
                "company": "Infosys",
                "location": "Bengaluru",
                "experience": "3-5 Years",
                "description": "Python, SQL, Power BI, DAX, Excel.",
                "url": "https://naukri.example/job/stale",
                "posted_date": "5 days ago",
            },
            # Unrelated / < 80% match -> should be rejected
            {
                "portal_step": "Step 3: ZipRecruiter",
                "title": "iOS Developer",
                "company": "MobileCo",
                "location": "Bengaluru",
                "experience": "3-5 Years",
                "description": "Swift, Objective-C, Xcode, iOS SDK, UIKit mobile app development.",
                "url": "https://ziprecruiter.example/job/ios",
                "posted_date": "Today",
            },
        ]

        gated = evaluate_and_gate_jobs(raw_jobs, mem, threshold_pct=80.0)
        qualified = gated["qualified_jobs"]
        self.assertEqual(len(qualified), 1)
        self.assertEqual(qualified[0]["url"], "https://linkedin.example/jobs/view/1")
        self.assertTrue(qualified[0]["easy_apply"])
        self.assertGreaterEqual(qualified[0]["match_score"], 90.0)
        self.assertEqual(gated["stats"]["duplicates_removed"], 1)
        self.assertEqual(gated["stats"]["stale_or_exp_rejected"], 1)
        self.assertEqual(gated["stats"]["below_threshold_rejected"], 1)

    def test_stage_05_playwright_apply_button_available_vs_missing_vs_antibot(self) -> None:
        from playwright.sync_api import sync_playwright

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            html_with_apply = tmp_path / "linkedin_easy.html"
            html_with_apply.write_text(
                """<!DOCTYPE html><html><body>
                <h1>Data Analyst at Acme</h1>
                <button class="jobs-apply-button" onclick="document.getElementById('modal').style.display='block'">Easy Apply</button>
                <div id="modal" style="display:none">
                  <input type="email" name="email" />
                  <button aria-label="Submit application" onclick="document.body.innerHTML='<div>Application submitted</div>'">Submit application</button>
                </div>
                </body></html>""",
                encoding="utf-8",
            )

            html_no_apply = tmp_path / "linkedin_redirect.html"
            html_no_apply.write_text(
                """<!DOCTYPE html><html><body>
                <h1>Data Analyst at BetaCorp</h1>
                <a href="https://betacorp.example/apply">Apply on company website</a>
                </body></html>""",
                encoding="utf-8",
            )

            html_antibot = tmp_path / "linkedin_challenge.html"
            html_antibot.write_text(
                """<!DOCTYPE html><html><body>
                <h1>Security Verification</h1>
                <p>Please verify you are human</p>
                <div class="cf-turnstile"></div>
                </body></html>""",
                encoding="utf-8",
            )

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()

                # 1. Apply button IS available -> applies & marks is_applied = True
                job_apply = {
                    "portal": "LinkedIn Easy Apply",
                    "company": "Acme",
                    "title": "Data Analyst",
                    "url": html_with_apply.as_uri(),
                }
                status_1, _ = attempt_auto_apply(page, job_apply)
                self.assertTrue(is_status_applied(status_1))
                self.assertTrue(job_apply["is_applied"])
                self.assertIn("Applied (LinkedIn Easy Apply)", job_apply["applied_result_display"])

                # 2. Apply button NOT available -> does not apply, preserves link
                job_no_btn = {
                    "portal": "LinkedIn",
                    "company": "BetaCorp",
                    "title": "Data Analyst",
                    "url": html_no_apply.as_uri(),
                }
                status_2, _ = attempt_auto_apply(page, job_no_btn)
                self.assertFalse(is_status_applied(status_2))
                self.assertFalse(job_no_btn["is_applied"])
                self.assertEqual(job_no_btn["applied_result_display"], "")

                # 3. Anti-bot gate -> safely stops without interacting, preserves link
                job_gate = {
                    "portal": "LinkedIn",
                    "company": "GatedCorp",
                    "title": "Data Analyst",
                    "url": html_antibot.as_uri(),
                }
                status_3, _ = attempt_auto_apply(page, job_gate)
                self.assertFalse(is_status_applied(status_3))
                self.assertFalse(job_gate["is_applied"])
                self.assertIn("Verification Gate", status_3)

                browser.close()

    def test_stage_06_excel_shows_applied_result_instead_of_link_when_applied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            excel_file = tmp_path / "Applied_Companies_Tracker.xlsx"
            history_file = tmp_path / "applied_jobs_history.json"

            jobs = [
                # Job 1: Apply button was available -> Applied! Excel MUST show Applied Result instead of URL
                {
                    "company": "Deloitte",
                    "title": "Senior Data Analyst",
                    "portal_step": "Step 1: LinkedIn",
                    "portal": "LinkedIn Easy Apply",
                    "location": "Hyderabad",
                    "experience": "3-5 Years",
                    "posted_date": "6 hours ago",
                    "match_score": 96.5,
                    "matched_skills": ["Python", "SQL", "Power BI", "DAX"],
                    "missing_skills": ["Snowflake"],
                    "description": "Build Power BI dashboards, DAX models, and SQL pipelines.",
                    "resume_variant": "data_analyst",
                    "url": "https://www.linkedin.com/jobs/view/90001",
                    "is_applied": True,
                    "application_status": "Applied (LinkedIn Easy Apply)",
                    "applied_result_display": "Applied (LinkedIn Easy Apply) | Resume: Adithya_Krishna_Data_Analyst.pdf | 2026-11-25 04:10 PM IST",
                },
                # Job 2: No Apply button -> Not applied! Excel MUST show clickable Apply Link
                {
                    "company": "Capgemini",
                    "title": "Power BI Developer",
                    "portal_step": "Step 4: Company Career Page",
                    "portal": "Company Career Page (Capgemini)",
                    "location": "Bengaluru",
                    "experience": "3-5 Years",
                    "posted_date": "1 day ago",
                    "match_score": 88.0,
                    "matched_skills": ["Power BI", "DAX", "Power Query", "SQL"],
                    "missing_skills": [],
                    "description": "Enterprise BI reporting with Power BI Service and RLS.",
                    "resume_variant": "power_bi_developer",
                    "url": "https://www.capgemini.com/jobs/power-bi-202",
                    "is_applied": False,
                    "application_status": "Apply Button Not Available (External Redirect)",
                    "applied_result_display": "",
                },
                # Job 3: Below 80% -> MUST NOT appear in Excel at all
                {
                    "company": "LowMatchCo",
                    "title": "General Operations",
                    "portal_step": "Step 3: ZipRecruiter",
                    "match_score": 68.0,
                    "url": "https://example.com/low",
                    "is_applied": False,
                },
            ]

            saved = update_applied_companies_excel(
                jobs,
                ["Deloitte", "Capgemini"],
                excel_path=excel_file,
                history_path=history_file,
            )
            self.assertTrue(saved.exists())

            wb = openpyxl.load_workbook(saved)
            self.assertIn(PRIMARY_SHEET_NAME, wb.sheetnames)
            self.assertIn("Target_Companies_CheckSheet", wb.sheetnames)
            self.assertIn("Resume_Skills_Analysis", wb.sheetnames)

            ws = wb[PRIMARY_SHEET_NAME]
            self.assertEqual([ws.cell(1, c).value for c in range(1, 6)], STRUCTURED_HEADERS)
            # Header + 2 >=80% rows (68% job excluded!)
            self.assertEqual(ws.max_row, 3)

            # Row 2 (Applied job): Shows APPLIED result, NO http link, NO hyperlink!
            row2_col5 = ws.cell(2, 5)
            self.assertIn("APPLIED:", str(row2_col5.value))
            self.assertIn("Applied (LinkedIn Easy Apply)", str(row2_col5.value))
            self.assertNotIn("http", str(row2_col5.value))
            self.assertIsNone(row2_col5.hyperlink)

            # Row 3 (Unapplied job): Shows Apply Link AND has clickable hyperlink!
            row3_col5 = ws.cell(3, 5)
            self.assertIn("Apply Link: https://www.capgemini.com/jobs/power-bi-202", str(row3_col5.value))
            self.assertIsNotNone(row3_col5.hyperlink)
            self.assertEqual(row3_col5.hyperlink.target, "https://www.capgemini.com/jobs/power-bi-202")
            wb.close()

            # Applied URL persisted in history file for duplicate prevention
            applied_urls = load_applied_urls(history_path=history_file, excel_path=excel_file)
            self.assertIn("https://www.linkedin.com/jobs/view/90001", applied_urls)
            self.assertNotIn("https://www.capgemini.com/jobs/power-bi-202", applied_urls)

            # Queued loader returns ONLY Row 3 (unapplied link row)
            queued = get_queued_jobs_from_excel(excel_path=excel_file)
            self.assertEqual(len(queued), 1)
            self.assertEqual(queued[0]["company"], "Capgemini")
            self.assertEqual(queued[0]["excel_row"], 3)

            # If --continue later applies to Row 3, Column 5 replaces link with APPLIED result!
            queued[0]["applied_result_display"] = "Applied (Company Career Portal) | Resume: power_bi_developer"
            update_single_job_status_in_excel(
                3,
                "Applied (Company Career Portal)",
                job=queued[0],
                excel_path=excel_file,
                history_path=history_file,
            )
            wb2 = openpyxl.load_workbook(excel_file)
            ws2 = wb2[PRIMARY_SHEET_NAME]
            updated_cell = ws2.cell(3, 5)
            self.assertIn("APPLIED:", str(updated_cell.value))
            self.assertNotIn("http", str(updated_cell.value))
            self.assertIsNone(updated_cell.hyperlink)
            wb2.close()

    def test_root_workflow_bridge_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_xlsx = Path(tmp) / "Matched_Jobs_Output.xlsx"
            export_records_to_structured_excel(
                [
                    {
                        "company": "NTT DATA",
                        "title": "AI Data Analyst",
                        "source": "linkedin",
                        "posted_date": "Today",
                        "resume_match_pct": 91,
                        "matched_skills": ["Python", "SQL", "Power BI"],
                        "missing_skills": [],
                        "url": "https://linkedin.com/jobs/view/555",
                        "is_applied": True,
                        "application_status": "Applied (LinkedIn Easy Apply)",
                        "applied_result_display": "Applied (LinkedIn Easy Apply) | Resume: GenAI",
                    }
                ],
                out_xlsx,
            )
            wb = openpyxl.load_workbook(out_xlsx)
            ws = wb[PRIMARY_SHEET_NAME]
            self.assertEqual(ws.max_row, 2)
            self.assertIn("APPLIED:", str(ws.cell(2, 5).value))
            self.assertNotIn("http", str(ws.cell(2, 5).value))
            wb.close()


if __name__ == "__main__":
    unittest.main()
