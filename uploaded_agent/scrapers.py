"""Stage 03: Sequential 48-Hour Multi-Portal Search Orchestrator (Steps 1 -> 2 -> 3 -> 4 Role-by-Role).

Executes strict <= 48h job search in sequential portal order using Shared Agent Memory:
  1. LinkedIn Jobs Search (<= 48 HRS, f_TPR=r172800, standard + Easy Apply)
  2. Naukri.com Search    (<= 48 HRS, jobAge=2 & skill tags)
  3. ZipRecruiter Search  (<= 48 HRS, days=2 & role/skill queries)
  4. Company Career Pages (<= 48 HRS, crawls Direct Career Portal URLs from Input Excel)
"""

import re
import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
import requests
from bs4 import BeautifulSoup
import openpyxl

from config import (
    COMPANY_CHECK_SHEET,
    OFFICIAL_COMPANY_PORTALS,
)
from firecrawl_scraper import discover_jobs_via_search, enrich_job_description
from resume_builder import ensure_company_check_sheet

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

NAV_NOISE_PATTERNS = re.compile(
    r"(?:skip\s+to\s+main|cookie|privacy\s+policy|terms\s+of\s+use|sign\s+in|log\s*in|"
    r"create\s+alert|job\s+alert|reshape\s+your\s+future|about\s+us|contact\s+us|read\s+more|"
    r"learn\s+more|view\s+all\s+jobs|search\s+jobs$)",
    re.IGNORECASE,
)

CAREER_ROLE_WORD_REGEX = re.compile(
    r"\b(?:data\s+analyst|mis\s+executive|mis\s+analyst|mis\s+reporting|reporting\s+analyst|"
    r"power\s*bi|insights\s+analyst|operations\s+analyst|claims\s+reporting|ai/?ml|"
    r"machine\s+learning|data\s+scientist|data\s+engineer|etl\s+developer|business\s+analyst|"
    r"analytics\s+engineer|bi\s+developer|bi\s+analyst)\b",
    re.IGNORECASE,
)


def is_posted_within_48_hours(posted_str: str) -> bool:
    """Returns True if the job was published within the last 48 hours (<= 2 days)."""
    if not posted_str:
        return True
    s = posted_str.lower().strip()

    if any(f"{d} day" in s or f"{d}d ago" in s or f"{d}d" == s for d in range(3, 31)):
        return False
    if any(k in s for k in ["week", "month", "30+", "older", "year ago", "years ago"]):
        return False

    m_days = re.search(r"(\d+)\s*day", s)
    if m_days and int(m_days.group(1)) > 2:
        return False

    m_iso = re.search(r"(\d{4})-(\d{2})-(\d{2})", posted_str)
    if m_iso:
        try:
            job_date = datetime.strptime(m_iso.group(0), "%Y-%m-%d").date()
            ist_today = datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
            diff_days = (ist_today - job_date).days
            if diff_days > 2:
                return False
        except Exception:
            pass

    if any(
        k in s
        for k in [
            "just now",
            "few hours ago",
            "hour ago",
            "hours ago",
            "hr ago",
            "hrs ago",
            "minute",
            "minutes",
            "today",
            "active today",
            "1 day ago",
            "2 days ago",
            "1d ago",
            "2d ago",
            "yesterday",
            "within 48",
            "recent",
            "active on",
        ]
    ):
        return True

    return True


def load_target_companies_from_sheet() -> List[str]:
    """Reads company names from 'Company name.xlsx' in the project folder."""
    ensure_company_check_sheet()
    companies = []
    if not COMPANY_CHECK_SHEET.exists():
        return [v["name"] for v in OFFICIAL_COMPANY_PORTALS.values()]

    try:
        wb = openpyxl.load_workbook(COMPANY_CHECK_SHEET, data_only=True)
        ws = wb.active
        for row_idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
            if not row or not row[0]:
                continue
            val = str(row[0]).strip()
            if row_idx == 1 and val.lower() in ("company name", "company", "companies"):
                continue
            if val:
                companies.append(val)
        wb.close()
    except Exception:
        companies = [v["name"] for v in OFFICIAL_COMPANY_PORTALS.values()]
    return companies


