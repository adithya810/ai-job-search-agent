"""Stage 06: Structured Excel Output (`Matched_Jobs_Output` + Summary Tabs).

Writes verified >= 80% matched jobs into `Applied_Companies_Tracker.xlsx` using the
5-column structured layout from the Agentic Workflow Architecture:
  1. Company Name
  2. Matched & JD Skills
  3. Job Description (JD)
  4. Job Role & Match %
  5. Portal, Posted Date & Applied Result / Apply Link:
     - When an Apply button was available and submitted (`is_applied == True`):
       displays the APPLIED RESULT & confirmation details INSTEAD OF the apply link!
     - When no direct Apply button was available (`is_applied == False`):
       displays the clickable Direct Apply Link (URL).
"""

from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from auto_applier import is_status_applied
from config import (
    APPLIED_COMPANIES_EXCEL,
    APPLIED_JOBS_HISTORY_PATH,
    CANDIDATE_PROFILE,
    OFFICIAL_COMPANY_PORTALS,
)
from matcher import summarize_job_description

PRIMARY_SHEET_NAME = "Matched_Jobs_Output"
STRUCTURED_HEADERS = [
    "Company Name",
    "Matched & JD Skills",
    "Job Description (JD)",
    "Job Role & Match %",
    "Portal, Posted Date & Applied Result / Apply Link",
]


def get_ist_now_str() -> str:
    ist = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(ist).strftime("%Y-%m-%d %I:%M %p IST")


def _normalize_url(url: str) -> str:
    return (url or "").split("#")[0].rstrip("/").strip()


def load_applied_urls(
    history_path: Path = APPLIED_JOBS_HISTORY_PATH,
    excel_path: Path = APPLIED_COMPANIES_EXCEL,
) -> set:
    """Loads URLs of all previously submitted/applied jobs to prevent duplicate applications."""
    applied: set = set()

    if history_path.exists():
        try:
            payload = json.loads(history_path.read_text(encoding="utf-8"))
            for u in payload.get("applied_urls", []):
                if u:
                    applied.add(_normalize_url(str(u)))
        except Exception:
            pass

    if excel_path.exists():
        try:
            wb = openpyxl.load_workbook(excel_path, data_only=True)
            if "Applied_Jobs_Tracker" in wb.sheetnames:
                ws_legacy = wb["Applied_Jobs_Tracker"]
                for r in range(2, ws_legacy.max_row + 1):
                    status = str(ws_legacy.cell(r, 11).value or "")
                    url = _normalize_url(str(ws_legacy.cell(r, 13).value or ""))
                    if url and is_status_applied(status):
                        applied.add(url)
            wb.close()
        except Exception as exc:
            print(f"[Tracker] Note loading applied URLs: {exc}")

    return applied


