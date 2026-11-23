"""LinkedIn hybrid job search provider (public guest API + persistent browser mode)."""

from __future__ import annotations

from html import unescape
import re
import time
from typing import Any
import urllib.parse

from ..browser import detect_anti_bot_challenge, open_persistent_browser
from ..models import JobListing, SiteRunStatus
from .base import BaseProvider, fetch_url, strip_html

LINKEDIN_GUEST_SEARCH_URL = (
    "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
)
LINKEDIN_GUEST_DETAIL_URL = (
    "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
)

CARD_SPLIT_RE = re.compile(r"<li>\s*<div[^>]*base-search-card", re.IGNORECASE)
URN_RE = re.compile(r'data-entity-urn="urn:li:jobPosting:(\d+)"', re.IGNORECASE)
HREF_RE = re.compile(r'class="base-card__full-link[^"]*"[^>]*href="([^"]+)"', re.IGNORECASE)
TITLE_RE = re.compile(r'class="base-search-card__title"[^>]*>(.*?)</h3>', re.IGNORECASE | re.S)
COMPANY_RE = re.compile(
    r'class="base-search-card__subtitle"[^>]*>(.*?)</h4>', re.IGNORECASE | re.S
)
LOCATION_RE = re.compile(
    r'class="job-search-card__location"[^>]*>(.*?)</span>', re.IGNORECASE | re.S
)
TIME_RE = re.compile(r'<time[^>]*datetime="([^"]+)"', re.IGNORECASE)
SALARY_RE = re.compile(
    r'class="job-search-card__salary-info"[^>]*>(.*?)</span>', re.IGNORECASE | re.S
)
DESC_RE = re.compile(
    r'class="show-more-less-html__markup[^"]*"[^>]*>(.*?)</div>', re.IGNORECASE | re.S
)


def parse_linkedin_guest_cards(
    html: str, *, query_matched: str = "", location_searched: str = ""
) -> list[JobListing]:
    """Parse job cards from LinkedIn's public guest search HTML response."""
    jobs: list[JobListing] = []
    parts = CARD_SPLIT_RE.split(html)
    for chunk in parts[1:]:
        urn_m = URN_RE.search(chunk)
        title_m = TITLE_RE.search(chunk)
        company_m = COMPANY_RE.search(chunk)
        if not title_m:
            continue

        job_id = urn_m.group(1) if urn_m else ""
        href_m = HREF_RE.search(chunk)
        raw_url = unescape(href_m.group(1)) if href_m else ""
        clean_url = raw_url.split("?")[0] if raw_url else (
            f"https://www.linkedin.com/jobs/view/{job_id}/" if job_id else ""
        )
        title = strip_html(title_m.group(1))
        company = strip_html(company_m.group(1)) if company_m else "Unknown Company"
        loc_m = LOCATION_RE.search(chunk)
        location = strip_html(loc_m.group(1)) if loc_m else location_searched
        time_m = TIME_RE.search(chunk)
        posted_date = time_m.group(1) if time_m else ""
        sal_m = SALARY_RE.search(chunk)
        salary = strip_html(sal_m.group(1)) if sal_m else ""

        jobs.append(
            JobListing(
                job_id=job_id,
                source="linkedin",
                title=title,
                company=company,
                location=location,
                url=clean_url,
                posted_date=posted_date,
                salary=salary,
                query_matched=query_matched,
                location_searched=location_searched,
            )
        )
    return jobs


def parse_linkedin_detail_description(html: str) -> str:
    """Extract clean job description text from LinkedIn's public jobPosting HTML."""
    match = DESC_RE.search(html)
    if not match:
        return ""
    return strip_html(match.group(1))[:6000]