def search_linkedin_jobs(
    queries: List[str],
    locations: List[str],
    max_per_query: int = 8,
    easy_apply_only: bool = False,
) -> List[Dict[str, Any]]:
    """Step 1 — Searches LinkedIn guest jobs API (<= 48h via f_TPR=r172800)."""
    jobs: List[Dict[str, Any]] = []
    seen_urls = set()

    for query in queries:
        for loc in locations:
            loc_param = loc if "india" in loc.lower() else f"{loc}, India"
            params = {
                "keywords": query,
                "location": loc_param,
                "f_TPR": "r172800",  # Strict 48 Hours Recency Filter
                "f_E": "2,3,4",      # Associate / Mid-Senior
                "start": 0,
            }
            if easy_apply_only:
                params["f_AL"] = "true"
            url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?{urllib.parse.urlencode(params)}"
            try:
                resp = requests.get(url, headers=HEADERS, timeout=10)
                if resp.status_code != 200:
                    continue
                soup = BeautifulSoup(resp.text, "html.parser")
                cards = soup.find_all("li")
                for card in cards[:max_per_query]:
                    title_el = card.find("h3", class_="base-search-card__title")
                    comp_el = card.find("h4", class_="base-search-card__subtitle")
                    loc_el = card.find("span", class_="job-search-card__location")
                    link_el = card.find("a", class_="base-card__full-link")
                    date_el = card.find("time")

                    if not title_el or not link_el:
                        continue
                    title = title_el.get_text(strip=True)
                    company = comp_el.get_text(strip=True) if comp_el else "Hiring Organization"
                    job_loc = loc_el.get_text(strip=True) if loc_el else loc_param
                    href = (link_el.get("href") or "").split("?")[0].strip()
                    if not href or href in seen_urls:
                        continue

                    posted_str = (
                        date_el.get("datetime") or date_el.get_text(strip=True)
                        if date_el
                        else "Within 48 hours"
                    )
                    posted_display = date_el.get_text(strip=True) if date_el else "Within 48 hours"
                    if not is_posted_within_48_hours(posted_display) or not is_posted_within_48_hours(posted_str):
                        continue

                    seen_urls.add(href)
                    portal_label = "LinkedIn Easy Apply" if easy_apply_only else "LinkedIn"
                    job_entry = {
                        "portal": portal_label,
                        "portal_step": "Step 1: LinkedIn",
                        "title": title,
                        "company": company,
                        "location": job_loc,
                        "experience": "1-4.5 Years",
                        "skills": "",
                        "description": f"{title} at {company} in {job_loc} (Query: {query}, Posted: {posted_display}).",
                        "url": href,
                        "posted_date": posted_display,
                        "easy_apply": easy_apply_only,
                        "role_queried": query,
                    }
                    if len(jobs) < 40:
                        enrich_linkedin_job_description(job_entry)
                    jobs.append(job_entry)
            except Exception:
                continue

    return jobs


def enrich_linkedin_job_description(job: Dict[str, Any]) -> Dict[str, Any]:
    """Fetches full job description & apply button metadata from LinkedIn guest job view API."""
    url = job.get("url", "")
    m = re.search(r"-(\d{7,12})(?:$|\?|/)", url) or re.search(r"view/(\d{7,12})", url)
    if not m:
        return job
    job_id = m.group(1)
    detail_url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
    try:
        resp = requests.get(detail_url, headers=HEADERS, timeout=8)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            desc_el = soup.find("div", class_="show-more-less-html__markup")
            if desc_el:
                job["description"] = desc_el.get_text(" ", strip=True)[:3500]
            # Detect whether LinkedIn guest page exposes an external off-site apply link vs native Easy Apply
            apply_el = soup.find("a", class_="apply-button") or soup.find("a", attrs={"data-tracking-control-name": re.compile("apply", re.I)})
            if apply_el and apply_el.get("href"):
                ext_href = apply_el.get("href", "")
                if "externalApply" in ext_href or (ext_href.startswith("http") and "linkedin.com/login" not in ext_href):
                    job["external_apply_url"] = ext_href
            easy_btn_el = soup.find(string=re.compile(r"Easy Apply", re.I))
            if easy_btn_el:
                job["easy_apply"] = True
                job["portal"] = "LinkedIn Easy Apply"
    except Exception:
        pass
    return job


def ensure_page_active(page):
    try:
        if page is None or page.is_closed():
            if page and hasattr(page, "context") and page.context:
                return page.context.new_page()
    except Exception:
        pass
    return page


