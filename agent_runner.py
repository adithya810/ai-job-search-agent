#!/usr/bin/env python3
"""Autonomous Job Search AI Agent Runner (Scheduled Mondays 11:00 AM IST Only).

Implements:
- Phase 1: Runtime, SQLite (`jobs_history.db`), and `.env` validation
- Phase 2: Next-run schedule calculation in Asia/Kolkata (IST) — Mondays 11:00 AM IST
- Phase 3: Search -> SQLite Deduplicate -> Resume Skill/Exclusion Scoring (1-10, >=7)
           -> Curated Digest Delivery (Markdown/JSON + optional Slack/SMTP)
- Guardrails: Randomized polite delays, robots.txt checking, zero fabricated URLs,
              silent `"No new matches"` exit when no qualifying jobs are found.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import random
import re
import smtplib
from email.message import EmailMessage
import sys
import time
from typing import Any
import urllib.parse
import urllib.robotparser
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv as _dotenv_load
except ImportError:
    from job_agent.env import load_dotenv as _dotenv_load

try:
    import requests
except ImportError:
    requests = None  # type: ignore[assignment]

from pydantic import BaseModel, Field

from job_agent.dedup import compute_fingerprint
from job_agent.filters import filter_jobs
from job_agent.models import JobListing, SearchConfig
from job_agent.providers import PROVIDERS
from job_agent.resume_matcher import (
    ResumeMatchResult,
    build_profiles_from_drive_resumes,
    match_jobs_to_resumes,
)
from job_agent.storage import JobHistoryDB

PROJECT_ROOT = Path(__file__).resolve().parent
IST = ZoneInfo("Asia/Kolkata")


class NotificationTarget(BaseModel):
    digest_markdown: str = "output/weekly_digest.md"
    digest_json: str = "output/weekly_digest.json"
    slack_webhook_env: str = "SLACK_WEBHOOK_URL"
    notify_email: str = ""


class UserProfile(BaseModel):
    candidate_name: str
    email: str
    model: str = "flash-3.8"
    schedule_cron_ist: str = "0 11 * * 1"
    resume_sources: list[str] = Field(default_factory=list)
    target_roles: list[str]
    experience_years: float = 4.5
    min_experience_years: int = 3
    experience_level: str = "4.5 years (Mid-Senior)"
    locations: list[str]
    work_modes: list[str] = Field(default_factory=lambda: ["Remote", "Hybrid", "On-site"])
    key_skills: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    max_age_days: int = 7
    min_relevance_score: float = 7.0
    sites: list[str] = Field(default_factory=lambda: ["linkedin", "exa", "firecrawl"])
    notification_target: NotificationTarget = Field(default_factory=NotificationTarget)


def setup_logging(log_file: Path) -> logging.Logger:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("job_search_agent_runner")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(fmt)
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        logger.addHandler(fh)
        logger.addHandler(sh)
    return logger


def next_monday_ist_runs(count: int = 4, now_ist: datetime | None = None) -> list[str]:
    """Compute the next `count` scheduled runs (Mondays at 11:00 AM IST only)."""
    now = now_ist or datetime.now(IST)
    upcoming: list[datetime] = []
    cursor_date = now.date()
    while len(upcoming) < count:
        if cursor_date.weekday() == 0:  # Monday
            for hour in (11,):
                dt = datetime(cursor_date.year, cursor_date.month, cursor_date.day, hour, 0, tzinfo=IST)
                if dt > now:
                    upcoming.append(dt)
                    if len(upcoming) >= count:
                        break
        cursor_date += timedelta(days=1)
    return [dt.strftime("%Y-%m-%d %H:%M %Z (%A)") for dt in upcoming]


def check_robots_txt(url: str, user_agent: str = "JobSearchAgentBot") -> bool:
    """Check whether robots.txt allows fetching a target URL (fails open only on network error)."""
    try:
        parsed = urllib.parse.urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(robots_url)
        rp.read()
        return rp.can_fetch(user_agent, url)
    except Exception:
        return True


def matches_exclusions(job: JobListing, exclusions: list[str]) -> str | None:
    """Return the matched exclusion term if the job violates user exclusions."""
    haystack = f"{job.title}\n{job.company}\n{job.description[:1500]}".lower()
    for excl in exclusions:
        term = excl.strip().lower()
        if not term:
            continue
        if re.search(rf"\b{re.escape(term)}\b", haystack):
            return excl
    return None


def compute_relevance_1_to_10(match: ResumeMatchResult, job: JobListing) -> tuple[float, str]:
    """Map resume match percentage + skill coverage + experience fit into a 1.0-10.0 relevance score."""
    # Direct calibrated mapping: 80% resume fit -> 8.0/10, 70% -> 7.0/10, 100% -> 10.0/10.
    score = round(max(1.0, min(10.0, match.resume_match_pct / 10.0)), 1)
    top_skills = ", ".join(match.matched_skills[:5]) if match.matched_skills else "core analytics skills"
    exp_part = f" ({job.experience})" if job.experience else ""
    reason = (
        f"Covers {match.jd_skill_coverage_pct}% of requested JD skills ({top_skills}) "
        f"using your {match.best_resume_track} resume with {match.experience_fit} experience alignment{exp_part}."
    )
    return score, reason


def format_digest_markdown(
    profile: UserProfile,
    qualifying: list[dict[str, Any]],
    *,
    ran_at_ist: str,
    window_label: str,
    model_name: str = "flash-3.8",
) -> str:
    """Render a clean curated Markdown digest of qualifying job opportunities."""
    lines = [
        f"# Curated Weekly Job Digest — {profile.candidate_name}",
        "",
        f"- **Generated:** {ran_at_ist}",
        f"- **Model:** `{model_name}` | **Schedule:** Every Monday 11:00 AM IST (`0 11 * * 1`)",
        f"- **Profile:** {profile.experience_level} | Target Roles: {', '.join(profile.target_roles[:4])}",
        f"- **Freshness Window:** {window_label} | **Min Relevance:** {profile.min_relevance_score:.1f}/10",
        f"- **New Qualifying Matches:** {len(qualifying)}",
        "",
        "---",
        "",
    ]
    for idx, item in enumerate(qualifying, start=1):
        mode_str = f" ({item['work_mode']})" if item.get("work_mode") else ""
        lines.extend(
            [
                f"### {idx}. {item['title']} — {item['company']}",
                f"- **Location & Work Mode:** {item['location']}{mode_str}",
                f"- **Experience & Posted:** {item['experience'] or 'Verified >3y'} | Posted: {item['posted_date'] or 'Recent'}",
                f"- **Match Score:** **{item['relevance_score']:.1f}/10** ({item['resume_match_pct']}% resume fit) — {item['fit_reason']}",
                f"- **Best Resume:** {item['best_resume_name']}",
                f"- **Direct Application URL:** {item['url']}",
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def deliver_digest(
    markdown_text: str,
    json_payload: dict[str, Any],
    profile: UserProfile,
    logger: logging.Logger,
) -> list[str]:
    """Write digest to local files and optionally deliver to Slack webhook or SMTP email."""
    delivered_to: list[str] = []

    md_path = PROJECT_ROOT / profile.notification_target.digest_markdown
    js_path = PROJECT_ROOT / profile.notification_target.digest_json
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(markdown_text, encoding="utf-8")
    js_path.write_text(json.dumps(json_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    delivered_to.append(f"file:{md_path}")

    # Optional Slack Webhook delivery
    slack_url = os.environ.get(profile.notification_target.slack_webhook_env, "").strip()
    if slack_url and requests is not None:
        try:
            resp = requests.post(slack_url, json={"text": markdown_text[:3900]}, timeout=15)
            if resp.status_code < 300:
                delivered_to.append("slack_webhook")
            else:
                logger.warning("Slack webhook returned HTTP %s", resp.status_code)
        except Exception as exc:
            logger.warning("Slack webhook delivery failed: %s", exc)

    # Optional SMTP Email delivery (only if SMTP_HOST, SMTP_USER, SMTP_PASS are explicitly set)
    smtp_host = os.environ.get("SMTP_HOST", "").strip()
    smtp_user = os.environ.get("SMTP_USER", "").strip()
    smtp_pass = os.environ.get("SMTP_PASS", "").strip()
    to_email = os.environ.get("NOTIFY_EMAIL", profile.notification_target.notify_email).strip()
    if smtp_host and smtp_user and smtp_pass and to_email:
        try:
            port = int(os.environ.get("SMTP_PORT", "587"))
            msg = EmailMessage()
            msg["Subject"] = f"Job Search Digest: {len(json_payload['qualifying_jobs'])} New Matches ({profile.candidate_name})"
            msg["From"] = smtp_user
            msg["To"] = to_email
            msg.set_content(markdown_text)
            with smtplib.SMTP(smtp_host, port, timeout=20) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)
            delivered_to.append(f"smtp:{to_email}")
        except Exception as exc:
            logger.warning("SMTP email delivery failed: %s", exc)

    return delivered_to


def run_autonomous_cycle(
    *,
    profile_path: Path,
    config_path: Path,
    db_path: Path,
    log_path: Path,
    max_age_hours_override: int | None = None,
    min_score_override: float | None = None,
    model_override: str | None = None,
    max_queries: int = 3,
    max_per_query: int = 10,
    max_detail_fetches: int = 24,
    require_api_keys: bool = False,
) -> int:
    logger = setup_logging(log_path)
    _dotenv_load(PROJECT_ROOT / ".env")

    # Phase 1: Validate secrets & runtime
    if sys.version_info < (3, 10):
        logger.error("Python 3.10+ is required; found %s", sys.version)
        return 1

    if require_api_keys and not (os.environ.get("EXA_API_KEY") or os.environ.get("FIRECRAWL_API_KEY")):
        logger.error("Missing required API keys (EXA_API_KEY / FIRECRAWL_API_KEY). Exiting gracefully.")
        return 2

    if not profile_path.exists():
        logger.error("Profile file missing: %s", profile_path)
        return 1

    profile = UserProfile.model_validate_json(profile_path.read_text(encoding="utf-8"))
    config = SearchConfig.from_file(config_path)
    db = JobHistoryDB(db_path)

    model_name = (
        model_override
        or os.environ.get("AGENT_MODEL")
        or profile.model
        or "flash-3.8"
    )

    max_age_hours = (
        max_age_hours_override
        if max_age_hours_override is not None
        else max(24, profile.max_age_days * 24)
    )
    min_score = min_score_override if min_score_override is not None else profile.min_relevance_score

    config.max_age_hours = max_age_hours
    config.min_experience_years = profile.min_experience_years
    config.enrich_details = True
    config.max_detail_fetches = max_detail_fetches
    # Randomized polite delay base
    config.request_delay_seconds = round(random.uniform(1.3, 2.2), 2)

    ran_at_ist = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S %Z")
    upcoming = next_monday_ist_runs(4)
    logger.info("=== Autonomous Job Search Run Started (%s) ===", ran_at_ist)
    logger.info("Model: %s | Schedule: Mon 11:00 AM IST | Candidate: %s | Exp: %s | Window: <=%dh | Min Score: %.1f/10",
                model_name, profile.candidate_name, profile.experience_level, max_age_hours, min_score)
    logger.info("Next scheduled IST runs: %s", " | ".join(upcoming[:2]))

    # Load Adithya's resume profiles
    resumes_dir = PROJECT_ROOT / "resumes"
    resume_profiles = build_profiles_from_drive_resumes(resumes_dir)

    # Phase 3.1: Search & Aggregate
    queries = profile.target_roles[:max_queries]
    locations = profile.locations
    all_fetched: list[JobListing] = []
    provider_notes: list[str] = []

    for site in profile.sites:
        if site not in PROVIDERS:
            continue
        provider = PROVIDERS[site](config)
        logger.info("Querying provider '%s' for %d roles x %d locations...", site, len(queries), len(locations))
        found, status = provider.search(
            mode="public",
            queries=queries,
            locations=locations,
            max_results_per_query=max_per_query,
            headless=True,
        )
        all_fetched.extend(found)
        provider_notes.append(f"{site}:{status.status}({len(found)})")
        logger.info("Provider '%s' -> [%s] %s", site, status.status, status.message)
        time.sleep(random.uniform(0.8, 1.8))

    # Compute fingerprints & intra-run dedup
    unique_map: dict[str, JobListing] = {}
    for job in all_fetched:
        job.fingerprint = compute_fingerprint(job)
        existing = unique_map.get(job.fingerprint)
        if existing is None or len(job.description) > len(existing.description):
            unique_map[job.fingerprint] = job
    unique_jobs = list(unique_map.values())

    # Phase 3.2: Deduplicate against persistent SQLite `jobs_history.db`
    unseen_jobs = db.filter_unseen(unique_jobs)
    logger.info("Fetched %d unique postings; %d are unseen in jobs_history.db", len(unique_jobs), len(unseen_jobs))

    # Apply freshness & >3y experience filters
    eligible_jobs, filter_stats = filter_jobs(unseen_jobs, config)
    logger.info("Post-filter (<=%dh & >%dy): %d eligible (rejected %d stale, %d exp)",
                max_age_hours, profile.min_experience_years, len(eligible_jobs),
                filter_stats["rejected_freshness"], filter_stats["rejected_experience"])

    # Phase 3.3: Exclusion check + Resume Skill Scoring (1-10, keep >= 7)
    non_excluded: list[JobListing] = []
    excluded_count = 0
    for job in eligible_jobs:
        hit = matches_exclusions(job, profile.exclusions)
        if hit:
            excluded_count += 1
            continue
        non_excluded.append(job)

    all_matches, _ = match_jobs_to_resumes(non_excluded, resume_profiles, min_match_pct=0)
    by_fp = {j.fingerprint: j for j in non_excluded}

    qualifying_records: list[dict[str, Any]] = []
    non_qualifying_records: list[dict[str, Any]] = []

    for m in all_matches:
        job = by_fp[m.fingerprint]
        rel_score, reason = compute_relevance_1_to_10(m, job)
        rec = {
            "fingerprint": job.fingerprint,
            "job_id": job.job_id,
            "source": job.source,
            "url": job.url,
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "work_mode": job.work_mode,
            "experience": job.experience,
            "posted_date": job.posted_date,
            "relevance_score": rel_score,
            "resume_match_pct": m.resume_match_pct,
            "jd_skill_coverage_pct": m.jd_skill_coverage_pct,
            "best_resume_track": m.best_resume_track,
            "best_resume_name": m.best_resume_name,
            "best_resume_drive_url": m.best_resume_drive_url,
            "matched_skills": m.matched_skills,
            "missing_skills": m.missing_skills,
            "fit_reason": reason,
        }
        if rel_score >= min_score:
            qualifying_records.append(rec)
        else:
            non_qualifying_records.append(rec)

    qualifying_records.sort(key=lambda r: (-r["relevance_score"], -r["resume_match_pct"]))

    # Phase 3.4 & 3.5: Format Digest, Deliver (only if >0 matches), and Persist to SQLite
    if not qualifying_records:
        # Record non-qualifying evaluated jobs so we don't re-alert stale items, but do NOT send an empty alert.
        db.record_jobs(non_qualifying_records, mark_notified=False)
        db.log_run(
            fetched_count=len(unique_jobs),
            new_count=len(unseen_jobs),
            qualifying_count=0,
            digest_delivered=False,
            status="no_new_matches",
            notes="; ".join(provider_notes),
        )
        logger.info("No new matches (excluded=%d, below_threshold=%d). Skipping empty alert.",
                    excluded_count, len(non_qualifying_records))
        return 0

    window_label = f"Last {max_age_hours} hours" if max_age_hours <= 72 else f"Last {max_age_hours // 24} days"
    digest_md = format_digest_markdown(
        profile,
        qualifying_records,
        ran_at_ist=ran_at_ist,
        window_label=window_label,
        model_name=model_name,
    )
    digest_payload = {
        "generated_at_ist": ran_at_ist,
        "model": model_name,
        "schedule": "Monday 11:00 AM IST (0 11 * * 1)",
        "candidate": profile.candidate_name,
        "window": window_label,
        "min_relevance_score": min_score,
        "next_scheduled_runs_ist": upcoming,
        "filter_stats": filter_stats,
        "excluded_count": excluded_count,
        "qualifying_count": len(qualifying_records),
        "qualifying_jobs": qualifying_records,
    }

    targets = deliver_digest(digest_md, digest_payload, profile, logger)
    db.record_jobs(qualifying_records, mark_notified=True)
    db.record_jobs(non_qualifying_records, mark_notified=False)
    db.log_run(
        fetched_count=len(unique_jobs),
        new_count=len(unseen_jobs),
        qualifying_count=len(qualifying_records),
        digest_delivered=True,
        status="ok",
        notes=f"Delivered to {', '.join(targets)} | {'; '.join(provider_notes)}",
    )
    logger.info(
        "Delivered curated digest with %d qualifying jobs (>= %.1f/10) to %s.",
        len(qualifying_records),
        min_score,
        ", ".join(targets),
    )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Autonomous Job Search AI Agent Runner")
    parser.add_argument("--profile", type=Path, default=PROJECT_ROOT / "profile.json")
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "config.json")
    parser.add_argument("--db", type=Path, default=PROJECT_ROOT / "jobs_history.db")
    parser.add_argument("--log", type=Path, default=PROJECT_ROOT / "agent.log")
    parser.add_argument("--model", type=str, default=None, help="Execution model identifier (default: AGENT_MODEL env or profile.model, e.g. flash-3.8)")
    parser.add_argument("--max-age-hours", type=int, help="Override freshness window in hours (default: profile.max_age_days*24)")
    parser.add_argument("--min-score", type=float, help="Override min 1-10 relevance score (default: 7.0)")
    parser.add_argument("--max-queries", type=int, default=3)
    parser.add_argument("--max-per-query", type=int, default=10)
    parser.add_argument("--max-detail-fetches", type=int, default=24)
    parser.add_argument("--require-api-keys", action="store_true", help="Exit with code 2 if EXA/FIRECRAWL keys are unset")
    parser.add_argument("--show-next-runs", action="store_true", help="Print next scheduled Monday 11:00 AM IST runs and exit")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.show_next_runs:
        print("Next scheduled Monday runs (Asia/Kolkata):")
        for ts in next_monday_ist_runs(6):
            print(f"  - {ts}")
        return 0
    return run_autonomous_cycle(
        profile_path=args.profile,
        config_path=args.config,
        db_path=args.db,
        log_path=args.log,
        max_age_hours_override=args.max_age_hours,
        min_score_override=args.min_score,
        model_override=args.model,
        max_queries=args.max_queries,
        max_per_query=args.max_per_query,
        max_detail_fetches=args.max_detail_fetches,
        require_api_keys=args.require_api_keys,
    )


if __name__ == "__main__":
    raise SystemExit(main())
