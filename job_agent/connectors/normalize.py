"""Normalize generic web search results (Exa, Firecrawl, MCP) into JobListing objects."""

from __future__ import annotations

import hashlib
import re
import urllib.parse

from ..models import JobListing

BOARD_DOMAIN_MAP = (
    ("linkedin.com", "linkedin"),
    ("naukri.com", "naukri"),
    ("ziprecruiter.com", "ziprecruiter"),
    ("indeed.com", "indeed"),
    ("glassdoor.", "glassdoor"),
    ("foundit.in", "foundit"),
    ("instahyre.com", "instahyre"),
    ("wellfound.com", "wellfound"),
    ("lever.co", "lever"),
    ("greenhouse.io", "greenhouse"),
)

INDIA_CITY_PATTERNS = (
    ("Bengaluru, Karnataka, India", re.compile(r"\b(bengaluru|bangalore)\b", re.I)),
    ("Hyderabad, Telangana, India", re.compile(r"\bhyderabad\b", re.I)),
    ("Pune, Maharashtra, India", re.compile(r"\bpune\b", re.I)),
    ("Mumbai, Maharashtra, India", re.compile(r"\bmumbai\b", re.I)),
    ("Chennai, Tamil Nadu, India", re.compile(r"\bchennai\b", re.I)),
    ("Gurugram, Haryana, India", re.compile(r"\b(gurugram|gurgaon)\b", re.I)),
    ("Noida, Uttar Pradesh, India", re.compile(r"\bnoida\b", re.I)),
    ("Delhi NCR, India", re.compile(r"\b(new delhi|delhi ncr|delhi)\b", re.I)),
    ("Remote India", re.compile(r"\bremote\b.*\bindia\b|\bindia\b.*\bremote\b", re.I)),
)


def infer_source_from_url(url: str, fallback: str = "web") -> str:
    """Identify the underlying job board from a webpage URL, or fall back to connector name."""
    host = urllib.parse.urlparse(url).netloc.lower()
    for domain_fragment, source_name in BOARD_DOMAIN_MAP:
        if domain_fragment in host:
            return source_name
    return fallback


def parse_title_and_company(raw_title: str, url: str = "") -> tuple[str, str]:
    """Heuristically split job title and company from common web result title formats."""
    cleaned = re.sub(r"\s+", " ", (raw_title or "")).strip()
    # Strip trailing site branding like "| LinkedIn", "- Naukri.com", "| ZipRecruiter"
    cleaned = re.sub(
        r"\s*[\|\-–—]\s*(LinkedIn|Naukri(?:\.com)?|ZipRecruiter|Indeed|Glassdoor).*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()

    # Pattern: "Company hiring Title in Location" (LinkedIn search snippets)
    m_hiring = re.match(r"^(.+?)\s+hiring\s+(.+?)(?:\s+in\s+.+)?$", cleaned, re.IGNORECASE)
    if m_hiring:
        return m_hiring.group(2).strip(), m_hiring.group(1).strip()

    # Pattern: "Data Analyst at Acme Corp" or "Data Analyst @ Acme Corp"
    m_at = re.match(r"^(.+?)\s+(?:at|@)\s+(.+?)(?:\s*[\-\|–].*)?$", cleaned, re.IGNORECASE)
    if m_at:
        return m_at.group(1).strip(), m_at.group(2).strip()

    # Pattern: "Data Analyst - Acme Corp"
    for sep in (" - ", " – ", " | "):
        if sep in cleaned:
            parts = [p.strip() for p in cleaned.split(sep) if p.strip()]
            if len(parts) >= 2:
                return parts[0], parts[1]

    host = urllib.parse.urlparse(url).netloc.replace("www.", "")
    return cleaned or "Data Analyst", host or "Unknown Company"


def infer_location(text: str, default_location: str = "India") -> str:
    """Infer an Indian city/hub from snippet text, falling back to the searched location."""
    sample = (text or "")[:1500]
    for canonical, pattern in INDIA_CITY_PATTERNS:
        if pattern.search(sample):
            return canonical
    return default_location or "India"


def webpage_result_to_job(
    *,
    url: str,
    raw_title: str,
    content_text: str,
    connector_name: str,
    posted_date: str = "",
    query_matched: str = "",
    location_searched: str = "India",
) -> JobListing:
    """Convert any web search/scrape result into a normalized JobListing."""
    title, company = parse_title_and_company(raw_title, url)
    source = infer_source_from_url(url, fallback=connector_name)
    location = infer_location(f"{raw_title}\n{content_text}", default_location=location_searched)

    # Preserve connector attribution cleanly if source is a generic web domain
    job_id = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12] if url else hashlib.sha1(
        f"{title}|{company}".encode("utf-8")
    ).hexdigest()[:12]

    return JobListing(
        job_id=job_id,
        source=source,
        title=title,
        company=company,
        location=location,
        url=url,
        posted_date=(posted_date or "")[:10],
        description=re.sub(r"\s+", " ", content_text or "").strip()[:6000],
        query_matched=f"{query_matched} [{connector_name}]".strip(),
        location_searched=location_searched,
    )
