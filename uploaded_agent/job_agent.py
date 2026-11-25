"""Main Orchestrator for the 6-Stage Job Search & Conditional Auto-Apply Agentic Workflow.

Architecture Pipeline:
  Stage 01 • Inputs & Extraction   — Parse Candidate Resume (PDF/DOCX/Text) + Load `Company name.xlsx` Career URLs
  Stage 02 • Agent Memory State    — Persist `target_roles[]`, `resume_skills[]`, `search_keywords[]`, `48h` window
  Stage 03 • Sequential 48h Search — Execute Steps `1 (LinkedIn) -> 2 (Naukri) -> 3 (ZipRecruiter) -> 4 (Career Pages)`
  Stage 04 • AI Scoring & >=80%    — Deduplicate JDs, verify <=48h, score JD vs Resume Skills, filter `< 80%`
  Stage 05 • Apply Button Gate     — If Apply button is available, auto-apply with matched resume; else keep link
  Stage 06 • Structured Excel      — Write `>= 80%` matches to `Applied_Companies_Tracker.xlsx`, showing
                                     `APPLIED: <result>` INSTEAD OF Apply Link when applied, or clickable Apply Link
"""

import argparse
from collections import Counter
import json
from pathlib import Path
import shutil
import sys
import time
from typing import Any, Dict, List

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except Exception:
    pass

from playwright.sync_api import sync_playwright

from agent_memory import AgentMemoryState
from auto_applier import (
    attempt_auto_apply,
    is_status_applied,
    select_resume_for_job,
    try_login_indeed,
    try_login_linkedin,
    try_login_naukri,
)
from config import (
    AGENT_MEMORY_STATE_PATH,
    BASE_DIR,
    BROWSER_PROFILE_DIR,
    CANDIDATE_PROFILE,
    JOB_DISCOVERY_LOG,
    LOGIN_EMAIL,
    MATCH_THRESHOLD_PERCENT,
)
from excel_reporter import (
    get_ist_now_str,
    get_queued_jobs_from_excel,
    load_applied_urls,
    update_applied_companies_excel,
    update_single_job_status_in_excel,
)
from matcher import evaluate_and_gate_jobs
from resume_builder import ensure_resume_files
from scrapers import run_sequential_48h_search


def _is_naukri_job(job: Dict[str, Any]) -> bool:
    return "naukri" in (job.get("portal") or "").lower() or "naukri.com" in (job.get("url") or "").lower()


def prepare_resumes_and_order(jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    for job in jobs:
        resume_path, resume_key, resume_reason = select_resume_for_job(job)
        job["resume_path"] = str(resume_path)
        job["resume_variant"] = resume_key
        job["resume_reason"] = resume_reason

    others = [j for j in jobs if not _is_naukri_job(j)]
    naukri = sorted((j for j in jobs if _is_naukri_job(j)), key=lambda j: j.get("resume_variant", ""))
    return others + naukri


def get_browser_context(p, headless: bool = True):
    """Connects to live Chrome via CDP (port 9222) if running, else launches persistent Chromium profile."""
    import urllib.request

    cdp_available = False
    try:
        with urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=0.8):
            cdp_available = True
    except Exception:
        cdp_available = False

    if cdp_available:
        try:
            print("[Chrome Integration] Attaching to running Chrome browser on port 9222...")
            browser = p.chromium.connect_over_cdp("http://localhost:9222")
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            print(f"[Chrome Integration] Attached! Active session ({LOGIN_EMAIL}) reused.")
            return browser, context, True
        except Exception as exc:
            print(f"[Chrome Integration] CDP note: {exc}")

    for channel_opt in [None, "chrome"]:
        try:
            kwargs = {
                "user_data_dir": str(BROWSER_PROFILE_DIR),
                "headless": headless,
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ],
                "user_agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                "viewport": {"width": 1366, "height": 768},
            }
            if channel_opt:
                kwargs["channel"] = channel_opt
            context = p.chromium.launch_persistent_context(**kwargs)
            _ = context.pages[0] if context.pages else context.new_page()
            return None, context, False
        except Exception:
            continue

    raise RuntimeError("Could not launch Playwright browser context.")


