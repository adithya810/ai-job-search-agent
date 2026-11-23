import sys
import shutil
import json
import time
import argparse
from pathlib import Path
from collections import Counter

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except Exception:
    pass

from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
from playwright.sync_api import sync_playwright

from config import (
    BASE_DIR,
    BROWSER_PROFILE_DIR,
    MATCH_THRESHOLD_PERCENT,
    JOB_DISCOVERY_LOG,
    LOGIN_EMAIL,
    CANDIDATE_PROFILE,
)
from resume_builder import ensure_resume_files
from matcher import compute_resume_match, is_experience_below_4_years
from scrapers import (
    load_target_companies_from_sheet,
    search_linkedin_jobs,
    search_portal_jobs_via_playwright,
    search_official_company_sites,
    is_posted_within_48_hours,
)
from firecrawl_scraper import (
    discover_jobs_via_search,
    enrich_job_description,
)
from auto_applier import (
    try_login_naukri,
    try_login_linkedin,
    try_login_indeed,
    attempt_auto_apply,
    select_resume_for_job,
)
from excel_reporter import (
    update_applied_companies_excel,
    get_ist_now_str,
    load_applied_urls,
    get_queued_jobs_from_excel,
    update_single_job_status_in_excel,
)


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
    """
    Connects to user's live Chrome via CDP (port 9222) if running, else launches
    persistent Chromium/Edge/Chrome context with saved profile in .chrome_profile.
    """
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
            page = context.pages[0] if context.pages else context.new_page()
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
    """
    On Windows only, keeps 'E:\\job search agent' and 'E:\\jobsearch python agent' synchronized.
    Skipped cleanly on Linux/macOS cloud runtimes.
    """
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
) -> Dict[str, Any]:
    print("=" * 75)
    print(f"[AI Job Agent] Starting Run at {get_ist_now_str()}")
    print(f"[AI Job Agent] Candidate: {CANDIDATE_PROFILE['full_name']} ({LOGIN_EMAIL})")
    print(f"[AI Job Agent] Target Headline: {CANDIDATE_PROFILE['target_designation']}")
    print(f"[AI Job Agent] Portals: LinkedIn, Naukri, Indeed, ZipRecruiter, Glassdoor, Official Sites + Exa & Firecrawl")
    print(f"[AI Job Agent] Minimum Resume Match Threshold: {MATCH_THRESHOLD_PERCENT}%")
    print(f"[AI Job Agent] Mode: {'Search + Resume Match Only' if (search_only or max_auto_apply <= 0) else f'Search + Match + Auto-Apply (cap={max_auto_apply})'}")
    print(f"[AI Job Agent] Project Folder: {BASE_DIR}")
    print("=" * 75)

    BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Ensure Role-Specific Resume PDFs & Company name.xlsx are ready
    resume_pdf = ensure_resume_files()
    print(f"[1/5] Verified role-specific Resume PDFs in {BASE_DIR / 'resumes'} (primary: {resume_pdf})")

    # 2. Load target companies from 'Company name.xlsx'
    target_companies = load_target_companies_from_sheet()
    print(f"[2/5] Loaded {len(target_companies)} target companies from 'Company name.xlsx': {', '.join(target_companies)}")

    # 3. Search LinkedIn Jobs (Standard & Easy Apply)
    search_queries = [
        "Data Analyst",
        "MIS Executive",
        "Power BI Developer",
        "AI ML Engineer Python",
        "Python Data Analyst SQL",
        "MIS Reporting Power BI Excel",
        "Reporting Analyst Power BI",
        "Data Analyst Azure Databricks",
    ]
    search_locations = ["Hyderabad", "Bengaluru", "Gurugram", "Chennai"]

    print("[3/5] Searching LinkedIn (Standard & Easy Apply) across Hyderabad, Bengaluru, Gurugram, Chennai (<= 48h)...")
    raw_jobs: List[Dict[str, Any]] = search_linkedin_jobs(
        queries=search_queries,
        locations=search_locations,
        max_per_query=6,
        easy_apply_only=False,
    )
    easy_apply_linkedin_jobs = search_linkedin_jobs(
        queries=search_queries[:4],
        locations=search_locations,
        max_per_query=5,
        easy_apply_only=True,
    )
    raw_jobs.extend(easy_apply_linkedin_jobs)
    print(f"      -> Found {len(raw_jobs)} initial listings on LinkedIn.")

    # Optional Playwright multi-portal & company career scraping (graceful fallback if browser binary unavailable)
    browser_available = False
    if not search_only:
        try:
            with sync_playwright() as p:
                browser_ref, context, is_attached = get_browser_context(p, headless=headless)
                browser_available = True
                page = context.pages[0] if context.pages else context.new_page()

                print("[3/5] Searching Naukri, Indeed, ZipRecruiter, and Glassdoor via Playwright & BeautifulSoup...")
                page = ensure_page(context, page)
                portal_jobs = search_portal_jobs_via_playwright(page, target_companies)
                print(f"      -> Found {len(portal_jobs)} listings across Multi-Portal Search.")
                raw_jobs.extend(portal_jobs)

                print("[3/5] Searching Official Company Career Portals from 'Company name.xlsx'...")
                page = ensure_page(context, page)
                official_jobs = search_official_company_sites(page, target_companies)
                print(f"      -> Found {len(official_jobs)} listings across Official Company Sites.")
                raw_jobs.extend(official_jobs)

                if not is_attached:
                    context.close()
                else:
                    browser_ref.disconnect()
        except Exception as pw_err:
            print(f"[3/5] Playwright browser note (skipping browser portals in this environment): {pw_err}")

    print("[3/5] Searching the web with Exa, Firecrawl & MCP discoveries for fresh job openings (<= 48h)...")
    try:
        exa_jobs = discover_jobs_via_search(search_queries[:4], search_locations, max_per_query=5)
        for exa_job in exa_jobs[:15]:
            if len(exa_job.get("description") or "") < 250:
                enrich_job_description(exa_job, page=None)
    except Exception as exa_err:
        exa_jobs = []
        print(f"      -> Exa / Firecrawl discovery note: {exa_err}")
    print(f"      -> Found {len(exa_jobs)} listings via Exa, Firecrawl & MCP web discovery.")
    raw_jobs.extend(exa_jobs)

    # Deduplicate raw jobs by URL
    unique_jobs: List[Dict[str, Any]] = []
    seen_urls = set()
    for j in raw_jobs:
        u = (j.get("url") or "").strip()
        if u and u not in seen_urls:
            seen_urls.add(u)
            unique_jobs.append(j)

    # Filter for 48 Hours Recency & Experience Fit
    recent_jobs = []
    for j in unique_jobs:
        if not is_posted_within_48_hours(j.get("posted_date", "")):
            continue
        is_exp_ok, _ = is_experience_below_4_years(j.get("experience", ""), j.get("description", ""))
        if not is_exp_ok:
            continue
        recent_jobs.append(j)

    print(f"[4/5] 48-Hour & Experience Filter: Retained {len(recent_jobs)} / {len(unique_jobs)} jobs.")

    # Score all recent jobs against Adithya's resume & filter >= 80%
    matched_jobs: List[Dict[str, Any]] = []
    print(f"[4/5] Evaluating Resume Skill Match for {len(recent_jobs)} recent jobs (Threshold >= {MATCH_THRESHOLD_PERCENT}%)...")
    for job in recent_jobs:
        score, matched_skills, explanation = compute_resume_match(job, target_companies)
        job["match_score"] = score
        job["matched_skills"] = matched_skills
        job["match_explanation"] = explanation
        if score >= MATCH_THRESHOLD_PERCENT:
            matched_jobs.append(job)

    def sort_priority(item):
        comp_in_sheet = any(tc.lower() in item.get("company", "").lower() for tc in target_companies)
        is_easy_apply = (
            "easy apply" in item.get("portal", "").lower()
            or "easily apply" in item.get("portal", "").lower()
            or "naukri" in item.get("portal", "").lower()
            or "indeed" in item.get("portal", "").lower()
            or item.get("easy_apply") is True
        )
        score = item.get("match_score", 0.0)
        return (comp_in_sheet, is_easy_apply, score)

    if indeed_only:
        matched_jobs = [j for j in matched_jobs if "indeed" in j.get("portal", "").lower() or "indeed.com" in j.get("url", "").lower()]

    matched_jobs.sort(key=sort_priority, reverse=True)
    print(f"      -> {len(matched_jobs)} jobs matched >= {MATCH_THRESHOLD_PERCENT}% and posted within 48 hours!")

    previously_applied_urls = load_applied_urls()
    print(f"[4/5] Loaded {len(previously_applied_urls)} previously applied URLs to prevent duplicate submissions.")

    fresh_jobs: List[Dict[str, Any]] = []
    for job in matched_jobs:
        job_url = (job.get("url") or "").strip()
        posted_tag = f"Posted: {job.get('posted_date', 'Within 48h')}"
        if job_url in previously_applied_urls:
            resume_path, resume_key, resume_reason = select_resume_for_job(job)
            job["resume_path"] = str(resume_path)
            job["resume_variant"] = resume_key
            job["resume_reason"] = resume_reason
            job["application_status"] = "Already Applied (Previous Iteration)"
            job["notes"] = f"{job['match_explanation']} | {posted_tag} | Resume: {resume_key} | Skipped duplicate."
            continue
        fresh_jobs.append(job)

    ordered_jobs = prepare_resumes_and_order(fresh_jobs)

    if search_only or max_auto_apply <= 0 or not browser_available:
        for job in ordered_jobs:
            posted_tag = f"Posted: {job.get('posted_date', 'Within 48h')}"
            job["application_status"] = "Matched >=80% (Ready with Matched Resume)"
            job["notes"] = (
                f"{job['match_explanation']} | {posted_tag} | "
                f"Resume: {job.get('resume_variant')} ({job.get('resume_reason', '')})"
            )
    else:
        print(f"[4/5] Verifying sessions & executing Auto-Apply for up to {max_auto_apply} top-matching jobs...")
        with sync_playwright() as p:
            browser_ref, context, is_attached = get_browser_context(p, headless=headless)
            page = context.pages[0] if context.pages else context.new_page()
            try_login_indeed(page)
            page = ensure_page(context, page)
            try_login_naukri(page)
            page = ensure_page(context, page)
            try_login_linkedin(page)

            submitted_count = 0
            attempt_cap = max_auto_apply
            for idx, job in enumerate(ordered_jobs, start=1):
                posted_tag = f"Posted: {job.get('posted_date', 'Within 48h')}"
                if submitted_count >= max_auto_apply or idx > attempt_cap:
                    job["application_status"] = "Matched >=80% (Queued for Next Run)"
                    job["notes"] = f"{job['match_explanation']} | {posted_tag} | Skills: {', '.join(job.get('matched_skills', []))}"
                    continue

                portal_label = job.get("portal", "Portal")
                comp_label = job.get("company", "Company")
                title_label = job.get("title", "Role")
                resume_label = job.get("resume_variant", "default")
                print(f"      [{idx}/{min(len(ordered_jobs), attempt_cap)}] Applying: {comp_label} - {title_label} ({portal_label}) | Resume: {resume_label}...")
                try:
                    page = ensure_page(context, page)
                    page.set_default_timeout(12000)
                    status, notes = attempt_auto_apply(page, job)
                except Exception as apply_err:
                    status = "Processed (Direct Link Saved)"
                    notes = f"Direct link saved ({str(apply_err)[:80]})"
                job["application_status"] = status
                job["notes"] = f"{job['match_explanation']} | {posted_tag} | Resume: {resume_label} ({job.get('resume_reason', '')}) | {notes}"
                print(f"         -> Result: {status}")
                if status.startswith("Applied") and "Already" not in status:
                    submitted_count += 1

            if not is_attached:
                context.close()
            else:
                browser_ref.disconnect()

    # 5. Export to Excel in project folder
    excel_path = update_applied_companies_excel(matched_jobs, target_companies)
    print(f"[5/5] Updated Excel Tracker saved to: {excel_path}")

    # Compute skill demand & resume variant routing summary
    skill_counter = Counter()
    resume_counter = Counter()
    for mj in matched_jobs:
        resume_counter[mj.get("resume_variant", "default")] += 1
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
        "total_discovered": len(raw_jobs),
        "total_unique_filtered_48h": len(recent_jobs),
        "total_matched_above_80_pct": len(matched_jobs),
        "resume_variant_distribution": dict(resume_counter),
        "excel_tracker_path": str(excel_path),
        "resume_skills_matched_summary": skill_summary,
        "top_matched_jobs": matched_jobs[:60],
    }
    JOB_DISCOVERY_LOG.write_text(json.dumps(summary_payload, indent=2), encoding="utf-8")

    mirror_project_folders()

    print("=" * 75)
    print(f"[AI Job Agent] Run Complete! {len(matched_jobs)} high-match (>=80%) jobs recorded in {excel_path.name}")
    print(f"[AI Job Agent] Resume Routing Breakdown: {dict(resume_counter)}")
    print("=" * 75)
    return summary_payload


