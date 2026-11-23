"""Naukri hybrid job search provider (public check + persistent Playwright browser mode)."""

from __future__ import annotations

import json
import math
import re
import urllib.parse

from ..browser import detect_anti_bot_challenge, open_persistent_browser
from ..models import JobListing, SiteRunStatus
from .base import BaseProvider, fetch_url


def _slugify(value: str) -> str:
    primary = value.split(",")[0].strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", primary).strip("-")
    return slug or "india"


def build_naukri_search_url(
    query: str,
    location: str,
    *,
    max_age_hours: int = 0,
    min_experience_years: int = 0,
) -> str:
    """Build a canonical Naukri India search URL with optional freshness (jobAge) & experience params."""
    q_slug = _slugify(query)
    loc_slug = _slugify(location)
    params: dict[str, str] = {}
    if loc_slug in ("remote", "remote-india"):
        base = f"https://www.naukri.com/{q_slug}-jobs"
        params["wfhType"] = "2"
    else:
        base = f"https://www.naukri.com/{q_slug}-jobs-in-{loc_slug}"

    if max_age_hours > 0:
        params["jobAge"] = str(max(1, math.ceil(max_age_hours / 24)))
    if min_experience_years > 0:
        params["experience"] = str(min_experience_years)

    if params:
        return f"{base}?{urllib.parse.urlencode(params)}"
    return base


def parse_naukri_cards_payload(
    raw_cards: list[dict], *, query_matched: str = "", location_searched: str = ""
) -> list[JobListing]:
    """Convert extracted Naukri DOM card dicts into normalized JobListing objects."""
    jobs: list[JobListing] = []
    for item in raw_cards:
        title = (item.get("title") or "").strip()
        if not title:
            continue
        url = (item.get("url") or "").strip()
        job_id = str(item.get("job_id") or "")
        if not job_id and url:
            m = re.search(r"-(\d{6,})(?:\?|$)", url)
            if m:
                job_id = m.group(1)
        skills = [s.strip() for s in item.get("skills", []) if s and s.strip()]
        jobs.append(
            JobListing(
                job_id=job_id,
                source="naukri",
                title=title,
                company=(item.get("company") or "Unknown Company").strip(),
                location=(item.get("location") or location_searched).strip(),
                url=url,
                posted_date=(item.get("posted_date") or "").strip(),
                salary=(item.get("salary") or "").strip(),
                experience=(item.get("experience") or "").strip(),
                description=(item.get("description") or "").strip(),
                raw_skills=skills,
                query_matched=query_matched,
                location_searched=location_searched,
            )
        )
    return jobs


def parse_naukri_json_ld(
    html: str, *, query_matched: str = "", location_searched: str = ""
) -> list[JobListing]:
    """Parse JobPosting JSON-LD blocks if present in a public Naukri HTML response."""
    jobs: list[JobListing] = []
    for match in re.finditer(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
        html,
        re.IGNORECASE | re.S,
    ):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        entries = payload if isinstance(payload, list) else [payload]
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("@type") != "JobPosting":
                continue
            title = str(entry.get("title") or "").strip()
            if not title:
                continue
            org = entry.get("hiringOrganization") or {}
            company = org.get("name", "Unknown Company") if isinstance(org, dict) else "Unknown Company"
            jobs.append(
                JobListing(
                    job_id=str(entry.get("identifier", {}).get("value", "") if isinstance(entry.get("identifier"), dict) else ""),
                    source="naukri",
                    title=title,
                    company=str(company),
                    location=location_searched or "India",
                    url=str(entry.get("url") or ""),
                    posted_date=str(entry.get("datePosted") or ""),
                    description=str(entry.get("description") or "")[:4000],
                    query_matched=query_matched,
                    location_searched=location_searched,
                )
            )
    return jobs