class LinkedInProvider(BaseProvider):
    """LinkedIn provider supporting live public guest API and authenticated Playwright mode."""

    site_name = "linkedin"
    login_url = "https://www.linkedin.com/login"
    email_selectors = ("input#username", 'input[name="session_key"]')

    def search_public(
        self,
        queries: list[str],
        locations: list[str],
        max_results_per_query: int,
    ) -> tuple[list[JobListing], SiteRunStatus]:
        collected: list[JobListing] = []
        seen_ids: set[str] = set()
        rate_limited = False

        def _fetch_with_polite_retry(target_url: str) -> tuple[int, str]:
            code, text = fetch_url(target_url)
            if code == 429:
                time.sleep(max(2.5, self.config.request_delay_seconds * 2))
                code, text = fetch_url(target_url)
            return code, text

        for query in queries:
            for location in locations:
                query_params: dict[str, Any] = {
                    "keywords": query,
                    "location": location,
                    "start": 0,
                }
                if self.config.max_age_hours > 0:
                    query_params["f_TPR"] = f"r{self.config.max_age_hours * 3600}"
                if self.config.min_experience_years >= 3:
                    # LinkedIn experience filter: 4 = Mid-Senior level
                    query_params["f_E"] = "4"
                params = urllib.parse.urlencode(query_params)
                url = f"{LINKEDIN_GUEST_SEARCH_URL}?{params}"
                try:
                    status_code, body = _fetch_with_polite_retry(url)
                except Exception as exc:
                    return collected, SiteRunStatus(
                        site=self.site_name,
                        mode_used="public",
                        status="partial" if collected else "error",
                        jobs_found=len(collected),
                        message=f"Network error querying LinkedIn public endpoint: {exc}",
                    )

                if status_code == 429:
                    rate_limited = True
                    break
                if status_code != 200:
                    continue

                challenge = detect_anti_bot_challenge(body, url)
                if challenge:
                    return collected, SiteRunStatus(
                        site=self.site_name,
                        mode_used="public",
                        status="blocked_by_antibot",
                        jobs_found=len(collected),
                        message=challenge,
                    )

                cards = parse_linkedin_guest_cards(
                    body, query_matched=query, location_searched=location
                )[:max_results_per_query]
                for job in cards:
                    if job.job_id and job.job_id in seen_ids:
                        continue
                    if job.job_id:
                        seen_ids.add(job.job_id)
                    collected.append(job)

                self.polite_sleep()
            if rate_limited:
                break

        # Optionally fetch public job descriptions for richer skill & experience verification.
        enriched_count = 0
        if self.config.enrich_details and collected:
            limit = max(0, self.config.max_detail_fetches)
            # Prioritize senior / data analyst titles first when detail fetches are capped.
            prioritized = sorted(
                collected,
                key=lambda j: (
                    0 if "data analyst" in j.title.lower() else 1,
                    0 if any(k in j.title.lower() for k in ("senior", "sr", "lead", "l3", "l4", "ii", "iii")) else 1,
                ),
            )
            consecutive_429 = 0
            for job in prioritized[:limit]:
                if not job.job_id:
                    continue
                detail_url = LINKEDIN_GUEST_DETAIL_URL.format(job_id=job.job_id)
                try:
                    code, detail_html = _fetch_with_polite_retry(detail_url)
                    if code == 200:
                        consecutive_429 = 0
                        desc = parse_linkedin_detail_description(detail_html)
                        if desc:
                            job.description = desc
                            enriched_count += 1
                    elif code == 429:
                        consecutive_429 += 1
                        if consecutive_429 >= 3:
                            break
                        time.sleep(4.0)
                        continue
                except Exception:
                    continue
                self.polite_sleep()

        msg = (
            f"Fetched {len(collected)} unique public LinkedIn postings "
            f"(freshness<={self.config.max_age_hours}h; {enriched_count} enriched with full descriptions)."
        )
        if rate_limited:
            msg += " Stopped early due to HTTP 429 rate limiting."
        final_status = "ok"
        if rate_limited:
            final_status = "partial" if collected else "rate_limited"
        return collected, SiteRunStatus(
            site=self.site_name,
            mode_used="public",
            status=final_status,
            jobs_found=len(collected),
            message=msg,
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
        seen_ids: set[str] = set()
        try:
            with open_persistent_browser(self.config.profile_dir, headless=headless) as context:
                page = context.pages[0] if context.pages else context.new_page()
                for query in queries:
                    for location in locations:
                        query_params: dict[str, Any] = {
                            "keywords": query,
                            "location": location,
                        }
                        if self.config.max_age_hours > 0:
                            query_params["f_TPR"] = f"r{self.config.max_age_hours * 3600}"
                        if self.config.min_experience_years >= 3:
                            query_params["f_E"] = "4"
                        params = urllib.parse.urlencode(query_params)
                        url = f"https://www.linkedin.com/jobs/search/?{params}"
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
                                    f"{challenge}. Run `python3 -m job_agent login --site linkedin` "
                                    "to sign in manually in a visible window."
                                ),
                            )

                        # Support both authenticated cards and public guest layout in browser.
                        raw_cards = page.eval_on_selector_all(
                            "li[data-occludable-job-id], div.base-search-card",
                            """(els) => els.map(el => {
                                const id = el.getAttribute('data-occludable-job-id')
                                  || (el.getAttribute('data-entity-urn') || '').split(':').pop()
                                  || '';
                                const linkEl = el.querySelector('a.job-card-container__link, a.base-card__full-link');
                                const titleEl = el.querySelector('.job-card-list__title, .base-search-card__title, a.job-card-container__link');
                                const compEl = el.querySelector('.job-card-container__primary-description, .artdeco-entity-lockup__subtitle, .base-search-card__subtitle');
                                const locEl = el.querySelector('.job-card-container__metadata-item, .artdeco-entity-lockup__caption, .job-search-card__location');
                                return {
                                    job_id: id.trim(),
                                    title: titleEl ? titleEl.innerText.trim() : '',
                                    company: compEl ? compEl.innerText.trim() : '',
                                    location: locEl ? locEl.innerText.trim() : '',
                                    url: linkEl ? linkEl.href : ''
                                };
                            })""",
                        )
                        for item in raw_cards[:max_results_per_query]:
                            title = (item.get("title") or "").split("\n")[0].strip()
                            if not title:
                                continue
                            jid = str(item.get("job_id") or "")
                            if jid and jid in seen_ids:
                                continue
                            if jid:
                                seen_ids.add(jid)
                            href = (item.get("url") or "").split("?")[0]
                            if not href and jid:
                                href = f"https://www.linkedin.com/jobs/view/{jid}/"
                            collected.append(
                                JobListing(
                                    job_id=jid,
                                    source="linkedin",
                                    title=title,
                                    company=item.get("company") or "Unknown Company",
                                    location=item.get("location") or location,
                                    url=href,
                                    query_matched=query,
                                    location_searched=location,
                                )
                            )
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
            status="ok",
            jobs_found=len(collected),
            message=f"Fetched {len(collected)} LinkedIn postings via persistent browser session.",
        )
