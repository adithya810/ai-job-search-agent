"""Base provider abstraction and polite HTTP/HTML helpers (cycle-free core module)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from html import unescape
import re
import time
import urllib.error
import urllib.request

from .models import JobListing, SearchConfig, SiteRunStatus

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def strip_html(raw_html: str) -> str:
    """Convert an HTML fragment into normalized plain text."""
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw_html, flags=re.S | re.I)
    text = re.sub(r"<(br|p|div|li|h[1-6])[^>]*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def fetch_url(
    url: str,
    *,
    timeout: int = 12,
    extra_headers: dict[str, str] | None = None,
) -> tuple[int, str]:
    """Fetch a URL politely using stdlib urllib; returns (http_status, body_text)."""
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as err:
        body = ""
        try:
            body = err.read().decode("utf-8", errors="ignore")
        except Exception:
            pass
        return err.code, body


class BaseProvider(ABC):
    """Abstract base class for hybrid (public + browser + API/MCP) job search providers."""

    site_name: str = ""
    login_url: str = ""
    email_selectors: tuple[str, ...] = ()

    def __init__(self, config: SearchConfig) -> None:
        self.config = config

    def polite_sleep(self) -> None:
        if self.config.request_delay_seconds > 0:
            time.sleep(self.config.request_delay_seconds)

    @abstractmethod
    def search_public(
        self,
        queries: list[str],
        locations: list[str],
        max_results_per_query: int,
    ) -> tuple[list[JobListing], SiteRunStatus]:
        """Search public listings or APIs without requiring browser sign-in."""

    @abstractmethod
    def search_browser(
        self,
        queries: list[str],
        locations: list[str],
        max_results_per_query: int,
        *,
        headless: bool = False,
    ) -> tuple[list[JobListing], SiteRunStatus]:
        """Search using the persistent local Playwright browser profile."""

    def search(
        self,
        *,
        mode: str,
        queries: list[str],
        locations: list[str],
        max_results_per_query: int,
        headless: bool = False,
    ) -> tuple[list[JobListing], SiteRunStatus]:
        """Dispatch search according to requested mode: public | browser | hybrid."""
        if mode == "public":
            return self.search_public(queries, locations, max_results_per_query)
        if mode == "browser":
            return self.search_browser(
                queries, locations, max_results_per_query, headless=headless
            )
        jobs, status = self.search_public(queries, locations, max_results_per_query)
        if jobs or status.status == "ok":
            return jobs, status
        if status.status in ("requires_browser_session", "blocked_by_antibot"):
            return self.search_browser(
                queries, locations, max_results_per_query, headless=headless
            )
        return jobs, status
