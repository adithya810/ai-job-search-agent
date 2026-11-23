"""Data models and configuration loader for the job search agent."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


@dataclass
class JobListing:
    """Normalized representation of a job posting across job boards & web connectors."""

    job_id: str
    source: str  # "linkedin" | "naukri" | "ziprecruiter" | "exa" | "firecrawl" | ...
    title: str
    company: str
    location: str
    url: str
    posted_date: str = ""
    salary: str = ""
    experience: str = ""
    work_mode: str = ""  # "Remote" | "Hybrid" | "On-site" | ""
    description: str = ""
    raw_skills: list[str] = field(default_factory=list)
    query_matched: str = ""
    location_searched: str = ""
    # Computed fields populated by scorer & deduplicator
    match_score: int = 0
    matched_core_skills: list[str] = field(default_factory=list)
    missing_core_skills: list[str] = field(default_factory=list)
    matched_bonus_skills: list[str] = field(default_factory=list)
    is_new: bool = True
    fingerprint: str = ""
    scraped_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SiteRunStatus:
    """Operational telemetry for a single job board or web connector provider run."""

    site: str
    mode_used: str  # "public" | "browser" | "api" | "mcp"
    status: str  # "ok" | "partial" | "requires_browser_session" | "blocked_by_antibot" | "missing_api_key" | "rate_limited" | "error"
    jobs_found: int = 0
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SearchConfig:
    """Runtime search configuration loaded from config.json."""

    email_hint: str
    sites: list[str]
    queries: list[str]
    locations: list[str]
    max_results_per_query: int
    enrich_details: bool
    max_detail_fetches: int
    request_delay_seconds: float
    profile_dir: Path
    output_dir: Path
    core_skills: dict[str, dict[str, Any]]
    bonus_skills: dict[str, dict[str, Any]]
    min_experience_years: int = 3
    max_age_hours: int = 48
    strict_experience_filter: bool = True
    strict_freshness_filter: bool = True
    web_search_domains: list[str] = field(
        default_factory=lambda: ["linkedin.com/jobs", "naukri.com", "ziprecruiter.com"]
    )
    mcp_servers: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_file(cls, config_path: Path) -> "SearchConfig":
        data = json.loads(config_path.read_text(encoding="utf-8"))
        base_dir = config_path.parent
        profile_dir = Path(data.get("profile_dir", ".browser_profile"))
        output_dir = Path(data.get("output_dir", "output"))
        if not profile_dir.is_absolute():
            profile_dir = (base_dir / profile_dir).resolve()
        if not output_dir.is_absolute():
            output_dir = (base_dir / output_dir).resolve()
        return cls(
            email_hint=data.get("email_hint", ""),
            sites=list(data.get("sites", ["linkedin", "naukri", "ziprecruiter", "exa", "firecrawl"])),
            queries=list(data.get("queries", ["Data Analyst"])),
            locations=list(data.get("locations", ["India"])),
            max_results_per_query=int(data.get("max_results_per_query", 20)),
            enrich_details=bool(data.get("enrich_details", True)),
            max_detail_fetches=int(data.get("max_detail_fetches", 40)),
            request_delay_seconds=float(data.get("request_delay_seconds", 1.4)),
            profile_dir=profile_dir,
            output_dir=output_dir,
            core_skills=dict(data.get("core_skills", {})),
            bonus_skills=dict(data.get("bonus_skills", {})),
            min_experience_years=int(data.get("min_experience_years", 3)),
            max_age_hours=int(data.get("max_age_hours", 48)),
            strict_experience_filter=bool(data.get("strict_experience_filter", True)),
            strict_freshness_filter=bool(data.get("strict_freshness_filter", True)),
            web_search_domains=list(
                data.get("web_search_domains", ["linkedin.com/jobs", "naukri.com", "ziprecruiter.com"])
            ),
            mcp_servers=dict(data.get("mcp_servers", {})),
        )
