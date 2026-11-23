import os
import re
import json
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

from config import (
    EXA_API_KEY,
    FIRECRAWL_API_KEY,
    MCP_DISCOVERED_JOBS_JSON,
)


def is_exa_configured() -> bool:
    return bool(EXA_API_KEY and len(EXA_API_KEY.strip()) > 10)


def is_firecrawl_configured() -> bool:
    return bool(FIRECRAWL_API_KEY and FIRECRAWL_API_KEY.startswith("fc-"))


def get_exa_client():
    if not is_exa_configured():
        return None
    try:
        from exa_py import Exa
        return Exa(api_key=EXA_API_KEY)
    except Exception as exc:
        print(f"[Exa] Client init note: {exc}")
        return None


def get_firecrawl_app():
    if not is_firecrawl_configured():
        return None
    try:
        from firecrawl import FirecrawlApp
        return FirecrawlApp(api_key=FIRECRAWL_API_KEY)
    except Exception:
        try:
            from firecrawl import Firecrawl
            return Firecrawl(api_key=FIRECRAWL_API_KEY)
        except Exception as exc:
            print(f"[Firecrawl] Client init note: {exc}")
            return None


def _markdown_from(res: Any) -> Optional[str]:
    if res is None:
        return None
    if isinstance(res, dict):
        data = res.get("data") if isinstance(res.get("data"), dict) else {}
        return res.get("markdown") or res.get("content") or data.get("markdown") or ""
    return getattr(res, "markdown", None)


def scrape_with_firecrawl(url: str) -> Optional[str]:
    """Scrapes a web page using Firecrawl and returns clean LLM-ready markdown."""
    if not is_firecrawl_configured():
        return None
    try:
        app = get_firecrawl_app()
        if not app:
            return None
        try:
            res = app.scrape(url, formats=["markdown"])
        except (AttributeError, TypeError):
            res = app.scrape_url(url, formats=["markdown"])
        return _markdown_from(res)
    except Exception as exc:
        print(f"[Firecrawl] Scrape notice for {url}: {exc}")
    return None


def _clean_job_url(url: str) -> str:
    if not url:
        return ""
    u = url.strip()
    if not u.startswith("http"):
        return ""
    return u.split("#")[0]


def _extract_skills(text: str) -> str:
    if not text:
        return "Python, SQL, Power BI, Advanced Excel, Pandas, ETL, MIS Reporting"
    skill_keywords = [
        "Python", "Pandas", "NumPy", "Scikit-learn", "TensorFlow", "PyTorch", "spaCy", "Keras",
        "Machine Learning", "Deep Learning", "NLP", "Generative AI", "LLMs", "Prompt Engineering",
        "SQL", "SQL Server", "MySQL", "SSMS", "SSIS", "ETL", "Azure", "Databricks", "PySpark",
        "Power BI", "DAX", "Power Query", "Power Automate", "RLS", "Advanced Excel", "Excel",
        "MIS", "KPI Reporting", "Dashboard", "Data Validation", "Data Reconciliation"
    ]
    found = [sk for sk in skill_keywords if re.search(r"\b" + re.escape(sk.lower()) + r"\b", text.lower())]
    return ", ".join(found) if found else "Python, SQL, Power BI, Advanced Excel, MIS, Data Analysis"


