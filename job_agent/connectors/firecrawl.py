"""Firecrawl web search & webpage scraping connector and provider."""

from __future__ import annotations

import json
import os
from typing import Any
import urllib.error
import urllib.request

from ..base import BaseProvider
from ..env import load_dotenv
from ..models import JobListing, SearchConfig, SiteRunStatus
from .normalize import webpage_result_to_job

DEFAULT_FIRECRAWL_BASE_URL = "https://api.firecrawl.dev/v1"
DEFAULT_JOB_DOMAINS = [
    "linkedin.com/jobs",
    "naukri.com",
    "ziprecruiter.com",
]


class FirecrawlConnector:
    """Zero-dependency HTTP client for Firecrawl `/search` and `/scrape` (v1/v2 & self-hosted)."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: int = 35,
    ) -> None:
        load_dotenv()
        self.api_key = (api_key or os.environ.get("FIRECRAWL_API_KEY", "")).strip()
        self.base_url = (
            base_url
            or os.environ.get("FIRECRAWL_API_URL")
            or DEFAULT_FIRECRAWL_BASE_URL
        ).rstrip("/")
        self.timeout = timeout

    @property
    def is_configured(self) -> bool:
        # Self-hosted Firecrawl may run without an API key; cloud requires FIRECRAWL_API_KEY.
        is_self_hosted = "api.firecrawl.dev" not in self.base_url
        return bool(self.api_key) or is_self_hosted

    def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.is_configured:
            raise RuntimeError(
                "FIRECRAWL_API_KEY is not set. Export FIRECRAWL_API_KEY in your shell or add it to `.env` "
                "(or set FIRECRAWL_API_URL for a self-hosted Firecrawl instance)."
            )
        url = f"{self.base_url}{endpoint}"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "job-search-agent/1.1",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers=headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8", errors="ignore"))
        except urllib.error.HTTPError as err:
            detail = err.read().decode("utf-8", errors="ignore")[:300]
            raise RuntimeError(f"Firecrawl API HTTP {err.code}: {detail}") from err

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        scrape_markdown: bool = True,
        country: str = "in",
        lang: str = "en",
        tbs: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search web pages via Firecrawl `/search` and optionally return full page markdown."""
        payload: dict[str, Any] = {
            "query": query,
            "limit": max(1, min(limit, 25)),
            "lang": lang,
            "country": country,
        }
        if tbs:
            payload["tbs"] = tbs
        if scrape_markdown:
            payload["scrapeOptions"] = {"formats": ["markdown"]}

        data = self._post("/search", payload)
        raw = data.get("data", [])
        # Support both Firecrawl v1 (`data: [...]`) and v2 (`data: { web: [...] }`).
        if isinstance(raw, dict):
            return list(raw.get("web") or raw.get("results") or [])
        if isinstance(raw, list):
            return raw
        return []

    def scrape(self, url: str, *, only_main_content: bool = True) -> dict[str, Any]:
        """Scrape a single job posting webpage into clean Markdown + metadata."""
        payload = {
            "url": url,
            "formats": ["markdown"],
            "onlyMainContent": only_main_content,
        }
        data = self._post("/scrape", payload)
        result = data.get("data")
        return result if isinstance(result, dict) else data


def parse_firecrawl_results(
    results: list[dict[str, Any]],
    *,
    query_matched: str = "",
    location_searched: str = "India",
) -> list[JobListing]:
    """Convert Firecrawl `/search` results into normalized JobListing objects."""
    jobs: list[JobListing] = []
    for item in results:
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        url = str(item.get("url") or metadata.get("sourceURL") or "").strip()
        title = str(item.get("title") or metadata.get("title") or "").strip()
        if not url and not title:
            continue
        content = str(
            item.get("markdown")
            or item.get("description")
            or metadata.get("description")
            or ""
        )
        jobs.append(
            webpage_result_to_job(
                url=url,
                raw_title=title,
                content_text=content,
                connector_name="firecrawl",
                query_matched=query_matched,
                location_searched=location_searched,
            )
        )
    return jobs


class FirecrawlProvider(BaseProvider):
    """Job search provider backed by Firecrawl Search + Markdown extraction."""

    site_name = "firecrawl"
    login_url = "https://www.firecrawl.dev/app/api-keys"

    def __init__(self, config: SearchConfig, connector: FirecrawlConnector | None = None) -> None:
        super().__init__(config)
        self.connector = connector or FirecrawlConnector()

    def search_public(
        self,
        queries: list[str],
        locations: list[str],
        max_results_per_query: int,
    ) -> tuple[list[JobListing], SiteRunStatus]:
        if not self.connector.is_configured:
            return [], SiteRunStatus(
                site=self.site_name,
                mode_used="api",
                status="missing_api_key",
                jobs_found=0,
                message=(
                    "FIRECRAWL_API_KEY is not configured. Add FIRECRAWL_API_KEY=fc-... to `.env` "
                    "(or set FIRECRAWL_API_URL for self-hosted Firecrawl) to search & extract job webpages."
                ),
            )

        domains = self.config.web_search_domains or DEFAULT_JOB_DOMAINS
        domain_clause = " OR ".join(f"site:{d}" for d in domains[:5])
        collected: list[JobListing] = []
        seen_urls: set[str] = set()
        tbs: str | None = None
        if 0 < self.config.max_age_hours <= 24:
            tbs = "qdr:d"
        elif 24 < self.config.max_age_hours <= 168:
            tbs = "qdr:w"
        exp_clause = (
            f'"{self.config.min_experience_years}+ years"'
            if self.config.min_experience_years > 0
            else ""
        )

        for query in queries:
            for location in locations:
                city = location.split(",")[0].strip()
                fc_query = f'({domain_clause}) "{query}" {exp_clause} {city} India'.strip()
                try:
                    raw_results = self.connector.search(
                        fc_query,
                        limit=max_results_per_query,
                        scrape_markdown=self.config.enrich_details,
                        tbs=tbs,
                    )
                except Exception as exc:
                    return collected, SiteRunStatus(
                        site=self.site_name,
                        mode_used="api",
                        status="partial" if collected else "error",
                        jobs_found=len(collected),
                        message=str(exc),
                    )

                for job in parse_firecrawl_results(
                    raw_results, query_matched=query, location_searched=location
                ):
                    if job.url and job.url in seen_urls:
                        continue
                    if job.url:
                        seen_urls.add(job.url)
                    collected.append(job)

                self.polite_sleep()

        return collected, SiteRunStatus(
            site=self.site_name,
            mode_used="api",
            status="ok",
            jobs_found=len(collected),
            message=f"Fetched {len(collected)} job webpages via Firecrawl.",
        )

    def search_browser(
        self,
        queries: list[str],
        locations: list[str],
        max_results_per_query: int,
        *,
        headless: bool = False,
    ) -> tuple[list[JobListing], SiteRunStatus]:
        return self.search_public(queries, locations, max_results_per_query)
