"""Exa neural web search connector and provider for job search webpages."""

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

DEFAULT_EXA_BASE_URL = "https://api.exa.ai"
DEFAULT_JOB_DOMAINS = [
    "linkedin.com",
    "naukri.com",
    "ziprecruiter.com",
]


class ExaConnector:
    """Zero-dependency HTTP client for Exa Search (`/search`) and Contents (`/contents`)."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: int = 25,
    ) -> None:
        load_dotenv()
        self.api_key = (api_key or os.environ.get("EXA_API_KEY", "")).strip()
        self.base_url = (base_url or os.environ.get("EXA_API_URL") or DEFAULT_EXA_BASE_URL).rstrip("/")
        self.timeout = timeout

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError(
                "EXA_API_KEY is not set. Export EXA_API_KEY in your shell or add it to `.env`."
            )
        url = f"{self.base_url}{endpoint}"
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "x-api-key": self.api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "job-search-agent/1.1",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8", errors="ignore"))
        except urllib.error.HTTPError as err:
            detail = err.read().decode("utf-8", errors="ignore")[:300]
            raise RuntimeError(f"Exa API HTTP {err.code}: {detail}") from err

    def search(
        self,
        query: str,
        *,
        num_results: int = 10,
        include_domains: list[str] | None = None,
        search_type: str = "auto",
        max_characters: int = 4000,
        start_published_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """Run an Exa web search with inline text + highlights extraction."""
        payload: dict[str, Any] = {
            "query": query,
            "type": search_type,
            "numResults": max(1, min(num_results, 50)),
            "contents": {
                "text": {"maxCharacters": max_characters},
                "highlights": {"numSentences": 3},
            },
        }
        if include_domains:
            payload["includeDomains"] = include_domains
        if start_published_date:
            payload["startPublishedDate"] = start_published_date

        data = self._post("/search", payload)
        return list(data.get("results", []))

    def get_contents(self, urls: list[str], *, max_characters: int = 5000) -> list[dict[str, Any]]:
        """Fetch extracted clean webpage text for specific job URLs via Exa `/contents`."""
        if not urls:
            return []
        payload = {
            "ids": urls,
            "text": {"maxCharacters": max_characters},
        }
        data = self._post("/contents", payload)
        return list(data.get("results", []))


def parse_exa_results(
    results: list[dict[str, Any]],
    *,
    query_matched: str = "",
    location_searched: str = "India",
) -> list[JobListing]:
    """Convert Exa `/search` result items into normalized JobListing objects."""
    jobs: list[JobListing] = []
    for item in results:
        url = str(item.get("url") or "").strip()
        title = str(item.get("title") or "").strip()
        if not url and not title:
            continue
        text = str(item.get("text") or "")
        highlights = item.get("highlights") or []
        if not text and isinstance(highlights, list):
            text = " ".join(str(h) for h in highlights)
        published = str(item.get("publishedDate") or "")
        jobs.append(
            webpage_result_to_job(
                url=url,
                raw_title=title,
                content_text=text,
                connector_name="exa",
                posted_date=published,
                query_matched=query_matched,
                location_searched=location_searched,
            )
        )
    return jobs


class ExaProvider(BaseProvider):
    """Job search provider backed by the Exa Search API."""

    site_name = "exa"
    login_url = "https://dashboard.exa.ai/"

    def __init__(self, config: SearchConfig, connector: ExaConnector | None = None) -> None:
        super().__init__(config)
        self.connector = connector or ExaConnector()

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
                    "EXA_API_KEY is not configured. Add EXA_API_KEY=... to `.env` or your environment "
                    "(get a key at https://dashboard.exa.ai/) to search LinkedIn, Naukri, ZipRecruiter, "
                    "and company career pages via Exa."
                ),
            )

        domains = self.config.web_search_domains or DEFAULT_JOB_DOMAINS
        collected: list[JobListing] = []
        seen_urls: set[str] = set()
        start_pub: str | None = None
        if self.config.max_age_hours > 0:
            from datetime import datetime, timedelta, timezone

            start_pub = (
                datetime.now(timezone.utc) - timedelta(hours=self.config.max_age_hours)
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
        exp_clause = (
            f"{self.config.min_experience_years}+ years experience "
            if self.config.min_experience_years > 0
            else ""
        )

        for query in queries:
            for location in locations:
                city = location.split(",")[0].strip()
                exa_query = f"{query} job opening {exp_clause}in {city} India SQL Python Power BI Tableau"
                try:
                    raw_results = self.connector.search(
                        exa_query,
                        num_results=max_results_per_query,
                        include_domains=domains,
                        start_published_date=start_pub,
                    )
                except Exception as exc:
                    return collected, SiteRunStatus(
                        site=self.site_name,
                        mode_used="api",
                        status="partial" if collected else "error",
                        jobs_found=len(collected),
                        message=str(exc),
                    )

                for job in parse_exa_results(
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
            message=(
                f"Fetched {len(collected)} job webpages via Exa across "
                f"{', '.join(domains)}."
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
        # Exa is an API connector; browser mode delegates directly to the API search.
        return self.search_public(queries, locations, max_results_per_query)