def continue_applying_queued_jobs(max_to_apply: int = 25, headless: bool = True) -> Dict[str, Any]:
    ensure_resume_files()
    target_companies = load_target_companies_from_sheet()
    queued = get_queued_jobs_from_excel()
    if not queued:
        return {"status": "complete", "message": "No queued jobs found", "applied": 0}

    to_process = prepare_resumes_and_order(queued[:max_to_apply])
    processed_results = []

    with sync_playwright() as p:
        browser_ref, context, is_attached = get_browser_context(p, headless=headless)
        page = context.pages[0] if context.pages else context.new_page()
        for idx, job in enumerate(to_process):
            row = job.get("excel_row")
            try:
                page = ensure_page(context, page)
                status, notes = attempt_auto_apply(page, job)
            except Exception as apply_err:
                status = "Processed (Direct Link Saved)"
                notes = f"Error: {str(apply_err)[:80]}"
            full_notes = f"{job.get('notes', '')} | Continued ({get_ist_now_str()}): {notes}"
            update_single_job_status_in_excel(row, status, full_notes)
            processed_results.append({
                "company": job.get("company"),
                "title": job.get("title"),
                "portal": job.get("portal"),
                "status": status,
                "url": job.get("url"),
            })
        if not is_attached:
            context.close()
        else:
            browser_ref.disconnect()

    mirror_project_folders()
    return {"last_run_ist": get_ist_now_str(), "processed_jobs": processed_results}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Adithya Krishna AI Job Search & Auto-Apply Agent")
    parser.add_argument("--headed", action="store_true", help="Run browser in visible window mode")
    parser.add_argument("--max-apply", type=int, default=25, help="Maximum auto-applications per run")
    parser.add_argument("--search-only", action="store_true", help="Run discovery, >=80% skill match, per-job resume selection & Excel export without auto-submitting")
    parser.add_argument("--setup-login", action="store_true", help="Open visible browser to log into job portals once")
    parser.add_argument("--refresh-naukri", action="store_true", help="Run daily Naukri profile keyword modification")
    parser.add_argument("--indeed-only", action="store_true", help="Filter and auto-apply strictly on Indeed India jobs")
    parser.add_argument("--continue", "-c", dest="continue_mode", action="store_true", help="Continue applying to queued jobs")
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
        )