class NaukriProvider(BaseProvider):
    """Naukri India provider supporting public checks and persistent Playwright browser sessions."""

    site_name = "naukri"
    login_url = "https://www.naukri.com/nlogin/login"
    email_selectors = (
        "input#usernameField",
        'input[placeholder*="Email" i]',
        'input[type="text"]',
    )

    def search_public(
        self,
        queries: list[str],
        locations: list[str],
        max_results_per_query: int,
    ) -> tuple[list[JobListing], SiteRunStatus]:
        # Naukri serves a client-rendered JavaScript SPA and gates raw API calls without a
        # real browser session. Try one polite public check for JSON-LD; otherwise report cleanly.
        sample_url = build_naukri_search_url(
            queries[0],
            locations[0],
            max_age_hours=self.config.max_age_hours,
            min_experience_years=self.config.min_experience_years,
        )
        try:
            status_code, body = fetch_url(sample_url)
        except Exception as exc:
            return [], SiteRunStatus(
                site=self.site_name,
                mode_used="public",
                status="error",
                jobs_found=0,
                message=f"Could not reach Naukri: {exc}",
            )

        if status_code in (403, 406, 429):
            return [], SiteRunStatus(
                site=self.site_name,
                mode_used="public",
                status="blocked_by_antibot",
                jobs_found=0,
                message=(
                    f"Naukri returned HTTP {status_code} for non-browser HTTP requests. "
                    "Run `python3 -m job_agent login --site naukri` and then "
                    "`python3 -m job_agent search --mode browser --sites naukri` locally."
                ),
            )

        jobs = parse_naukri_json_ld(body, query_matched=queries[0], location_searched=locations[0])
        if jobs:
            return jobs[:max_results_per_query], SiteRunStatus(
                site=self.site_name,
                mode_used="public",
                status="ok",
                jobs_found=len(jobs[:max_results_per_query]),
                message=f"Extracted {len(jobs[:max_results_per_query])} public Naukri JSON-LD jobs.",
            )

        return [], SiteRunStatus(
            site=self.site_name,
            mode_used="public",
            status="requires_browser_session",
            jobs_found=0,
            message=(
                "Naukri search listings render dynamically in a browser session (JS SPA). "
                "Run `python3 -m job_agent login --site naukri` once on your machine, then "
                "`python3 -m job_agent search --mode hybrid` (or `--mode browser`)."
            ),
        )

    def search_browser(
        self,
        queries: list[str],
        locations: list[str],
        max_results_per_query: int,
        *,
        headless: bool = False,
    ) -> tuple[list[JobListing], SiteRunStatus]:
        collected: list[JobListing] = []
        seen_urls: set[str] = set()

        try:
            with open_persistent_browser(self.config.profile_dir, headless=headless) as context:
                page = context.pages[0] if context.pages else context.new_page()
                for query in queries:
                    for location in locations:
                        url = build_naukri_search_url(
                            query,
                            location,
                            max_age_hours=self.config.max_age_hours,
                            min_experience_years=self.config.min_experience_years,
                        )
                        page.goto(url, wait_until="domcontentloaded", timeout=35000)
                        try:
                            page.wait_for_selector(
                                ".srp-jobtuple-wrapper, .cust-job-tuple, article.jobTuple",
                                timeout=9000,
                            )
                        except Exception:
                            pass

                        html = page.content()
                        challenge = detect_anti_bot_challenge(html, page.url)
                        if challenge:
                            return collected, SiteRunStatus(
                                site=self.site_name,
                                mode_used="browser",
                                status="blocked_by_antibot",
                                jobs_found=len(collected),
                                message=(
                                    f"{challenge}. Run `python3 -m job_agent login --site naukri` "
                                    "to verify in a visible browser window."
                                ),
                            )

                        raw_cards = page.eval_on_selector_all(
                            ".srp-jobtuple-wrapper, .cust-job-tuple, article.jobTuple",
                            """(els) => els.map(el => {
                                const titleEl = el.querySelector('a.title, .row1 a');
                                const compEl = el.querySelector('a.comp-name, .comp-name, .subTitle');
                                const expEl = el.querySelector('.expwdth, .experience');
                                const salEl = el.querySelector('.sal-wrap, .salary');
                                const locEl = el.querySelector('.locWdth, .location');
                                const descEl = el.querySelector('.job-desc, .job-description');
                                const dateEl = el.querySelector('.job-post-day, .fleft.postedDate');
                                const skillEls = Array.from(el.querySelectorAll('ul.tags-gt li, .tag-li'));
                                return {
                                    job_id: el.getAttribute('data-job-id') || '',
                                    title: titleEl ? titleEl.innerText.trim() : '',
                                    url: titleEl ? titleEl.href : '',
                                    company: compEl ? compEl.innerText.trim() : '',
                                    experience: expEl ? expEl.innerText.trim() : '',
                                    salary: salEl ? salEl.innerText.trim() : '',
                                    location: locEl ? locEl.innerText.trim() : '',
                                    description: descEl ? descEl.innerText.trim() : '',
                                    posted_date: dateEl ? dateEl.innerText.trim() : '',
                                    skills: skillEls.map(s => s.innerText.trim()).filter(Boolean)
                                };
                            })""",
                        )

                        parsed = parse_naukri_cards_payload(
                            raw_cards[:max_results_per_query],
                            query_matched=query,
                            location_searched=location,
                        )
                        for job in parsed:
                            if job.url and job.url in seen_urls:
                                continue
                            if job.url:
                                seen_urls.add(job.url)
                            collected.append(job)

                        self.polite_sleep()
        except Exception as exc:
            return collected, SiteRunStatus(
                site=self.site_name,
                mode_used="browser",
                status="error",
                jobs_found=len(collected),
                message=str(exc),
            )

        return collected, SiteRunStatus(
            site=self.site_name,
            mode_used="browser",
            status="ok" if collected else "partial",
            jobs_found=len(collected),
            message=f"Fetched {len(collected)} Naukri postings via persistent browser session.",
        )