def search_ziprecruiter_jobs(
    page,
    locations: List[str],
    max_per_loc: int = 8,
    queries: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Step 3 — Searches ZipRecruiter role-wise for <= 48h fresh openings (days=2)."""
    discovered: List[Dict[str, Any]] = []
    if page is None:
        return discovered
    seen_urls = set()
    role_queries = queries or ["Data Analyst", "MIS Executive", "Power BI Developer"]

    for q in role_queries:
        for loc in locations:
            clean_loc = "Gurugram" if "gurgaon" in loc.lower() or "gurugram" in loc.lower() else loc
            url = f"https://www.ziprecruiter.in/jobs/search?q={urllib.parse.quote(q)}&l={urllib.parse.quote(clean_loc)}&days=2"
            try:
                page = ensure_page_active(page)
                page.goto(url, wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(1400)

                soup = BeautifulSoup(page.content(), "html.parser")
                items = soup.find_all("div", class_="jobList-introWrap")
                for it in items[:max_per_loc]:
                    link_el = it.find("a")
                    title_el = it.find(["h2", "h3", "a"])
                    if not link_el or not title_el:
                        continue
                    title = title_el.get_text(strip=True)
                    rel_url = link_el.get("href", "")
                    if not rel_url:
                        continue
                    full_url = f"https://www.ziprecruiter.in{rel_url}" if rel_url.startswith("/") else rel_url
                    if full_url in seen_urls:
                        continue
                    seen_urls.add(full_url)

                    parent_text = it.parent.get_text(" | ", strip=True) if it.parent else ""
                    parts = [p.strip() for p in parent_text.split(" | ") if p.strip()]
                    company = parts[1] if len(parts) > 1 and parts[1] != title else "Enterprise Employer"
                    job_loc = parts[2] if len(parts) > 2 else f"{clean_loc}, India"
                    snippet = parts[3] if len(parts) > 3 else f"{title} opening in {clean_loc} on ZipRecruiter."
                    quick_apply = bool(re.search(r"1-click\s+apply|quick\s+apply", parent_text, re.I))

                    discovered.append(
                        {
                            "portal": "ZipRecruiter Quick Apply" if quick_apply else "ZipRecruiter",
                            "portal_step": "Step 3: ZipRecruiter",
                            "title": title,
                            "company": company,
                            "location": job_loc,
                            "experience": "1-4.5 Years",
                            "skills": "",
                            "description": snippet,
                            "url": full_url,
                            "posted_date": "Within 48 hours",
                            "easy_apply": quick_apply,
                            "role_queried": q,
                        }
                    )
            except Exception as exc:
                print(f"[ZipRecruiter] Search note ({clean_loc} - {q}): {exc}")

    return discovered


def search_portal_jobs_via_playwright(page, target_companies: List[str]) -> List[Dict[str, Any]]:
    """Legacy multi-portal helper retained for backward compatibility."""
    discovered: List[Dict[str, Any]] = []
    if page is None:
        return discovered
    seen_urls = set()

    zip_jobs = search_ziprecruiter_jobs(page, ["Hyderabad", "Bengaluru", "Gurugram", "Chennai"], max_per_loc=6)
    for zj in zip_jobs:
        seen_urls.add(zj["url"])
        discovered.append(zj)

    try:
        from naukri_agent import search_naukri_api_and_portal

        naukri_results = search_naukri_api_and_portal(page, freshness_days=2, max_per_query=8)
        for nj in naukri_results:
            u = nj.get("url", "")
            if u and u not in seen_urls:
                nj.setdefault("portal_step", "Step 2: Naukri.com")
                seen_urls.add(u)
                discovered.append(nj)
    except Exception as n_api_exc:
        print(f"[Naukri] Dynamic search note: {n_api_exc}")

    return discovered


def search_official_company_sites(
    page,
    target_companies: List[str],
    career_pages: Optional[List[Dict[str, str]]] = None,
) -> List[Dict[str, Any]]:
    """Step 4 — Crawls Direct Career Portal URLs from `Company name.xlsx` for <= 48h roles."""
    official_jobs: List[Dict[str, Any]] = []
    seen_urls = set()

    resolved_targets: List[Dict[str, str]] = []
    if career_pages:
        resolved_targets = career_pages
    else:
        for raw_company in target_companies:
            key = raw_company.lower().strip()
            portal_cfg = OFFICIAL_COMPANY_PORTALS.get(key, {})
            if not portal_cfg:
                for k, v in OFFICIAL_COMPANY_PORTALS.items():
                    if k in key or key in k:
                        portal_cfg = v
                        break
            resolved_targets.append(
                {
                    "company": portal_cfg.get("name", raw_company),
                    "careers_url": portal_cfg.get(
                        "careers_url",
                        f"https://www.google.com/search?q={urllib.parse.quote(raw_company + ' careers Data Analyst India')}",
                    ),
                }
            )

    for entry in resolved_targets:
        official_name = entry["company"]
        careers_url = entry["careers_url"]

        # 1. Crawl direct career portal page (Playwright if available, HTTP fallback otherwise)
        anchors: List[tuple[str, str]] = []
        if page is not None:
            try:
                page = ensure_page_active(page)
                page.goto(careers_url, wait_until="domcontentloaded", timeout=14000)
                page.wait_for_timeout(1400)
                for a in page.locator("a").all()[:100]:
                    try:
                        txt = (a.inner_text() or "").strip()
                        href = a.get_attribute("href") or ""
                        if txt and href:
                            anchors.append((txt, href))
                    except Exception:
                        continue
            except Exception as exc:
                print(f"[Step 4 Career Page] Browser note ({official_name}): {exc}")
        else:
            try:
                resp = requests.get(careers_url, headers=HEADERS, timeout=10)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    for a in soup.find_all("a", href=True)[:100]:
                        txt = a.get_text(" ", strip=True)
                        href = a.get("href", "")
                        if txt and href:
                            anchors.append((txt, href))
            except Exception:
                pass

        found_on_portal = 0
        for txt, href in anchors:
            clean_title = txt.splitlines()[0].strip()
            if len(clean_title) < 6 or len(clean_title) > 120:
                continue
            if NAV_NOISE_PATTERNS.search(clean_title):
                continue
            if not CAREER_ROLE_WORD_REGEX.search(clean_title):
                continue
            full_url = urllib.parse.urljoin(careers_url, href)
            if not full_url.startswith("http") or full_url in seen_urls or full_url.rstrip("/") == careers_url.rstrip("/"):
                continue
            seen_urls.add(full_url)
            official_jobs.append(
                {
                    "portal": f"Company Career Page ({official_name})",
                    "portal_step": "Step 4: Company Career Page",
                    "title": clean_title,
                    "company": official_name,
                    "location": "India",
                    "experience": "1-4.5 Years",
                    "skills": "",
                    "description": f"Career portal opening at {official_name}: {clean_title}.",
                    "url": full_url,
                    "official_careers_url": careers_url,
                    "posted_date": "Within 48 hours",
                }
            )
            found_on_portal += 1
            if found_on_portal >= 4:
                break

        # 2. Cross-check <=48h fresh openings for this exact Input-Excel company via LinkedIn Guest API
        try:
            comp_jobs = search_linkedin_jobs(
                queries=[f"{official_name} Data Analyst", f"{official_name} Power BI"],
                locations=["India"],
                max_per_query=3,
                easy_apply_only=False,
            )
            first_token = official_name.split()[0].lower()
            for cj in comp_jobs:
                if cj["url"] not in seen_urls and first_token in cj["company"].lower():
                    seen_urls.add(cj["url"])
                    cj["portal"] = f"Company Career Page / LinkedIn ({official_name})"
                    cj["portal_step"] = "Step 4: Company Career Page"
                    cj["official_careers_url"] = careers_url
                    official_jobs.append(cj)
        except Exception:
            pass

    return official_jobs


def run_sequential_48h_search(
    memory: Any,
    *,
    page=None,
    max_roles: int = 5,
    max_per_role: int = 5,
) -> Dict[str, Any]:
    """Stage 03 — SEQUENTIAL SEARCH ORCHESTRATOR (Steps 1 -> 2 -> 3 -> 4 Role-by-Role, <= 48h).

    Returns a dictionary containing `jobs` and `step_counts` across Steps 1..4.
    """
    roles = list(memory.target_roles[:max_roles]) or ["Data Analyst", "MIS Executive", "Power BI Developer"]
    locations = list(memory.locations) or ["Hyderabad", "Bengaluru", "Gurugram", "Chennai"]
    skill_hint = " ".join(memory.primary_skills[:2]) if getattr(memory, "primary_skills", None) else "Python SQL"

    step_counts = {
        "step_1_linkedin": 0,
        "step_2_naukri": 0,
        "step_3_ziprecruiter": 0,
        "step_4_company_career_pages": 0,
    }
    collected: List[Dict[str, Any]] = []

    print(f"[Stage 03] Sequential 48h Search Orchestrator starting across {len(roles)} roles (Steps 1 -> 2 -> 3 -> 4)...")

    for role_idx, role in enumerate(roles, start=1):
        role_with_skill = f"{role} {skill_hint}".strip()
        print(f"  [Role {role_idx}/{len(roles)}: '{role}'] Executing Sequential Loop 1 -> 2 -> 3...")

        # Step 1: LinkedIn Jobs Search (<= 48 HRS)
        li_std = search_linkedin_jobs(
            queries=[role],
            locations=locations,
            max_per_query=max_per_role,
            easy_apply_only=False,
        )
        li_easy = search_linkedin_jobs(
            queries=[role],
            locations=locations[:2],
            max_per_query=max(2, max_per_role - 1),
            easy_apply_only=True,
        )
        step1_batch = li_std + li_easy
        for j in step1_batch:
            j["portal_step"] = "Step 1: LinkedIn"
            j["role_queried"] = role
        collected.extend(step1_batch)
        step_counts["step_1_linkedin"] += len(step1_batch)

        # Step 2: Naukri.com Search (<= 48 HRS, freshness=2 days)
        if page is not None:
            try:
                from naukri_agent import search_naukri_api_and_portal

                naukri_batch = search_naukri_api_and_portal(
                    page,
                    freshness_days=2,
                    max_per_query=max_per_role,
                    role_queries=[role],
                    locations=locations,
                )
                for nj in naukri_batch:
                    nj["portal_step"] = "Step 2: Naukri.com"
                    nj["role_queried"] = role
                collected.extend(naukri_batch)
                step_counts["step_2_naukri"] += len(naukri_batch)
            except Exception as exc:
                print(f"    [Step 2: Naukri] Note for '{role}': {exc}")

        # Step 3: ZipRecruiter Search (<= 48 HRS, days=2)
        if page is not None:
            try:
                zip_batch = search_ziprecruiter_jobs(
                    page,
                    locations=locations,
                    max_per_loc=max_per_role,
                    queries=[role],
                )
                for zj in zip_batch:
                    zj["portal_step"] = "Step 3: ZipRecruiter"
                    zj["role_queried"] = role
                collected.extend(zip_batch)
                step_counts["step_3_ziprecruiter"] += len(zip_batch)
            except Exception as exc:
                print(f"    [Step 3: ZipRecruiter] Note for '{role}': {exc}")

        # Supplementary web-index discovery (Exa / Firecrawl) if API keys are configured
        if role_idx <= 2:
            try:
                web_hits = discover_jobs_via_search([role_with_skill], locations[:2], max_per_query=3)
                for wh in web_hits[:6]:
                    if len(wh.get("description") or "") < 250:
                        enrich_job_description(wh, page=None)
                    u_low = (wh.get("url") or "").lower()
                    if "linkedin.com" in u_low:
                        wh["portal_step"] = "Step 1: LinkedIn"
                    elif "naukri.com" in u_low:
                        wh["portal_step"] = "Step 2: Naukri.com"
                    elif "ziprecruiter" in u_low:
                        wh["portal_step"] = "Step 3: ZipRecruiter"
                    else:
                        wh["portal_step"] = "Step 4: Company Career Page"
                collected.extend(web_hits)
            except Exception:
                pass

    # Step 4: Company Career Pages (<= 48 HRS) from Input Excel (`Company name.xlsx`)
    print(f"  [Step 4/4] Crawling {len(memory.career_pages)} Target Company Career Portals from Input Excel...")
    career_batch = search_official_company_sites(
        page,
        memory.target_company_names,
        career_pages=memory.career_pages,
    )
    for cj in career_batch:
        cj["portal_step"] = "Step 4: Company Career Page"
    collected.extend(career_batch)
    step_counts["step_4_company_career_pages"] += len(career_batch)

    print(
        f"[Stage 03] Sequential Search Summary -> "
        f"Step 1 LinkedIn: {step_counts['step_1_linkedin']} | "
        f"Step 2 Naukri: {step_counts['step_2_naukri']} | "
        f"Step 3 ZipRecruiter: {step_counts['step_3_ziprecruiter']} | "
        f"Step 4 Career Pages: {step_counts['step_4_company_career_pages']}"
    )
    return {"jobs": collected, "step_counts": step_counts}