def _parse_iso(dt_str: Optional[str]) -> Optional[datetime]:
    if not dt_str:
        return None
    try:
        s = dt_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _job_from_search_hit(
    url: str,
    title: str,
    text: str,
    location_hint: str,
    posted_label: str = "Within 48 hours",
    posted_at: str = "",
) -> Optional[Dict[str, Any]]:
    if not url or not title:
        return None
    clean_t = re.sub(r"\s*\|\s*(LinkedIn|Naukri\.com|Indeed.*|Glassdoor.*)$", "", title, flags=re.I).strip()
    company = "Hiring Organization"
    role_title = clean_t

    m_hiring = re.match(r"^(.+?)\s+hiring\s+(.+?)\s+in\s+(.+)$", clean_t, flags=re.I)
    if m_hiring:
        company = m_hiring.group(1).strip()
        role_title = m_hiring.group(2).strip()
        location_hint = m_hiring.group(3).strip()
    elif " - " in clean_t:
        parts = [p.strip() for p in clean_t.split(" - ") if p.strip()]
        if len(parts) >= 2:
            role_title = parts[0]
            company = parts[-1] if "years" not in parts[-1].lower() else (parts[-2] if len(parts) >= 3 else "Enterprise Employer")
    elif " at " in clean_t:
        parts = clean_t.split(" at ", 1)
        role_title = parts[0].strip()
        company = parts[1].strip()

    portal = "Exa / Firecrawl Web Discovery"
    if "linkedin.com" in url:
        portal = "LinkedIn (Exa/Firecrawl)"
    elif "naukri.com" in url:
        portal = "Naukri (Exa/Firecrawl)"
    elif "indeed." in url:
        portal = "Indeed (Exa/Firecrawl)"
    elif "deloitte" in url:
        portal = "Official Site (Deloitte)"
        company = "Deloitte"
    elif "accenture" in url:
        portal = "Official Site (Accenture)"
        company = "Accenture"
    elif "nttdata" in url or "ntt" in url:
        portal = "Official Site (NTT DATA)"
        company = "NTT DATA"

    desc = (text or f"{role_title} at {company} ({location_hint})").strip()[:4000]
    skills = _extract_skills(f"{role_title} {desc}")

    return {
        "portal": portal,
        "title": role_title[:120],
        "company": company[:80],
        "location": location_hint,
        "experience": "0-4.5 Years",
        "skills": skills,
        "description": desc,
        "url": url,
        "posted_date": posted_label,
        "published_at": posted_at,
    }


