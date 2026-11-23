from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
from pathlib import Path
from collections import Counter
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from config import (
    APPLIED_COMPANIES_EXCEL,
    CANDIDATE_PROFILE,
    OFFICIAL_COMPANY_PORTALS,
)


def get_ist_now_str() -> str:
    ist = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(ist).strftime("%Y-%m-%d %I:%M %p IST")


def load_applied_urls() -> set:
    """Loads URLs of all successfully submitted/applied jobs to prevent duplicate applications."""
    applied = set()
    if not APPLIED_COMPANIES_EXCEL.exists():
        return applied
    try:
        wb = openpyxl.load_workbook(APPLIED_COMPANIES_EXCEL, data_only=True)
        if "Applied_Jobs_Tracker" in wb.sheetnames:
            ws = wb["Applied_Jobs_Tracker"]
            for r in range(2, ws.max_row + 1):
                status = str(ws.cell(r, 11).value or "").lower()
                url = str(ws.cell(r, 13).value or "").strip()
                if url and ("applied (" in status or "applied / initiated" in status or "auto-submitted" in status):
                    applied.add(url)
        wb.close()
    except Exception as exc:
        print(f"[Tracker] Note loading applied URLs: {exc}")
    return applied


def update_applied_companies_excel(
    matched_jobs: List[Dict[str, Any]],
    target_companies: List[str],
) -> Path:
    """
    Creates or updates 'Applied_Companies_Tracker.xlsx' in the project folder
    with three tabs:
      1. Applied_Jobs_Tracker
      2. Target_Companies_CheckSheet
      3. Resume_Skills_Analysis
    """
    if APPLIED_COMPANIES_EXCEL.exists():
        try:
            wb = openpyxl.load_workbook(APPLIED_COMPANIES_EXCEL)
        except Exception:
            wb = openpyxl.Workbook()
    else:
        wb = openpyxl.Workbook()

    header_fill = PatternFill(start_color="12355B", end_color="12355B", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True, size=10)
    thin_border = Border(
        left=Side(style="thin", color="D9D9D9"),
        right=Side(style="thin", color="D9D9D9"),
        top=Side(style="thin", color="D9D9D9"),
        bottom=Side(style="thin", color="D9D9D9"),
    )

    # 1. Applied_Jobs_Tracker sheet
    if "Applied_Jobs_Tracker" in wb.sheetnames:
        ws = wb["Applied_Jobs_Tracker"]
    else:
        ws = wb.active
        ws.title = "Applied_Jobs_Tracker"
        headers = [
            "S.No",
            "Run Timestamp (IST)",
            "Company Name",
            "In Target Check-Sheet?",
            "Job Title / Designation",
            "Source Portal",
            "Location",
            "Experience Required",
            "Resume Match %",
            "Matched Resume Skills",
            "Application Status",
            "Resume Variant Used",
            "Direct Application URL",
            "Match Breakdown & Notes",
        ]
        ws.append(headers)
        for col_idx in range(1, len(headers) + 1):
            c = ws.cell(1, col_idx)
            c.fill = header_fill
            c.font = header_font
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    now_str = get_ist_now_str()
    start_sno = max(1, ws.max_row)

    for idx, job in enumerate(matched_jobs, start=start_sno):
        comp = job.get("company", "Hiring Organization")
        in_sheet = "Yes (Target Company)" if any(tc.lower() in comp.lower() for tc in target_companies) else "No"
        skills_list = job.get("matched_skills") or []
        skills_str = ", ".join(skills_list) if isinstance(skills_list, list) else str(skills_list)
        score = job.get("match_score", 85.0)
        url = job.get("url", "")

        row_vals = [
            idx,
            now_str,
            comp,
            in_sheet,
            job.get("title", "Data Analyst"),
            job.get("portal", "Portal"),
            job.get("location", "India"),
            job.get("experience", "0-4.5 Years"),
            f"{score}%",
            skills_str,
            job.get("application_status", "Queued"),
            job.get("resume_variant", "default"),
            url,
            job.get("notes", job.get("match_explanation", "")),
        ]
        ws.append(row_vals)
        r_idx = ws.max_row
        for c_idx in range(1, len(row_vals) + 1):
            cell = ws.cell(r_idx, c_idx)
            cell.border = thin_border
            cell.alignment = Alignment(vertical="top", wrap_text=(c_idx in (5, 10, 14)))
            if c_idx == 13 and url.startswith("http"):
                cell.hyperlink = url
                cell.font = Font(color="0563C1", underline="single")

    col_widths = [8, 22, 26, 20, 36, 24, 24, 16, 15, 48, 30, 22, 45, 55]
    for i, w in enumerate(col_widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # 2. Target_Companies_CheckSheet
    if "Target_Companies_CheckSheet" in wb.sheetnames:
        del wb["Target_Companies_CheckSheet"]
    ws_tc = wb.create_sheet("Target_Companies_CheckSheet")
    tc_headers = [
        "Company Name",
        "Official Career Portal",
        "Matched Openings Found",
        "Highest Match %",
        "Top Matched Role",
        "Matched Resume Skills",
        "Latest Status",
    ]
    ws_tc.append(tc_headers)
    for col_idx in range(1, len(tc_headers) + 1):
        c = ws_tc.cell(1, col_idx)
        c.fill = header_fill
        c.font = header_font

    for tc in target_companies:
        key = tc.lower().strip()
        portal_cfg = OFFICIAL_COMPANY_PORTALS.get(key, {})
        if not portal_cfg:
            for k, v in OFFICIAL_COMPANY_PORTALS.items():
                if k in key or key in k:
                    portal_cfg = v
                    break
        c_url = portal_cfg.get("careers_url", "")
        c_jobs = [j for j in matched_jobs if tc.lower() in (j.get("company") or "").lower()]
        top_j = c_jobs[0] if c_jobs else {}
        ws_tc.append([
            tc,
            c_url,
            len(c_jobs),
            f"{top_j.get('match_score', 90.0)}%" if top_j else "N/A",
            top_j.get("title", "Data Analyst / MIS Reporting"),
            ", ".join(top_j.get("matched_skills", ["Python", "SQL", "Power BI", "Advanced Excel"])),
            top_j.get("application_status", "Portal Monitored"),
        ])
    for i, w in enumerate([24, 50, 22, 16, 38, 45, 30], start=1):
        ws_tc.column_dimensions[get_column_letter(i)].width = w

    # 3. Resume_Skills_Analysis
    if "Resume_Skills_Analysis" in wb.sheetnames:
        del wb["Resume_Skills_Analysis"]
    ws_sk = wb.create_sheet("Resume_Skills_Analysis")
    sk_headers = ["Skill Category", "Adithya Resume Skill", "Jobs Matching This Skill", "Demand Share (%)"]
    ws_sk.append(sk_headers)
    for col_idx in range(1, len(sk_headers) + 1):
        c = ws_sk.cell(1, col_idx)
        c.fill = header_fill
        c.font = header_font

    skill_counts = Counter()
    for j in matched_jobs:
        for sk in j.get("matched_skills", []):
            skill_counts[sk] += 1

    total_j = max(1, len(matched_jobs))
    for cat, sk_list in CANDIDATE_PROFILE.get("skill_categories", {}).items():
        for sk in sk_list:
            cnt = sum(v for k, v in skill_counts.items() if sk.lower() in k.lower() or k.lower() in sk.lower())
            pct = round((cnt / total_j) * 100.0, 1)
            ws_sk.append([cat, sk, cnt, f"{pct}%"])

    for i, w in enumerate([34, 32, 24, 18], start=1):
        ws_sk.column_dimensions[get_column_letter(i)].width = w

    try:
        wb.save(APPLIED_COMPANIES_EXCEL)
        return APPLIED_COMPANIES_EXCEL
    except PermissionError:
        alt_path = APPLIED_COMPANIES_EXCEL.parent / "Applied_Companies_Tracker_Live.xlsx"
        wb.save(alt_path)
        return alt_path


def get_queued_jobs_from_excel() -> List[Dict[str, Any]]:
    queued_jobs: List[Dict[str, Any]] = []
    if not APPLIED_COMPANIES_EXCEL.exists():
        return queued_jobs
    try:
        wb = openpyxl.load_workbook(APPLIED_COMPANIES_EXCEL, data_only=True)
        if "Applied_Jobs_Tracker" in wb.sheetnames:
            ws = wb["Applied_Jobs_Tracker"]
            for r in range(2, ws.max_row + 1):
                status = str(ws.cell(r, 11).value or "")
                if any(kw in status.lower() for kw in ["queued", "direct link saved", "company site redirect"]):
                    comp = str(ws.cell(r, 3).value or "Company")
                    title = str(ws.cell(r, 5).value or "Data Analyst")
                    portal = str(ws.cell(r, 6).value or "Portal")
                    location = str(ws.cell(r, 7).value or "India")
                    exp = str(ws.cell(r, 8).value or "0-4.5 Years")
                    match_val = str(ws.cell(r, 9).value or "85%").replace("%", "").strip()
                    try:
                        match_score = float(match_val)
                    except ValueError:
                        match_score = 85.0
                    skills = str(ws.cell(r, 10).value or "")
                    url = str(ws.cell(r, 13).value or "").strip()
                    notes = str(ws.cell(r, 14).value or "")
                    if url and url.startswith("http"):
                        queued_jobs.append({
                            "excel_row": r,
                            "company": comp,
                            "title": title,
                            "portal": portal,
                            "location": location,
                            "experience": exp,
                            "match_score": match_score,
                            "skills": skills,
                            "url": url,
                            "notes": notes,
                            "application_status": status,
                        })
        wb.close()
    except Exception as exc:
        print(f"[Excel Tracker] Error loading queued jobs: {exc}")
    return queued_jobs


def update_single_job_status_in_excel(row_idx: int, new_status: str, new_notes: str) -> None:
    if not APPLIED_COMPANIES_EXCEL.exists() or not row_idx:
        return
    try:
        wb = openpyxl.load_workbook(APPLIED_COMPANIES_EXCEL)
        if "Applied_Jobs_Tracker" in wb.sheetnames:
            ws = wb["Applied_Jobs_Tracker"]
            ws.cell(row_idx, 11, new_status)
            ws.cell(row_idx, 14, new_notes)
            wb.save(APPLIED_COMPANIES_EXCEL)
        wb.close()
    except Exception as exc:
        print(f"[Excel Tracker] Single row update note: {exc}")
