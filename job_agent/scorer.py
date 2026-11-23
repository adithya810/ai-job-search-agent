"""Data Analyst skill extraction and match scoring engine."""

from __future__ import annotations

import re
from typing import Any

from .models import JobListing, SearchConfig

TITLE_HIGH_RELEVANCE = (
    "data analyst",
    "business data analyst",
    "analytics analyst",
    "bi analyst",
    "business intelligence analyst",
    "product data analyst",
    "reporting analyst",
    "sql analyst",
    "marketing data analyst",
    "operations data analyst",
)

TITLE_MODERATE_RELEVANCE = (
    "analyst",
    "analytics",
    "business intelligence",
    "power bi",
    "tableau",
    "mis",
    "insights",
)

EXP_PATTERN = re.compile(
    r"(\d+\s*(?:\+|to|-|–)\s*\d*\s*(?:years?|yrs?)|\d+\+\s*(?:years?|yrs?))",
    re.IGNORECASE,
)


def detect_work_mode(text: str) -> str:
    """Infer Remote / Hybrid / On-site from title, location, or description."""
    lower = text.lower()
    if re.search(r"\b(remote|work from home|wfh)\b", lower):
        return "Remote"
    if re.search(r"\bhybrid\b", lower):
        return "Hybrid"
    if re.search(r"\b(on-?site|in-office|work from office|wfo)\b", lower):
        return "On-site"
    return ""


def extract_experience(text: str) -> str:
    """Extract a short experience range snippet if not already populated."""
    match = EXP_PATTERN.search(text)
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()


def _matches_any(patterns: list[str], haystack: str) -> bool:
    for pattern in patterns:
        if re.search(pattern, haystack, re.IGNORECASE):
            return True
    return False


def score_job(job: JobListing, config: SearchConfig) -> JobListing:
    """Compute 0-100 Data Analyst skill-match score and annotate the job in place."""
    combined_parts = [
        job.title,
        job.company,
        job.location,
        " ".join(job.raw_skills),
        job.description,
    ]
    combined_text = "\n".join(p for p in combined_parts if p)
    title_lower = job.title.lower()

    matched_core: list[str] = []
    missing_core: list[str] = []
    matched_bonus: list[str] = []

    raw_points = 0.0
    max_skill_points = 0.0

    for skill_name, spec in config.core_skills.items():
        weight = float(spec.get("weight", 10))
        patterns: list[str] = list(spec.get("patterns", []))
        max_skill_points += weight
        if _matches_any(patterns, combined_text):
            matched_core.append(skill_name)
            raw_points += weight
        else:
            missing_core.append(skill_name)

    bonus_points = 0.0
    for skill_name, spec in config.bonus_skills.items():
        weight = float(spec.get("weight", 2))
        patterns = list(spec.get("patterns", []))
        if _matches_any(patterns, combined_text):
            matched_bonus.append(skill_name)
            bonus_points += weight

    # Title relevance gives up to 20 points so title-only listings (when full JD
    # isn't fetched yet) still rank sensibly without overshadowing rich skill matches.
    title_points = 0.0
    if any(k in title_lower for k in TITLE_HIGH_RELEVANCE):
        title_points = 20.0
    elif any(k in title_lower for k in TITLE_MODERATE_RELEVANCE):
        title_points = 12.0

    # Combine: up to 68 pts from core skills, up to 12 pts from bonus skills, up to 20 pts from title.
    core_ratio = (raw_points / max_skill_points) if max_skill_points > 0 else 0.0
    core_component = core_ratio * 68.0
    bonus_component = min(12.0, bonus_points)

    # If description was not fetched (short text) and no skills were extracted from tags,
    # keep score honest and reflective of title + available signals.
    total_score = int(round(min(100.0, title_points + core_component + bonus_component)))

    if not job.work_mode:
        job.work_mode = detect_work_mode(f"{job.title} {job.location} {job.description[:800]}")
    if not job.experience and job.description:
        job.experience = extract_experience(job.description)

    job.match_score = total_score
    job.matched_core_skills = matched_core
    job.missing_core_skills = missing_core
    job.matched_bonus_skills = matched_bonus
    return job


def score_jobs(jobs: list[JobListing], config: SearchConfig) -> list[JobListing]:
    """Score all jobs and sort by match_score descending, then source and title."""
    for job in jobs:
        score_job(job, config)
    jobs.sort(key=lambda j: (-j.match_score, not j.is_new, j.source, j.title.lower()))
    return jobs


def summarize_skills(jobs: list[JobListing]) -> dict[str, Any]:
    """Aggregate skill demand counts across all matched jobs."""
    core_counts: dict[str, int] = {}
    bonus_counts: dict[str, int] = {}
    for job in jobs:
        for s in job.matched_core_skills:
            core_counts[s] = core_counts.get(s, 0) + 1
        for s in job.matched_bonus_skills:
            bonus_counts[s] = bonus_counts.get(s, 0) + 1
    return {
        "core": dict(sorted(core_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
        "bonus": dict(sorted(bonus_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
    }