def load_mcp_discovered_jobs() -> List[Dict[str, Any]]:
    """Loads jobs discovered via Exa & Firecrawl MCP tools saved in mcp_discovered_jobs.json."""
    if not MCP_DISCOVERED_JOBS_JSON.exists():
        return []
    try:
        data = json.loads(MCP_DISCOVERED_JOBS_JSON.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        return data.get("jobs", [])
    except Exception as exc:
        print(f"[MCP Jobs] Load note: {exc}")
        return []


def search_jobs_with_exa(
    queries: List[str],
    locations: List[str],
    max_per_query: int = 5,
    max_queries: int = 4,
    hours: int = 48,
) -> List[Dict[str, Any]]:
    """
    Uses Exa SDK to find LinkedIn / Naukri / Indeed / Company job pages published recently.
    Also merges verified Exa & Firecrawl MCP discoveries stored in mcp_discovered_jobs.json.
    """
    discovered: List[Dict[str, Any]] = []
    seen_urls = set()

    # 1. Load MCP-verified Exa & Firecrawl discoveries first
    for mj in load_mcp_discovered_jobs():
        u = _clean_job_url(mj.get("url", ""))
        if u and u not in seen_urls:
            seen_urls.add(u)
            discovered.append(mj)

    client = get_exa_client()
    if client is None:
        return discovered

    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    start_date = since.strftime("%Y-%m-%d")

    for q in queries[:max_queries]:
        for loc in locations[:4]:
            query = f"{q} job opening in {loc} India"
            try:
                res = client.search_and_contents(
                    query,
                    num_results=max_per_query,
                    include_domains=["linkedin.com", "naukri.com", "in.indeed.com"],
                    start_published_date=start_date,
                    text={"max_characters": 3000},
                )
            except Exception as exc:
                print(f"[Exa] Search notice ({q} - {loc}): {exc}")
                continue

            for r in getattr(res, "results", []) or []:
                url = _clean_job_url(getattr(r, "url", "") or "")
                if not url or url in seen_urls:
                    continue
                published = _parse_iso(getattr(r, "published_date", None))
                job = _job_from_search_hit(
                    url=url,
                    title=getattr(r, "title", "") or "",
                    text=getattr(r, "text", "") or "",
                    location_hint=loc,
                    posted_label="Within 48 hours",
                    posted_at=published.isoformat() if published else "",
                )
                if job:
                    seen_urls.add(url)
                    discovered.append(job)

    print(f"[Exa] Discovered {len(discovered)} job pages (MCP + Exa SDK) from the last {hours}h.")
    return discovered


def _iter_search_results(res: Any) -> list:
    if res is None:
        return []
    if isinstance(res, dict):
        items = res.get("web") or res.get("data") or res.get("results")
    else:
        items = getattr(res, "web", None) or getattr(res, "data", None) or getattr(res, "results", None)
    if isinstance(items, dict):
        items = items.get("web") or []
    return list(items or [])


def _field(item: Any, name: str) -> str:
    value = item.get(name) if isinstance(item, dict) else getattr(item, name, None)
    return value or ""


def search_jobs_with_firecrawl(queries: List[str], locations: List[str]) -> List[Dict[str, Any]]:
    """Fallback / complementary discovery through Firecrawl search."""
    if not is_firecrawl_configured():
        return []

    app = get_firecrawl_app()
    if not app:
        return []

    discovered: List[Dict[str, Any]] = []
    seen_urls = set()

    for q in queries[:2]:
        for loc in locations[:2]:
            search_text = f'"{q}" {loc} jobs (site:linkedin.com/jobs/view OR site:naukri.com/job-listings OR site:in.indeed.com)'
            try:
                try:
                    res = app.search(search_text, limit=6, tbs="qdr:d2")
                except TypeError:
                    res = app.search(search_text, limit=6)
            except Exception as exc:
                print(f"[Firecrawl] Search notice ({q} - {loc}): {exc}")
                continue

            for item in _iter_search_results(res):
                url = _clean_job_url(_field(item, "url"))
                if not url or url in seen_urls:
                    continue
                job = _job_from_search_hit(
                    url=url,
                    title=_field(item, "title"),
                    text=_field(item, "markdown") or _field(item, "description"),
                    location_hint=loc,
                    posted_label="Within 48 hours",
                )
                if job:
                    seen_urls.add(url)
                    discovered.append(job)

    print(f"[Firecrawl] Discovered {len(discovered)} job pages via Firecrawl search.")
    return discovered


def discover_jobs_via_search(
    queries: List[str],
    locations: List[str],
    max_per_query: int = 5,
) -> List[Dict[str, Any]]:
    """Combines Exa search + MCP discoveries + Firecrawl search fallback."""
    jobs = search_jobs_with_exa(queries, locations, max_per_query=max_per_query)
    fc_jobs = search_jobs_with_firecrawl(queries, locations)
    seen = {j.get("url") for j in jobs if j.get("url")}
    for fj in fc_jobs:
        if fj.get("url") not in seen:
            seen.add(fj.get("url"))
            jobs.append(fj)
    return jobs


def enrich_job_description(job: Dict[str, Any], page=None, min_chars: int = 350) -> Dict[str, Any]:
    """Ensures job['description'] has rich text for resume skill matching."""
    current = job.get("description") or ""
    if len(current) >= min_chars:
        return job

    url = job.get("url") or ""
    if not url:
        return job

    md = scrape_with_firecrawl(url)
    if md and len(md) > len(current):
        job["description"] = md[:5000]
        job["skills"] = job.get("skills") or _extract_skills(md)
        job["description_source"] = "firecrawl"
        return job

    if page is not None:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(1200)
            text = page.inner_text("body") or ""
            if len(text) > len(current):
                job["description"] = text[:5000]
                job["skills"] = job.get("skills") or _extract_skills(text)
                job["description_source"] = "chrome"
        except Exception as exc:
            print(f"[Chrome] Could not read job page {url}: {exc}")

    return job