def ensure_page(context, page=None):
    try:
        if page is not None and not page.is_closed():
            return page
    except Exception:
        pass
    try:
        return context.new_page()
    except Exception:
        return page


def mirror_project_folders() -> None:
    """On Windows only, keeps 'E:\\job search agent' and 'E:\\jobsearch python agent' synchronized."""
    if sys.platform != "win32":
        return
    folders = [Path(r"E:\job search agent"), Path(r"E:\jobsearch python agent")]
    src = BASE_DIR
    for dst in folders:
        if dst.resolve() == src.resolve():
            continue
        try:
            dst.mkdir(parents=True, exist_ok=True)
            for item in src.iterdir():
                if item.name in (".chrome_profile", "__pycache__", ".git", ".venv"):
                    continue
                target = dst / item.name
                if item.is_file():
                    shutil.copy2(item, target)
                elif item.is_dir() and item.name == "resumes":
                    target.mkdir(parents=True, exist_ok=True)
                    for sub in item.iterdir():
                        if sub.is_file():
                            shutil.copy2(sub, target / sub.name)
        except Exception as exc:
            print(f"[Sync Note] Mirror to {dst}: {exc}")


def setup_interactive_login() -> None:
    BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    print("=" * 75)
    print("[AI Job Agent] Launching Interactive Session Setup...")
    print(f"Browser Profile Storage: {BROWSER_PROFILE_DIR}")
    print("=" * 75)

    with sync_playwright() as p:
        browser_ref, context, is_attached = get_browser_context(p, headless=False)
        urls = [
            "https://accounts.google.com",
            "https://www.linkedin.com/login",
            "https://www.naukri.com/nlogin/login",
            "https://in.indeed.com/",
            "https://www.glassdoor.co.in/",
            "https://www.ziprecruiter.in/",
        ]
        for idx, u in enumerate(urls):
            pg = context.pages[0] if (idx == 0 and context.pages) else context.new_page()
            try:
                pg.goto(u, timeout=20000)
            except Exception:
                pass
        try:
            input("Press Enter after logging in to save session...")
        except EOFError:
            time.sleep(30)
        if not is_attached:
            context.close()
        else:
            browser_ref.disconnect()


