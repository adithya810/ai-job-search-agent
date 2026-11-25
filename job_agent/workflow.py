"""Unified 6-Stage Agentic Workflow & Structured Excel Exporter for `job_agent` and `agent_runner`.

Implements:
  01 • Inputs & Extraction   — Parse Resume(s) (PDF/DOCX/Text) + `Company name.xlsx` Career URLs
  02 • Agent Memory State    — Persist `output/agent_memory_state.json`
  03 • Sequential 48h Search — Role-by-role `1. LinkedIn -> 2. Naukri -> 3. ZipRecruiter -> 4. Career Pages`
  04 • >=80% Match Gate      — Cross-portal JD deduplication, <=48h freshness, >=80% resume skill match
  05 • Apply Button Gate     — Auto-apply when Apply button is available; otherwise keep Direct Apply Link
  06 • Structured Excel      — Write `Applied_Companies_Tracker.xlsx` / `output/Matched_Jobs_Output.xlsx`
                               displaying `APPLIED: <result>` INSTEAD OF Apply Link when applied
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
UPLOADED_AGENT_DIR = PROJECT_ROOT / "uploaded_agent"


def _ensure_uploaded_agent_importable() -> None:
    path_str = str(UPLOADED_AGENT_DIR)
    if UPLOADED_AGENT_DIR.exists() and path_str not in sys.path:
        sys.path.insert(0, path_str)


def export_records_to_structured_excel(
    records: list[dict[str, Any]],
    output_excel_path: Path,
    *,
    target_companies: list[str] | None = None,
    career_pages: list[dict[str, str]] | None = None,
    history_path: Path | None = None,
) -> Path:
    """Exports >=80% matched job records into the 5-column Structured Excel sheet.

    Column 5 (`Portal, Posted Date & Applied Result / Apply Link`) displays:
      - `APPLIED: <result>` (no hyperlink, no raw URL) when `is_applied` is True
      - `Apply Link: <url>` (clickable hyperlink) when `is_applied` is False
    """
    _ensure_uploaded_agent_importable()
    from excel_reporter import update_applied_companies_excel

    normalized_jobs: list[dict[str, Any]] = []
    for rec in records:
        score = float(rec.get("match_score") or rec.get("resume_match_pct") or 0.0)
        if score < 80.0:
            continue
        source_raw = str(rec.get("portal_step") or rec.get("portal") or rec.get("source") or "Portal")
        s_low = source_raw.lower()
        if not source_raw.startswith("Step "):
            if "linkedin" in s_low:
                portal_step = "Step 1: LinkedIn"
            elif "naukri" in s_low:
                portal_step = "Step 2: Naukri.com"
            elif "ziprecruiter" in s_low:
                portal_step = "Step 3: ZipRecruiter"
            else:
                portal_step = f"Step 4: Company Career Page ({source_raw})"
        else:
            portal_step = source_raw

        normalized_jobs.append(
            {
                "company": rec.get("company", "Hiring Organization"),
                "title": rec.get("title", "Data Analyst"),
                "portal": rec.get("portal") or rec.get("source") or "Portal",
                "portal_step": portal_step,
                "location": rec.get("location", "India"),
                "experience": rec.get("experience", "3-5 Years"),
                "posted_date": rec.get("posted_date") or "Within 48 hours",
                "match_score": score,
                "matched_skills": rec.get("matched_skills") or rec.get("matched_core_skills") or [],
                "missing_skills": rec.get("missing_skills") or rec.get("missing_core_skills") or [],
                "description": rec.get("description") or rec.get("fit_reason") or "",
                "jd_summary": rec.get("jd_summary"),
                "resume_variant": rec.get("resume_variant") or rec.get("best_resume_track") or "data_analyst",
                "url": rec.get("url", ""),
                "external_apply_url": rec.get("external_apply_url", ""),
                "is_applied": bool(rec.get("is_applied", False)),
                "application_status": rec.get("application_status", "Apply Link Saved"),
                "applied_result_display": rec.get("applied_result_display", ""),
            }
        )

    hist = history_path or (output_excel_path.parent / "applied_jobs_history.json")
    return update_applied_companies_excel(
        normalized_jobs,
        target_companies or [],
        excel_path=output_excel_path,
        history_path=hist,
        career_pages=career_pages,
    )


def run_six_stage_workflow(
    *,
    headless: bool = True,
    max_auto_apply: int = 25,
    search_only: bool = False,
    max_roles: int = 5,
    max_per_role: int = 5,
    output_excel_copy: Path | None = None,
) -> dict[str, Any]:
    """Executes the full 6-stage agentic workflow and optionally mirrors the output Excel."""
    _ensure_uploaded_agent_importable()
    import shutil
    from job_agent import run_job_search_and_apply as _run_uploaded_workflow

    summary = _run_uploaded_workflow(
        headless=headless,
        max_auto_apply=max_auto_apply,
        search_only=search_only,
        max_roles=max_roles,
        max_per_role=max_per_role,
    )
    src_excel = Path(summary["excel_tracker_path"])
    if output_excel_copy and src_excel.exists() and src_excel.resolve() != output_excel_copy.resolve():
        output_excel_copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_excel, output_excel_copy)
        summary["output_excel_copy"] = str(output_excel_copy)
    return summary
