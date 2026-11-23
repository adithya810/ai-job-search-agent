"""Strict experience (>3 years) and freshness (<=48 hours) filtering for job postings."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from typing import Any

from .models import JobListing, SearchConfig

EXP_RANGE_PATTERNS = (
    # "3-5 years", "3 to 6 yrs", "4 – 8 years"
    re.compile(
        r"(?<!\d)(\d{1,2})\s*(?:-|–|—|to)\s*(\d{1,2})\s*\+?\s*(?:years?|yrs?)\b",
        re.IGNORECASE,
    ),
    # "3+ years", "5+ yrs", "minimum 4 years", "at least 4 years", "more than 3 years", "> 3 years"
    re.compile(
        r"(?:minimum|min\.?|at\s+least|more\s+than|over|>|>=)?\s*(?<!\d)(\d{1,2})\s*\+\s*(?:years?|yrs?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:minimum|min\.?|at\s+least|more\s+than|over|>=?)\s*(\d{1,2})\s*(?:years?|yrs?)\b",
        re.IGNORECASE,
    ),
    # "experience of 4 years", "4 years of experience"
    re.compile(
        r"(?<!\d)(\d{1,2})\s*(?:years?|yrs?)\s+(?:of\s+)?(?:relevant\s+|hands[- ]on\s+|work\s+|industry\s+|total\s+)?experience\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"experience\s*(?:of|:|-)?\s*(?<!\d)(\d{1,2})\s*(?:years?|yrs?)\b",
        re.IGNORECASE,
    ),
)

JUNIOR_TITLE_RE = re.compile(
    r"\b(intern|internship|fresher|trainee|apprentice|entry[- ]level|jr\.?|junior)\b",
    re.IGNORECASE,
)

RELATIVE_AGE_PATTERNS = (
    (re.compile(r"\b(just\s+now|today|few\s+seconds|moments?\s+ago)\b", re.I), 0.5),
    (re.compile(r"\b(\d+)\s*(?:min|minute)s?\s+ago\b", re.I), "minutes"),
    (re.compile(r"\b(\d+)\s*(?:hr|hour)s?\s+ago\b", re.I), "hours"),
    (re.compile(r"\byesterday\b", re.I), 24.0),
    (re.compile(r"\b(\d+)\s*\+?\s*days?\s+ago\b", re.I), "days"),
    (re.compile(r"\b(\d+)\s*\+?\s*weeks?\s+ago\b", re.I), "weeks"),
    (re.compile(r"\b(\d+)\s*\+?\s*months?\s+ago\b", re.I), "months"),
)


def parse_experience_bounds(text: str) -> tuple[int, int | None] | None:
    """Extract (min_years, max_years_or_None) from job experience/description text.

    Returns the highest-confidence range found (preferring explicit ranges or
    minimum-years clauses). Ignores implausible numbers (> 25 years).
    """
    if not text:
        return None

    # 1. Explicit range like "3-5 years" or "4 to 7 yrs"
    m_range = EXP_RANGE_PATTERNS[0].search(text)
    if m_range:
        lo, hi = int(m_range.group(1)), int(m_range.group(2))
        if 0 <= lo <= 25 and lo <= hi <= 30:
            return lo, hi

    # 2. Explicit lower bound like "4+ years", "more than 3 years", "minimum 4 years"
    for pat in EXP_RANGE_PATTERNS[1:]:
        m = pat.search(text)
        if m:
            lo = int(m.group(1))
            if 0 <= lo <= 25:
                full = m.group(0).lower()
                # "more than 3 years" / "> 3 years" strictly implies >= 4 years minimum
                if any(tok in full for tok in ("more than", "over", ">")) and ">=" not in full:
                    return lo + 1, None
                return lo, None

    return None


def meets_experience_requirement(
    job: JobListing,
    min_years: int,
    *,
    strict: bool = True,
) -> tuple[bool, str]:
    """Check whether a job meets the experience threshold (e.g. >3 / 3+ years)."""
    if min_years <= 0:
        return True, "experience filter disabled"

    bounds = parse_experience_bounds(job.experience) or parse_experience_bounds(job.description)
    if bounds is not None:
        lo, hi = bounds
        # Store normalized display string if experience wasn't populated yet
        if not job.experience:
            job.experience = f"{lo}-{hi} years" if hi is not None else f"{lo}+ years"
        # Require lower bound >= min_years AND upper bound (if finite) > min_years
        # so "1-3 years" or "2-4 years" are excluded, while "3-5 years", "3+ years", "4+ years" pass.
        if lo >= min_years and (hi is None or hi > min_years):
            return True, f"matches ({lo}-{hi} yrs)" if hi is not None else f"matches ({lo}+ yrs)"
        return False, f"experience below threshold ({lo}-{hi} yrs)" if hi is not None else f"experience below threshold ({lo} yrs)"

    # No explicit numeric experience found in posting
    if JUNIOR_TITLE_RE.search(job.title):
        return False, "junior/intern/fresher title"
    if strict:
        return False, "experience years not stated in posting"
    return True, "unverified experience allowed"


def estimate_age_hours(posted_date: str, now: datetime | None = None) -> float | None:
    """Estimate posting age in hours from an ISO date/timestamp or relative string."""
    raw = (posted_date or "").strip()
    if not raw:
        return None
    now_utc = now or datetime.now(timezone.utc)

    # 1. Relative human strings ("5 hours ago", "1 day ago", "Just now", etc.)
    for pattern, unit in RELATIVE_AGE_PATTERNS:
        m = pattern.search(raw)
        if m:
            if isinstance(unit, float):
                return unit
            val = float(m.group(1))
            if unit == "minutes":
                return val / 60.0
            if unit == "hours":
                return val
            if unit == "days":
                return val * 24.0
            if unit == "weeks":
                return val * 24.0 * 7.0
            if unit == "months":
                return val * 24.0 * 30.0

    # 2. ISO date-only ("2026-11-22") — date granularity only, so treat end-of-day UTC
    #    as lower bound on age, meaning dates within `floor(max_age/24)` days pass cleanly.
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        try:
            d = datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            day_diff = (now_utc.date() - d.date()).days
            if day_diff <= 0:
                return 0.0
            return float(day_diff * 24)
        except ValueError:
            return None

    # 3. Full ISO-8601 datetime ("2026-11-22T14:30:00Z" or with offset)
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta_hours = (now_utc - dt).total_seconds() / 3600.0
        return max(0.0, delta_hours)
    except ValueError:
        return None


def meets_freshness_requirement(
    job: JobListing,
    max_age_hours: int,
    *,
    strict: bool = True,
    now: datetime | None = None,
) -> tuple[bool, str]:
    """Check whether a job was uploaded within `max_age_hours` (e.g. <= 48 hours)."""
    if max_age_hours <= 0:
        return True, "freshness filter disabled"

    age = estimate_age_hours(job.posted_date, now=now)
    if age is None:
        if strict:
            return False, "posted time missing"
        return True, "unverified posted time allowed"

    if age <= float(max_age_hours):
        return True, f"fresh ({age:.1f}h <= {max_age_hours}h)"
    return False, f"stale ({age:.1f}h > {max_age_hours}h)"


def filter_jobs(
    jobs: list[JobListing],
    config: SearchConfig,
    *,
    now: datetime | None = None,
) -> tuple[list[JobListing], dict[str, Any]]:
    """Filter jobs by freshness (<= max_age_hours) and experience (>= min_experience_years)."""
    kept: list[JobListing] = []
    rejected_freshness = 0
    rejected_experience = 0

    for job in jobs:
        fresh_ok, _ = meets_freshness_requirement(
            job,
            config.max_age_hours,
            strict=config.strict_freshness_filter,
            now=now,
        )
        if not fresh_ok:
            rejected_freshness += 1
            continue

        exp_ok, _ = meets_experience_requirement(
            job,
            config.min_experience_years,
            strict=config.strict_experience_filter,
        )
        if not exp_ok:
            rejected_experience += 1
            continue

        kept.append(job)

    stats = {
        "input_count": len(jobs),
        "kept_count": len(kept),
        "rejected_freshness": rejected_freshness,
        "rejected_experience": rejected_experience,
        "max_age_hours": config.max_age_hours,
        "min_experience_years": config.min_experience_years,
        "strict_experience_filter": config.strict_experience_filter,
        "strict_freshness_filter": config.strict_freshness_filter,
    }
    return kept, stats