def run_job_search_and_apply(
    headless: bool = True,
    max_auto_apply: int = 25,
    indeed_only: bool = False,
    search_only: bool = False,
    max_roles: int = 5,
    max_per_role: int = 5,
) -> Dict[str, Any]:
    print("=" * 78)
    print(f"[AI Job Agent] Starting Restructured 6-Stage Agentic Workflow at {get_ist_now_str()}")
    print(f"[AI Job Agent] Candidate: {CANDIDATE_PROFILE['full_name']} ({LOGIN_EMAIL})")
    print(f"[AI Job Agent] Pipeline : Resume Parse -> Memory State -> Sequential 48h Search (1->4)")
    print(f"                          -> >=80% Match Gate -> Apply Button Auto-Apply -> Excel Sheet")
    print("=" * 78)

    BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    # STAGE 01 & STAGE 02: Inputs & Extraction -> Shared Agent Memory State
    resume_pdf = ensure_resume_files()
    memory = AgentMemoryState.build_and_persist(state_path=AGENT_MEMORY_STATE_PATH)
    print(
        f"[Stage 01 & 02] Parsed {len(memory.resume_skills)} skills & {len(memory.target_roles)} roles "
        f"from {memory.resume_sources_parsed}; loaded {len(memory.career_pages)} career URLs from 'Company name.xlsx'."
    )
    print(f"                Memory persisted to: {AGENT_MEMORY_STATE_PATH} (primary PDF: {resume_pdf.name})")

    # STAGE 03: Sequential 48h Search (Steps 1 -> 2 -> 3 -> 4 Role-by-Role)
    browser_available = False
    search_result: Dict[str, Any] = {"jobs": [], "step_counts": {}}
    try:
        with sync_playwright() as p:
            browser_ref, context, is_attached = get_browser_context(p, headless=headless)
            browser_available = True
            page = context.pages[0] if context.pages else context.new_page()
            search_result = run_sequential_48h_search(
                memory,
                page=page,
                max_roles=max_roles,
                max_per_role=max_per_role,
            )
            if not is_attached:
                context.close()
            else:
                browser_ref.disconnect()
    except Exception as pw_err:
        print(f"[Stage 03] Browser note (running HTTP/API sequential fallback): {pw_err}")
        search_result = run_sequential_48h_search(
            memory,
            page=None,
            max_roles=max_roles,
            max_per_role=max_per_role,
        )

    raw_jobs: List[Dict[str, Any]] = search_result["jobs"]
    step_counts = search_result["step_counts"]

    # STAGE 04: AI Scoring & >=80% Filter Gate
    eval_result = evaluate_and_gate_jobs(raw_jobs, memory, threshold_pct=MATCH_THRESHOLD_PERCENT)
    matched_jobs: List[Dict[str, Any]] = eval_result["qualified_jobs"]
    gate_stats = eval_result["stats"]

    if indeed_only:
        matched_jobs = [
            j for j in matched_jobs
            if "indeed" in (j.get("portal") or "").lower() or "indeed.com" in (j.get("url") or "").lower()
        ]

    target_companies = memory.target_company_names

    def sort_priority(item):
        comp_in_sheet = any(tc.lower() in (item.get("company") or "").lower() for tc in target_companies)
        is_easy_apply = bool(item.get("easy_apply")) or any(
            k in (item.get("portal") or "").lower() for k in ("easy apply", "quick apply", "naukri")
        )
        return (comp_in_sheet, is_easy_apply, float(item.get("match_score", 0.0)))

    matched_jobs.sort(key=sort_priority, reverse=True)
    print(
        f"[Stage 04] >=80% Filter Gate: {len(matched_jobs)} qualified "
        f"(raw={gate_stats['raw_count']}, deduped={gate_stats['deduped_count']}, "
        f"rejected_stale_or_exp={gate_stats['stale_or_exp_rejected']}, "
        f"rejected_below_80={gate_stats['below_threshold_rejected']})"
    )

    # STAGE 05: Apply Button Gate & Conditional Auto-Apply
    previously_applied_urls = load_applied_urls()
    fresh_jobs: List[Dict[str, Any]] = []
    already_applied_count = 0

    for job in matched_jobs:
        norm_url = (job.get("url") or "").split("#")[0].rstrip("/").strip()
        resume_path, resume_key, resume_reason = select_resume_for_job(job)
        job["resume_path"] = str(resume_path)
        job["resume_variant"] = resume_key
        job["resume_reason"] = resume_reason

        if norm_url and norm_url in previously_applied_urls:
            job["is_applied"] = True
            job["apply_button_available"] = True
            job["application_status"] = "Already Applied (Previous Run)"
            job["applied_result_display"] = f"Already Applied (Previous Run) | Resume: {resume_key}"
            already_applied_count += 1
        else:
            fresh_jobs.append(job)

    ordered_jobs = prepare_resumes_and_order(fresh_jobs)
    submitted_count = 0

    if search_only or max_auto_apply <= 0 or not browser_available:
        print("[Stage 05] Auto-Apply disabled or headless API-only mode -> Preserving Direct Apply Links in Excel.")
        for job in ordered_jobs:
            job["is_applied"] = False
            job["apply_button_available"] = False
            job["application_status"] = "Apply Link Saved (Auto-Apply Skipped)"
            job["applied_result_display"] = ""
    else:
        print(f"[Stage 05] Checking Apply Button availability & executing Auto-Apply (cap={max_auto_apply})...")
        with sync_playwright() as p:
            browser_ref, context, is_attached = get_browser_context(p, headless=headless)
            page = context.pages[0] if context.pages else context.new_page()
            try_login_naukri(page)
            page = ensure_page(context, page)
            try_login_linkedin(page)
            page = ensure_page(context, page)
            try_login_indeed(page)

            for idx, job in enumerate(ordered_jobs, start=1):
                if submitted_count >= max_auto_apply or idx > max_auto_apply:
                    job["is_applied"] = False
                    job["apply_button_available"] = False
                    job["application_status"] = "Apply Link Saved (Cap Reached)"
                    job["applied_result_display"] = ""
                    continue

                comp_label = job.get("company", "Company")
                title_label = job.get("title", "Role")
                portal_label = job.get("portal_step") or job.get("portal", "Portal")
                resume_label = job.get("resume_variant", "data_analyst")
                print(
                    f"  [{idx}/{min(len(ordered_jobs), max_auto_apply)}] Checking Apply Button: "
                    f"{comp_label} — {title_label} ({portal_label}) | Resume: {resume_label}"
                )
                try:
                    page = ensure_page(context, page)
                    page.set_default_timeout(12000)
                    status, notes = attempt_auto_apply(page, job)
                except Exception as apply_err:
                    status = "Apply Link Available (Manual Apply)"
                    notes = f"Direct link preserved ({str(apply_err)[:80]})"
                    job["is_applied"] = False
                    job["apply_button_available"] = False
                    job["applied_result_display"] = ""

                job["application_status"] = status
                job["notes"] = notes
                if is_status_applied(status):
                    submitted_count += 1
                    print(f"     -> APPLIED via Apply Button: {status} (Excel will show Applied Result instead of link)")
                else:
                    print(f"     -> No Auto-Submit Button ({status}) -> Excel will show clickable Apply Link")

            if not is_attached:
                context.close()
            else:
                browser_ref.disconnect()

    # STAGE 06: Structured Excel Output
    excel_path = update_applied_companies_excel(
        matched_jobs,
        target_companies,
        career_pages=memory.career_pages,
    )
    applied_in_sheet = sum(1 for j in matched_jobs if j.get("is_applied"))
    links_in_sheet = len(matched_jobs) - applied_in_sheet
    print(
        f"[Stage 06] Structured Excel Output saved to: {excel_path}\n"
        f"           Rows written: {len(matched_jobs)} (>=80% only) | "
        f"Showing Applied Result: {applied_in_sheet} | Showing Apply Link: {links_in_sheet}"
    )

    skill_counter = Counter()
    resume_counter = Counter()
    for mj in matched_jobs:
        resume_counter[mj.get("resume_variant", "data_analyst")] += 1
        for sk in mj.get("matched_skills", []):
            skill_counter[sk] += 1

    skill_summary = [
        {"skill": sk, "matched_job_count": cnt, "share_pct": round((cnt / max(1, len(matched_jobs))) * 100.0, 1)}
        for sk, cnt in skill_counter.most_common()
    ]

    summary_payload = {
        "last_run_ist": get_ist_now_str(),
        "candidate": CANDIDATE_PROFILE["full_name"],
        "headline": CANDIDATE_PROFILE["target_designation"],
        "agent_memory_state_path": str(AGENT_MEMORY_STATE_PATH),
        "sequential_step_counts": step_counts,
        "gate_stats": gate_stats,
        "newly_applied_count": submitted_count,
        "previously_applied_count": already_applied_count,
        "links_preserved_count": links_in_sheet,
        "resume_variant_distribution": dict(resume_counter),
        "excel_tracker_path": str(excel_path),
        "resume_skills_matched_summary": skill_summary,
        "top_matched_jobs": matched_jobs[:60],
    }
    JOB_DISCOVERY_LOG.write_text(json.dumps(summary_payload, indent=2, ensure_ascii=False), encoding="utf-8")

    mirror_project_folders()

    print("=" * 78)
    print(f"[AI Job Agent] Workflow Complete! Excel: {excel_path.name}")
    print("=" * 78)
    return summary_payload