def record_applied_jobs(
    jobs: List[Dict[str, Any]],
    history_path: Path = APPLIED_JOBS_HISTORY_PATH,
) -> None:
    """Persists applied job URLs & metadata so future runs skip duplicates even when Excel hides URLs."""
    existing_urls = load_applied_urls(history_path=history_path)
    records: List[Dict[str, str]] = []
    if history_path.exists():
        try:
            old_data = json.loads(history_path.read_text(encoding="utf-8"))
            records = list(old_data.get("applied_records", []))
        except Exception:
            records = []

    seen_rec_urls = {_normalize_url(r.get("url", "")) for r in records if r.get("url")}
    for j in jobs:
        applied_flag = bool(j.get("is_applied")) or is_status_applied(str(j.get("application_status") or ""))
        if not applied_flag:
            continue
        norm_u = _normalize_url(str(j.get("url") or ""))
        if norm_u:
            existing_urls.add(norm_u)
            if norm_u not in seen_rec_urls:
                seen_rec_urls.add(norm_u)
                records.append(
                    {
                        "url": norm_u,
                        "company": str(j.get("company") or ""),
                        "title": str(j.get("title") or ""),
                        "status": str(j.get("application_status") or "Applied"),
                        "recorded_at_ist": get_ist_now_str(),
                    }
                )

    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(
        json.dumps(
            {
                "updated_at_ist": get_ist_now_str(),
                "applied_urls": sorted(existing_urls),
                "applied_records": records,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def format_portal_action_cell(job: Dict[str, Any]) -> tuple[str, bool, str]:
    """Builds Column 5 value (`cell_text, is_applied, link_url`).

    Rule:
      - If applied (`is_applied == True`): returns APPLIED RESULT instead of apply link (`link_url == ""`).
      - Otherwise: returns Portal + Posted Date + Direct Apply Link (`link_url == direct_url`).
    """
    portal_label = (job.get("portal_step") or job.get("portal") or "Portal").strip()
    posted_age = (job.get("posted_date") or "Within 48 hours").strip()
    status = (job.get("application_status") or "").strip()
    applied_flag = bool(job.get("is_applied")) or is_status_applied(status)

    if applied_flag:
        detail = (job.get("applied_result_display") or status or "Applied Successfully").strip()
        # Strip any accidental raw URL from applied display so ONLY applied result appears
        detail_no_url = re.sub(r"https?://\S+", "", detail).strip(" |-")
        text = f"{portal_label} | Posted: {posted_age} | APPLIED: {detail_no_url}"
        return text, True, ""

    direct_url = (job.get("external_apply_url") or job.get("url") or "").strip()
    text = f"{portal_label} | Posted: {posted_age} | Apply Link: {direct_url}"
    return text, False, direct_url


def update_applied_companies_excel(
    matched_jobs: List[Dict[str, Any]],
    target_companies: List[str],
    *,
    excel_path: Path = APPLIED_COMPANIES_EXCEL,
    history_path: Path = APPLIED_JOBS_HISTORY_PATH,
    career_pages: Optional[List[Dict[str, str]]] = None,
) -> Path:
    """Creates or updates `Applied_Companies_Tracker.xlsx` with:
      1. `Matched_Jobs_Output` (5-column structured sheet with Applied Result vs Apply Link)
      2. `Target_Companies_CheckSheet`
      3. `Resume_Skills_Analysis`
    """
    # Filter defensively: only >= 80% matched jobs may ever be written to Output Excel
    verified_jobs = [j for j in matched_jobs if float(j.get("match_score", 0.0)) >= 80.0]

    record_applied_jobs(verified_jobs, history_path=history_path)

    if excel_path.exists():
        try:
            wb = openpyxl.load_workbook(excel_path)
        except Exception:
            wb = openpyxl.Workbook()
    else:
        wb = openpyxl.Workbook()

    header_fill = PatternFill(start_color="102A43", end_color="102A43", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True, size=10.5)
    applied_fill = PatternFill(start_color="E6F4EA", end_color="E6F4EA", fill_type="solid")
    applied_font = Font(color="137333", bold=True, size=10)
    link_font = Font(color="0563C1", underline="single", size=10)
    body_font = Font(color="1F2933", size=10)
    thin_border = Border(
        left=Side(style="thin", color="D9E2EC"),
        right=Side(style="thin", color="D9E2EC"),
        top=Side(style="thin", color="D9E2EC"),
        bottom=Side(style="thin", color="D9E2EC"),
    )

    # 1. Primary Sheet: Matched_Jobs_Output
    if PRIMARY_SHEET_NAME in wb.sheetnames:
        ws = wb[PRIMARY_SHEET_NAME]
    else:
        if len(wb.sheetnames) == 1 and wb.active.max_row <= 1 and wb.active.title == "Sheet":
            ws = wb.active
            ws.title = PRIMARY_SHEET_NAME
        else:
            ws = wb.create_sheet(PRIMARY_SHEET_NAME, 0)
        ws.append(STRUCTURED_HEADERS)
        ws.row_dimensions[1].height = 28
        for col_idx in range(1, len(STRUCTURED_HEADERS) + 1):
            c = ws.cell(1, col_idx)
            c.fill = header_fill
            c.font = header_font
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    # Ensure Matched_Jobs_Output is the first sheet
    if wb.sheetnames[0] != PRIMARY_SHEET_NAME:
        wb.move_sheet(ws, offset=-wb.sheetnames.index(PRIMARY_SHEET_NAME))

    for job in verified_jobs:
        comp = (job.get("company") or "Hiring Organization").strip()
        in_sheet = any(tc.lower() in comp.lower() for tc in target_companies if tc)
        comp_cell = f"{comp}\n[Target Sheet]" if in_sheet else comp

        matched_list = job.get("matched_skills") or []
        missing_list = job.get("missing_skills") or []
        matched_str = ", ".join(matched_list) if isinstance(matched_list, list) else str(matched_list)
        missing_str = ", ".join(missing_list) if isinstance(missing_list, list) and missing_list else "None"
        skills_cell = f"Matched: {matched_str or 'Core Analytics'}\nMissing / Bonus: {missing_str}"

        jd_cell = job.get("jd_summary") or summarize_job_description(job)

        title = (job.get("title") or "Data Analyst").strip()
        score = float(job.get("match_score", 80.0))
        resume_variant = (job.get("resume_variant") or "data_analyst").strip()
        role_score_cell = f"{title} — {score:.1f}% Match\nResume: {resume_variant}"

        action_cell_text, is_applied, link_url = format_portal_action_cell(job)

        row_vals = [
            comp_cell,
            skills_cell,
            jd_cell,
            role_score_cell,
            action_cell_text,
        ]
        ws.append(row_vals)
        r_idx = ws.max_row
        for c_idx in range(1, len(row_vals) + 1):
            cell = ws.cell(r_idx, c_idx)
            cell.border = thin_border
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            cell.font = body_font
            if c_idx == 5:
                if is_applied:
                    cell.hyperlink = None
                    cell.fill = applied_fill
                    cell.font = applied_font
                elif link_url.startswith("http"):
                    cell.hyperlink = link_url
                    cell.font = link_font

    col_widths = [26, 44, 54, 34, 56]
    for i, w in enumerate(col_widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # 2. Target_Companies_CheckSheet
    if "Target_Companies_CheckSheet" in wb.sheetnames:
        del wb["Target_Companies_CheckSheet"]
    ws_tc = wb.create_sheet("Target_Companies_CheckSheet")
    tc_headers = [
        "Company Name",
        "Official Career Portal",
        "Matched Openings (>=80%)",
        "Highest Match %",
        "Top Matched Role",
        "Matched Resume Skills",
        "Latest Action / Status",
    ]
    ws_tc.append(tc_headers)
    for col_idx in range(1, len(tc_headers) + 1):
        c = ws_tc.cell(1, col_idx)
        c.fill = header_fill
        c.font = header_font

    career_url_lookup: Dict[str, str] = {}
    if career_pages:
        for cp in career_pages:
            career_url_lookup[cp.get("company", "").lower()] = cp.get("careers_url", "")
            career_url_lookup[cp.get("raw_company", "").lower()] = cp.get("careers_url", "")

    for tc in target_companies:
        key = tc.lower().strip()
        c_url = career_url_lookup.get(key, "")
        if not c_url:
            portal_cfg = OFFICIAL_COMPANY_PORTALS.get(key, {})
            if not portal_cfg:
                for k, v in OFFICIAL_COMPANY_PORTALS.items():
                    if k in key or key in k:
                        portal_cfg = v
                        break
            c_url = portal_cfg.get("careers_url", "")

        c_jobs = [j for j in verified_jobs if tc.lower() in (j.get("company") or "").lower()]
        top_j = max(c_jobs, key=lambda item: float(item.get("match_score", 0.0))) if c_jobs else {}
        if top_j:
            top_action, top_applied, _ = format_portal_action_cell(top_j)
            status_summary = top_action if top_applied else (top_j.get("application_status") or "Apply Link Saved")
        else:
            status_summary = "Monitored (No <=48h >=80% Opening)"

        ws_tc.append(
            [
                tc,
                c_url,
                len(c_jobs),
                f"{float(top_j['match_score']):.1f}%" if top_j else "N/A",
                top_j.get("title", "—") if top_j else "—",
                ", ".join(top_j.get("matched_skills", [])) if top_j else "—",
                status_summary,
            ]
        )
    for i, w in enumerate([24, 50, 24, 16, 36, 44, 42], start=1):
        ws_tc.column_dimensions[get_column_letter(i)].width = w

    # 3. Resume_Skills_Analysis
    if "Resume_Skills_Analysis" in wb.sheetnames:
        del wb["Resume_Skills_Analysis"]
    ws_sk = wb.create_sheet("Resume_Skills_Analysis")
    sk_headers = ["Skill Category", "Candidate Resume Skill", "Jobs Matching Skill (>=80%)", "Demand Share (%)"]
    ws_sk.append(sk_headers)
    for col_idx in range(1, len(sk_headers) + 1):
        c = ws_sk.cell(1, col_idx)
        c.fill = header_fill
        c.font = header_font

    skill_counts = Counter()
    for j in verified_jobs:
        for sk in j.get("matched_skills", []):
            skill_counts[sk] += 1

    total_j = max(1, len(verified_jobs))
    for cat, sk_list in CANDIDATE_PROFILE.get("skill_categories", {}).items():
        for sk in sk_list:
            cnt = sum(v for k, v in skill_counts.items() if sk.lower() in k.lower() or k.lower() in sk.lower())
            pct = round((cnt / total_j) * 100.0, 1) if verified_jobs else 0.0
            ws_sk.append([cat, sk, cnt, f"{pct}%"])

    for i, w in enumerate([34, 32, 26, 18], start=1):
        ws_sk.column_dimensions[get_column_letter(i)].width = w

    excel_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        wb.save(excel_path)
        return excel_path
    except PermissionError:
        alt_path = excel_path.parent / f"{excel_path.stem}_Live.xlsx"
        wb.save(alt_path)
        return alt_path


def get_queued_jobs_from_excel(excel_path: Path = APPLIED_COMPANIES_EXCEL) -> List[Dict[str, Any]]:
    """Loads unapplied rows (those still carrying an Apply Link) from `Matched_Jobs_Output`."""
    queued_jobs: List[Dict[str, Any]] = []
    if not excel_path.exists():
        return queued_jobs
    try:
        wb = openpyxl.load_workbook(excel_path, data_only=False)
        if PRIMARY_SHEET_NAME in wb.sheetnames:
            ws = wb[PRIMARY_SHEET_NAME]
            for r in range(2, ws.max_row + 1):
                comp_raw = str(ws.cell(r, 1).value or "").splitlines()[0].strip()
                skills_raw = str(ws.cell(r, 2).value or "")
                jd_raw = str(ws.cell(r, 3).value or "")
                role_raw = str(ws.cell(r, 4).value or "")
                action_cell = ws.cell(r, 5)
                action_val = str(action_cell.value or "")

                if "APPLIED:" in action_val:
                    continue

                url = ""
                if action_cell.hyperlink and action_cell.hyperlink.target:
                    url = str(action_cell.hyperlink.target).strip()
                if not url:
                    m_url = re.search(r"(https?://\S+)", action_val)
                    if m_url:
                        url = m_url.group(1).strip()

                if not url.startswith("http"):
                    continue

                title_part = role_raw.splitlines()[0]
                m_score = re.search(r"—\s*(\d+(?:\.\d+)?)%\s*Match", title_part)
                score = float(m_score.group(1)) if m_score else 85.0
                title = re.sub(r"\s*—\s*\d+(?:\.\d+)?%\s*Match.*$", "", title_part).strip()

                parts = [p.strip() for p in action_val.split("|")]
                portal = parts[0] if parts else "Portal"
                posted_date = parts[1].replace("Posted:", "").strip() if len(parts) > 1 else "Within 48 hours"

                queued_jobs.append(
                    {
                        "excel_row": r,
                        "company": comp_raw or "Company",
                        "title": title or "Data Analyst",
                        "portal": portal,
                        "portal_step": portal,
                        "posted_date": posted_date,
                        "match_score": score,
                        "skills": skills_raw,
                        "description": jd_raw,
                        "url": url,
                        "application_status": "Queued (Apply Link)",
                    }
                )
        wb.close()
    except Exception as exc:
        print(f"[Excel Tracker] Error loading queued jobs: {exc}")
    return queued_jobs


def update_single_job_status_in_excel(
    row_idx: int,
    new_status: str,
    new_notes: str = "",
    *,
    job: Optional[Dict[str, Any]] = None,
    excel_path: Path = APPLIED_COMPANIES_EXCEL,
    history_path: Path = APPLIED_JOBS_HISTORY_PATH,
) -> None:
    """Updates Row `row_idx` in `Matched_Jobs_Output`: replaces Apply Link with APPLIED result if applied."""
    if not excel_path.exists() or not row_idx:
        return
    try:
        wb = openpyxl.load_workbook(excel_path)
        if PRIMARY_SHEET_NAME in wb.sheetnames:
            ws = wb[PRIMARY_SHEET_NAME]
            cell = ws.cell(row_idx, 5)
            applied_ok = is_status_applied(new_status) or bool(job and job.get("is_applied"))
            if applied_ok:
                portal_label = (job.get("portal_step") or job.get("portal") or "Portal") if job else "Portal"
                posted_age = (job.get("posted_date") or "Within 48 hours") if job else "Within 48 hours"
                detail = (job.get("applied_result_display") if job else "") or f"{new_status} | {get_ist_now_str()}"
                detail_clean = re.sub(r"https?://\S+", "", detail).strip(" |-")
                cell.value = f"{portal_label} | Posted: {posted_age} | APPLIED: {detail_clean}"
                cell.hyperlink = None
                cell.fill = PatternFill(start_color="E6F4EA", end_color="E6F4EA", fill_type="solid")
                cell.font = Font(color="137333", bold=True, size=10)
                if job:
                    job["is_applied"] = True
                    job["application_status"] = new_status
                    record_applied_jobs([job], history_path=history_path)
            wb.save(excel_path)
        wb.close()
    except Exception as exc:
        print(f"[Excel Tracker] Single row update note: {exc}")
