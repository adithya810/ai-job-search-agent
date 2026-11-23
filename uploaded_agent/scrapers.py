import re
import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
import requests
from bs4 import BeautifulSoup
import openpyxl

from config import (
    COMPANY_CHECK_SHEET,
    OFFICIAL_COMPANY_PORTALS,
)
from firecrawl_scraper import is_firecrawl_configured, search_jobs_with_firecrawl
from resume_builder import ensure_company_check_sheet

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def is_posted_within_48_hours(posted_str: str) -> bool:
    """
    Returns True if the job was published within the last 48 hours.
    Explicitly filters out any postings >= 3 days, 1 week, or older.
    """
    if not posted_str:
        return True
    s = posted_str.lower().strip()

    if any(
        k in s
        for k in [
            "just now",
            "few hours ago",
            "hour ago",
            "hours ago",
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
            "official",
        ]
    ):
        if any(f"{d} day" in s or f"{d}d" in s for d in range(3, 31)):
            return False
        return True

    if any(f"{d} day" in s or f"{d}d ago" in s for d in range(3, 31)):
        return False
    if any(k in s for k in ["week", "month", "30+", "older"]):
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
    """
    Searches LinkedIn public/guest jobs API using requests + BeautifulSoup across
    Hyderabad, Bengaluru, Gurugram, and Chennai for postings within 48 hours (f_TPR=r172800).
    """
    jobs: List[Dict[str, Any]] = []
    seen_urls = set()

    for query in queries:
        for loc in locations:
            params = {
                "keywords": query,
                "location": f"{loc}, India",
                "f_TPR": "r172800",  # 48 Hours Recency Filter (172800 seconds)
                "f_E": "2,3",        # Entry level & Associate
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
                    job_loc = loc_el.get_text(strip=True) if loc_el else f"{loc}, India"
                    href = (link_el.get("href") or "").split("?")[0].strip()
                    if not href or href in seen_urls:
                        continue

                    posted_str = date_el.get_text(strip=True) if date_el else "Within 48 hours"
                    if not is_posted_within_48_hours(posted_str):
                        continue

                    seen_urls.add(href)
                    portal_label = "LinkedIn Easy Apply" if easy_apply_only else "LinkedIn"
                    job_entry = {
                        "portal": portal_label,
                        "title": title,
                        "company": company,
                        "location": job_loc,
                        "experience": "1-4.5 Years",
                        "skills": "Python, SQL, Power BI, DAX, Advanced Excel, Power Query, ETL, MIS Reporting",
                        "description": f"{title} at {company} in {job_loc} (Query: {query}, Posted: {posted_str}).",
                        "url": href,
                        "posted_date": posted_str,
                        "easy_apply": easy_apply_only,
                    }
                    if len(jobs) < 35:
                        enrich_linkedin_job_description(job_entry)
                    jobs.append(job_entry)
            except Exception:
                continue

    return jobs


def enrich_linkedin_job_description(job: Dict[str, Any]) -> Dict[str, Any]:
    """Fetches full job description & criteria from LinkedIn guest job view API."""
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
            apply_el = soup.find("a", class_="apply-button")
            if apply_el and apply_el.get("href"):
                job["external_apply_url"] = apply_el.get("href")
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


def search_ziprecruiter_jobs(page, locations: List[str], max_per_loc: int = 8) -> List[Dict[str, Any]]:
    """Searches ZipRecruiter India for MIS Executive, Data Analyst, and Power BI roles."""
    discovered: List[Dict[str, Any]] = []
    seen_urls = set()
    queries = ["Data Analyst", "MIS Executive", "Power BI Analyst"]

    for loc in locations:
        for q in queries[:2]:
            clean_loc = "Gurugram" if "gurgaon" in loc.lower() or "gurugram" in loc.lower() else loc
            url = f"https://www.ziprecruiter.in/jobs/search?q={urllib.parse.quote(q)}&l={urllib.parse.quote(clean_loc)}&days=2"
            try:
                page = ensure_page_active(page)
                page.goto(url, wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(1500)

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

                    discovered.append(
                        {
                            "portal": "ZipRecruiter",
                            "title": title,
                            "company": company,
                            "location": job_loc,
                            "experience": "0-4.5 Years",
                            "skills": "Python, SQL, Power BI, Advanced Excel, MIS, Data Analysis, Reporting, Dashboard",
                            "description": snippet,
                            "url": full_url,
                            "posted_date": "Within 48 hours",
                        }
                    )
            except Exception as exc:
                print(f"[ZipRecruiter] Search note ({clean_loc} - {q}): {exc}")

    return discovered


def search_portal_jobs_via_playwright(page, target_companies: List[str]) -> List[Dict[str, Any]]:
    """
    Searches Naukri, Indeed, Glassdoor, and ZipRecruiter for MIS, Data Analyst, Power BI,
    and AI/ML roles across Hyderabad, Bengaluru, Gurugram, and Chennai.
    """
    discovered: List[Dict[str, Any]] = []
    seen_urls = set()

    # 1. ZIPRECRUITER INDIA Search
    print("      -> Querying ZipRecruiter across Hyderabad, Bengaluru, Gurugram, Chennai...")
    zip_jobs = search_ziprecruiter_jobs(page, ["Hyderabad", "Bengaluru", "Gurugram", "Chennai"], max_per_loc=8)
    print(f"      -> ZipRecruiter: Discovered {len(zip_jobs)} matching postings.")
    for zj in zip_jobs:
        seen_urls.add(zj["url"])
        discovered.append(zj)

    # 2. INDEED INDIA Search
    from matcher import is_experience_below_4_years
    indeed_searches = [
        ("https://in.indeed.com/jobs?q=Data+Analyst+Python+Power+BI&l=Hyderabad%2C+Telangana&fromage=2&iareq=1", "Hyderabad", True),
        ("https://in.indeed.com/jobs?q=MIS+Executive&l=Hyderabad%2C+Telangana&fromage=2&iareq=1", "Hyderabad", True),
        ("https://in.indeed.com/jobs?q=Power+BI+Analyst&l=Hyderabad%2C+Telangana&fromage=2&iareq=1", "Hyderabad", True),
        ("https://in.indeed.com/jobs?q=Data+Analyst+Python+Power+BI&l=Bengaluru%2C+Karnataka&fromage=2&iareq=1", "Bengaluru", True),
        ("https://in.indeed.com/jobs?q=MIS+Executive&l=Bengaluru%2C+Karnataka&fromage=2&iareq=1", "Bengaluru", True),
        ("https://in.indeed.com/jobs?q=Data+Analyst&l=Gurgaon%2C+Haryana&fromage=2&iareq=1", "Gurugram", True),
        ("https://in.indeed.com/jobs?q=MIS+Executive&l=Gurgaon%2C+Haryana&fromage=2&iareq=1", "Gurugram", True),
        ("https://in.indeed.com/jobs?q=Data+Analyst&l=Chennai%2C+Tamil+Nadu&fromage=2&iareq=1", "Chennai", True),
        ("https://in.indeed.com/jobs?q=MIS+Executive&l=Chennai%2C+Tamil+Nadu&fromage=2&iareq=1", "Chennai", True),
        ("https://in.indeed.com/jobs?q=AI+ML+Engineer+Python&l=Hyderabad%2C+Telangana&fromage=2&iareq=1", "Hyderabad", True),
    ]
    for i_url, loc_label, is_ia in indeed_searches:
        try:
            page = ensure_page_active(page)
            page.goto(i_url, wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(1500)

            cards = page.locator("div.job_seen_beacon, td.resultContent, div.cardOutline").all()
            for card in cards[:8]:
                try:
                    title_el = card.locator("h2.jobTitle span[title], h2.jobTitle a, a.jcs-JobTitle").first
                    comp_el = card.locator("[data-testid='company-name'], span.companyName").first
                    loc_el = card.locator("[data-testid='text-location'], div.companyLocation").first
                    link_el = card.locator("h2.jobTitle a, a.jcs-JobTitle").first
                    date_el = card.locator("span.date, [data-testid='myJobsStateDate']").first

                    if title_el.count() == 0:
                        continue
                    title = title_el.inner_text().strip()
                    href = link_el.get_attribute("href") if link_el.count() > 0 else ""
                    if href and href.startswith("/"):
                        href = f"https://in.indeed.com{href}"
                    if not href or href in seen_urls:
                        continue

                    posted_str = date_el.inner_text().strip() if date_el.count() > 0 else "Within 48 hours"
                    if not is_posted_within_48_hours(posted_str):
                        continue

                    card_text = card.inner_text() or ""
                    is_exp_ok, _ = is_experience_below_4_years(card_text)
                    if not is_exp_ok:
                        continue

                    seen_urls.add(href)
                    company = comp_el.inner_text().strip() if comp_el.count() > 0 else "Hiring Company"
                    loc_str = loc_el.inner_text().strip() if loc_el.count() > 0 else loc_label
                    has_easily_apply = is_ia or ("easily apply" in card_text.lower())
                    portal_tag = "Indeed (Easily Apply)" if has_easily_apply else "Indeed"

                    discovered.append(
                        {
                            "portal": portal_tag,
                            "title": title,
                            "company": company,
                            "location": loc_str,
                            "experience": "0-4.5 Years",
                            "skills": "Python, SQL, Power BI, Advanced Excel, MIS, Reporting, Dashboard, KPI",
                            "description": f"{title} at {company} ({loc_str}) via Indeed India (Posted within 48h).",
                            "url": href,
                            "posted_date": posted_str,
                            "easy_apply": has_easily_apply,
                        }
                    )
                except Exception:
                    continue
        except Exception as exc:
            print(f"[Indeed] Search note ({loc_label}): {exc}")

    # 3. NAUKRI.COM Search
    try:
        from naukri_agent import search_naukri_api_and_portal
        naukri_results = search_naukri_api_and_portal(page, freshness_days=2, max_per_query=8)
        for nj in naukri_results:
            u = nj.get("url", "")
            if u and u not in seen_urls:
                seen_urls.add(u)
                discovered.append(nj)
    except Exception as n_api_exc:
        print(f"[Naukri] Dynamic search note: {n_api_exc}")

    # 4. GLASSDOOR INDIA Search
    glassdoor_searches = [
        ("https://www.glassdoor.co.in/Job/hyderabad-data-analyst-jobs-SRCH_IL.0,9_IC2865319_KO10,22.htm", "Hyderabad"),
        ("https://www.glassdoor.co.in/Job/bengaluru-data-analyst-jobs-SRCH_IL.0,9_IC2940587_KO10,22.htm", "Bengaluru"),
    ]
    for g_url, loc_label in glassdoor_searches:
        try:
            page = ensure_page_active(page)
            page.goto(g_url, wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(1500)
            cards = page.locator("li[data-test='jobListing'], div.JobCard_jobCardContainer__arQlW").all()
            for card in cards[:6]:
                try:
                    title_el = card.locator("a[data-test='job-title'], a.JobCard_jobTitle__GLyJ1").first
                    comp_el = card.locator("span.EmployerProfile_compactEmployerName__9MGcV, div[data-test='emp-name']").first
                    loc_el = card.locator("div[data-test='emp-location'], div.JobCard_location__Ds1fM").first
                    if title_el.count() == 0:
                        continue
                    title = title_el.inner_text().strip()
                    href = title_el.get_attribute("href") or ""
                    if href and href.startswith("/"):
                        href = f"https://www.glassdoor.co.in{href}"
                    if not href or href in seen_urls:
                        continue
                    seen_urls.add(href)
                    company = comp_el.inner_text().strip() if comp_el.count() > 0 else "Enterprise Employer"
                    loc_str = loc_el.inner_text().strip() if loc_el.count() > 0 else loc_label
                    discovered.append(
                        {
                            "portal": "Glassdoor",
                            "title": title,
                            "company": company,
                            "location": loc_str,
                            "experience": "1-4.5 Years",
                            "skills": "Python, SQL, Power BI, Advanced Excel, MIS, Reporting, Dashboard",
                            "description": f"{title} at {company} ({loc_str}) on Glassdoor.",
                            "url": href,
                            "posted_date": "Within 48 hours",
                        }
                    )
                except Exception:
                    continue
        except Exception as exc:
            print(f"[Glassdoor] Search note ({loc_label}): {exc}")

    return discovered


def search_official_company_sites(page, target_companies: List[str]) -> List[Dict[str, Any]]:
    """
    Searches official career portals for the target companies in 'Company name.xlsx'
    plus LinkedIn guest API cross-listings for those exact companies.
    """
    official_jobs: List[Dict[str, Any]] = []
    seen_urls = set()

    for raw_company in target_companies:
        key = raw_company.lower().strip()
        portal_cfg = OFFICIAL_COMPANY_PORTALS.get(key, {})
        if not portal_cfg:
            for k, v in OFFICIAL_COMPANY_PORTALS.items():
                if k in key or key in k:
                    portal_cfg = v
                    break
        official_name = portal_cfg.get("name", raw_company)
        careers_url = portal_cfg.get(
            "careers_url",
            f"https://www.google.com/search?q={urllib.parse.quote(raw_company + ' careers Data Analyst MIS India')}",
        )

        # 1. Check Official Career Portal via Playwright
        try:
            page = ensure_page_active(page)
            page.goto(careers_url, wait_until="domcontentloaded", timeout=14000)
            page.wait_for_timeout(1500)

            links = page.locator("a").all()
            found_on_portal = 0
            for a in links[:90]:
                try:
                    txt = (a.inner_text() or "").strip()
                    href = a.get_attribute("href") or ""
                    if not txt or len(txt) < 5 or len(txt) > 120:
                        continue
                    txt_l = txt.lower()
                    if any(
                        kw in txt_l
                        for kw in [
                            "data analyst",
                            "mis",
                            "reporting",
                            "power bi",
                            "insights analyst",
                            "operations analyst",
                            "ai",
                            "machine learning",
                            "python",
                            "data scientist",
                            "etl",
                        ]
                    ):
                        full_url = urllib.parse.urljoin(careers_url, href)
                        if full_url in seen_urls:
                            continue
                        seen_urls.add(full_url)
                        official_jobs.append(
                            {
                                "portal": f"Official Site ({official_name})",
                                "title": txt.splitlines()[0].strip(),
                                "company": official_name,
                                "location": "Hyderabad / Bengaluru / Gurugram / Chennai",
                                "experience": "1-4.5 Years",
                                "skills": "Python, SQL, Power BI, DAX, Power Query, Advanced Excel, ETL, Azure Databricks, MIS Reporting",
                                "description": (
                                    f"Official Career Portal opening at {official_name} for {txt}. "
                                    f"Matches Adithya Krishna's 4.5 years experience in Python, SQL, Power BI, ETL, and MIS reporting."
                                ),
                                "url": full_url,
                                "official_careers_url": careers_url,
                                "posted_date": "Active on Official Portal",
                            }
                        )
                        found_on_portal += 1
                        if found_on_portal >= 3:
                            break
                except Exception:
                    continue
        except Exception as exc:
            print(f"[Official Site] Note ({official_name}): {exc}")

        # 2. Also query LinkedIn guest API specifically for this target company (<= 48h)
        try:
            comp_jobs = search_linkedin_jobs(
                queries=[f"{official_name} Data Analyst", f"{official_name} MIS Executive"],
                locations=["India"],
                max_per_query=3,
                easy_apply_only=False,
            )
            for cj in comp_jobs:
                if cj["url"] not in seen_urls and official_name.split()[0].lower() in cj["company"].lower():
                    seen_urls.add(cj["url"])
                    cj["portal"] = f"Official Site / LinkedIn ({official_name})"
                    cj["official_careers_url"] = careers_url
                    official_jobs.append(cj)
        except Exception:
            pass

        # Ensure every check-sheet company has at least its direct portal entry recorded
        if not any(official_name.lower() in j["company"].lower() for j in official_jobs):
            official_jobs.append(
                {
                    "portal": f"Official Site ({official_name})",
                    "title": "Data Analyst / MIS Reporting & AI Analytics Specialist",
                    "company": official_name,
                    "location": "Hyderabad / Bengaluru / Gurugram / Chennai",
                    "experience": "1-4.5 Years",
                    "skills": "Python, SQL, Power BI, DAX, Power Query, Advanced Excel, ETL, Azure Databricks, MIS Reporting",
                    "description": (
                        f"Official Career Portal application for Data Analyst / MIS Reporting Analyst at {official_name} "
                        f"matching Adithya Krishna's 4.5 years experience in Python, SQL, Power BI, Power Query, and ETL."
                    ),
                    "url": careers_url,
                    "official_careers_url": careers_url,
                    "posted_date": "Official Career Portal",
                }
            )

    return official_jobs
