"""ZipRecruiter hybrid job search provider (public check + persistent Playwright browser mode)."""

from __future__ import annotations

import hashlib
import math
import urllib.parse

from ..browser import detect_anti_bot_challenge, open_persistent_browser
from ..models import JobListing, SiteRunStatus
from .base import BaseProvider, fetch_url


def build_ziprecruiter_search_url(query: str, location: str, *, max_age_hours: int = 0) -> str:
    """Build a ZipRecruiter job search URL with optional `days` freshness filter."""
    params: dict[str, str] = {"search": query, "location": location}
    if max_age_hours > 0:
        params["days"] = str(max(1, math.ceil(max_age_hours / 24)))
    return f"https://www.ziprecruiter.com/jobs-search?{urllib.parse.urlencode(params)}"


def parse_ziprecruiter_cards_payload(
    raw_cards: list[dict], *, query_matched: str = "", location_searched: str = ""
) -> list[JobListing]:
    """Convert extracted ZipRecruiter DOM card dicts into normalized JobListing objects."""
    jobs: list[JobListing] = []
    for item in raw_cards:
        title = (item.get("title") or "").strip()
        if not title:
            continue
        url = (item.get("url") or "").strip()
        job_id = str(item.get("job_id") or "")
        if not job_id:
            seed = url or f"{title}|{item.get('company', '')}|{item.get('location', '')}"
            job_id = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]

        jobs.append(
            JobListing(
                job_id=job_id,
                source="ziprecruiter",
                title=title,
                company=(item.get("company") or "Unknown Company").strip(),
                location=(item.get("location") or location_searched).strip(),
                url=url,
                posted_date=(item.get("posted_date") or "").strip(),
                salary=(item.get("salary") or "").strip(),
                description=(item.get("description") or "").strip(),
                query_matched=query_matched,
                location_searched=location_searched,
            )
        )
    return jobs


class ZipRecruiterProvider(BaseProvider):
    """ZipRecruiter provider with transparent anti-bot reporting and persistent browser mode."""

    site_name = "ziprecruiter"
    login_url = "https://www.ziprecruiter.com/authn/login"
    email_selectors = (
        'input[type="email"]',
        'input[name="email"]',
        'input[id*="email" i]',
    )

    def search_public(
        self,
        queries: list[str],
        locations: list[str],
        max_results_per_query: int,
    ) -> tuple[list[JobListing], SiteRunStatus]:
        url = build_ziprecruiter_search_url(
            queries[0], locations[0], max_age_hours=self.config.max_age_hours
        )
        try:
            status_code, body = fetch_url(url)
        except Exception as exc:
            return [], SiteRunStatus(
                site=self.site_name,
                mode_used="public",
                status="error",
                jobs_found=0,
                message=f"Could not reach ZipRecruiter: {exc}",
            )

        challenge = detect_anti_bot_challenge(body, url)
        if status_code in (403, 429, 503) or challenge:
            reason = challenge or f"HTTP {status_code} anti-bot protection"
            return [], SiteRunStatus(
                site=self.site_name,
                mode_used="public",
                status="blocked_by_antibot",
                jobs_found=0,
                message=(
                    f"ZipRecruiter gated automated public HTTP requests ({reason}). "
                    "To search ZipRecruiter safely without bypassing protections, run "
                    "`python3 -m job_agent login --site ziprecruiter` in a visible browser on your "
                    "machine and then run `python3 -m job_agent search --mode browser --sites ziprecruiter`."
                ),
            )

        return [], SiteRunStatus(
            site=self.site_name,
            mode_used="public",
            status="requires_browser_session",
            jobs_found=0,
            message=(
                "ZipRecruiter requires a browser session to render search results. "
                "Run `python3 -m job_agent login --site ziprecruiter` and `--mode browser`."
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
                        url = build_ziprecruiter_search_url(
                            query, location, max_age_hours=self.config.max_age_hours
                        )
                        page.goto(url, wait_until="domcontentloaded", timeout=35000)
                        page.wait_for_timeout(2500)

                        html = page.content()
                        challenge = detect_anti_bot_challenge(html, page.url)
                        if challenge:
                            return collected, SiteRunStatus(
                                site=self.site_name,
                                mode_used="browser",
                                status="blocked_by_antibot",
                                jobs_found=len(collected),
                                message=(
                                    f"{challenge}. Complete verification directly in a visible "
                                    "browser via `python3 -m job_agent login --site ziprecruiter`."
                                ),
                            )

                        raw_cards = page.eval_on_selector_all(
                            'article[data-testid="job-card"], article.job_result, div.job_content',
                            """(els) => els.map(el => {
                                const titleEl = el.querySelector('h2 a, a.job_link, [data-testid="job-card-title"]');
                                const compEl = el.querySelector('[data-testid="job-card-company"], a.company_name, .t_org_link');
                                const locEl = el.querySelector('[data-testid="job-card-location"], .location, .t_location');
                                const salEl = el.querySelector('[data-testid="job-card-salary"], .salary');
                                const descEl = el.querySelector('p.job_snippet, [data-testid="job-card-snippet"]');
                                const linkEl = el.querySelector('a[href*="/c/"], a[href*="/jobs/"], a.job_link');
                                return {
                                    job_id: el.getAttribute('data-job-id') || '',
                                    title: titleEl ? titleEl.innerText.trim() : '',
                                    company: compEl ? compEl.innerText.trim() : '',
                                    location: locEl ? locEl.innerText.trim() : '',
                                    salary: salEl ? salEl.innerText.trim() : '',
                                    description: descEl ? descEl.innerText.trim() : '',
                                    url: linkEl ? linkEl.href : ''
                                };
                            })""",
                        )

                        parsed = parse_ziprecruiter_cards_payload(
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
            message=(
                f"Fetched {len(collected)} ZipRecruiter postings via persistent browser session."
                if collected
                else "No ZipRecruiter listings matched these India filters (ZipRecruiter mainly covers US/remote roles)."
            ),
        )