def continue_applying_queued_jobs(max_to_apply: int = 25, headless: bool = True) -> Dict[str, Any]:
    ensure_resume_files()
    queued = get_queued_jobs_from_excel()
    if not queued:
        return {"status": "complete", "message": "No unapplied link rows found in Excel", "applied": 0}

    to_process = prepare_resumes_and_order(queued[:max_to_apply])
    processed_results = []

    with sync_playwright() as p:
        browser_ref, context, is_attached = get_browser_context(p, headless=headless)
        page = context.pages[0] if context.pages else context.new_page()
        for job in to_process:
            row = job.get("excel_row")
            try:
                page = ensure_page(context, page)
                status, notes = attempt_auto_apply(page, job)
            except Exception as apply_err:
                status = "Apply Link Available (Manual Apply)"
                notes = f"Error: {str(apply_err)[:80]}"
            update_single_job_status_in_excel(row, status, notes, job=job)
            processed_results.append(
                {
                    "company": job.get("company"),
                    "title": job.get("title"),
                    "portal": job.get("portal"),
                    "status": status,
                    "replaced_link_with_applied_result": is_status_applied(status),
                }
            )
        if not is_attached:
            context.close()
        else:
            browser_ref.disconnect()

    mirror_project_folders()
    return {"last_run_ist": get_ist_now_str(), "processed_jobs": processed_results}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Restructured 6-Stage AI Job Search & Conditional Auto-Apply Agent")
    parser.add_argument("--headed", action="store_true", help="Run browser in visible window mode")
    parser.add_argument("--max-apply", type=int, default=25, help="Maximum auto-applications per run")
    parser.add_argument("--max-roles", type=int, default=5, help="Number of target roles in Sequential Loop 1->4")
    parser.add_argument("--max-per-role", type=int, default=5, help="Max listings per role+location per step")
    parser.add_argument("--search-only", action="store_true", help="Skip auto-apply and output clickable Apply Links for >=80%% matches")
    parser.add_argument("--setup-login", action="store_true", help="Open visible browser to log into job portals once")
    parser.add_argument("--refresh-naukri", action="store_true", help="Run daily Naukri profile keyword refresh")
    parser.add_argument("--indeed-only", action="store_true", help="Filter strictly on Indeed India jobs")
    parser.add_argument("--continue", "-c", dest="continue_mode", action="store_true", help="Retry auto-apply on link rows in Excel")
    parser.add_argument("--resume", action="store_true", help="Alias for --continue")
    args = parser.parse_args()

    if args.setup_login:
        setup_interactive_login()
    elif args.refresh_naukri:
        with sync_playwright() as p:
            browser_ref, context, is_attached = get_browser_context(p, headless=not args.headed)
            page = context.pages[0] if context.pages else context.new_page()
            from naukri_agent import modify_naukri_profile_keywords

            success, msg = modify_naukri_profile_keywords(page)
            print(f"[AI Job Agent] Naukri Keyword Modifier Result: {success} - {msg}")
            if not is_attached:
                context.close()
            else:
                browser_ref.disconnect()
    elif args.continue_mode or args.resume:
        continue_applying_queued_jobs(max_to_apply=args.max_apply, headless=not args.headed)
    else:
        run_job_search_and_apply(
            headless=not args.headed,
            max_auto_apply=args.max_apply,
            indeed_only=args.indeed_only,
            search_only=args.search_only,
            max_roles=args.max_roles,
            max_per_role=args.max_per_role,
        )
