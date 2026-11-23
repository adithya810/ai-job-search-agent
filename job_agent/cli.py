"""Command-line interface for the Data Analyst Job Search Agent."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .apply_assistant import export_apply_queue, run_assisted_apply
from .browser import has_saved_profile, interactive_site_login, playwright_available
from .connectors.exa import ExaConnector
from .connectors.firecrawl import FirecrawlConnector
from .connectors.mcp_client import create_mcp_client
from .dedup import deduplicate_jobs
from .env import load_dotenv
from .exporters import (
    build_report_payload,
    export_csv,
    export_dashboard_html,
    export_json,
)
from .filters import filter_jobs
from .mcp_server import JobSearchMCPServer, scrape_and_score_url
from .models import JobListing, SearchConfig, SiteRunStatus
from .providers import PROVIDERS
from .resume_matcher import (
    build_profiles_from_drive_resumes,
    match_jobs_to_resumes,
    save_resume_profiles,
)
from .scorer import score_jobs, summarize_skills

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"
LOGIN_SITES = ("linkedin", "naukri", "ziprecruiter")


def _parse_csv_arg(value: str | None) -> list[str] | None:
    if not value:
        return None
    items = [part.strip() for part in value.split(",") if part.strip()]
    return items or None


def cmd_login(args: argparse.Namespace, config: SearchConfig) -> int:
    sites = list(LOGIN_SITES) if args.site == "all" else [args.site]
    email_hint = args.email if args.email is not None else config.email_hint
    for site in sites:
        provider_cls = PROVIDERS[site]
        interactive_site_login(
            config.profile_dir,
            site_name=site,
            login_url=provider_cls.login_url,
            email_hint=email_hint,
            email_selectors=provider_cls.email_selectors,
        )
    return 0


def cmd_status(args: argparse.Namespace, config: SearchConfig) -> int:
    load_dotenv()
    pw_ok, pw_msg = playwright_available()
    profile_exists = has_saved_profile(config.profile_dir)
    exa_ok = ExaConnector().is_configured
    fc_ok = FirecrawlConnector().is_configured
    last_json = config.output_dir / "jobs.json"

    print("=== Data Analyst Job Search Agent Status ===")
    print(f"Config email hint : {config.email_hint or '(none)'}")
    print(f"Sites configured  : {', '.join(config.sites)}")
    print(f"Queries           : {', '.join(config.queries)}")
    print(f"Locations         : {', '.join(config.locations)}")
    print(
        f"Filters           : experience > {config.min_experience_years} yrs "
        f"(strict={config.strict_experience_filter}) | "
        f"freshness <= {config.max_age_hours}h (strict={config.strict_freshness_filter})"
    )
    print(f"Playwright        : {'Available' if pw_ok else 'Missing'} ({pw_msg})")
    print(
        f"Browser profile   : {config.profile_dir} "
        f"({'Saved session found' if profile_exists else 'Not initialized yet'})"
    )
    print(f"Exa connector     : {'Configured (EXA_API_KEY set)' if exa_ok else 'Not configured (set EXA_API_KEY in .env)'}")
    print(f"Firecrawl conn.   : {'Configured (FIRECRAWL_API_KEY/URL set)' if fc_ok else 'Not configured (set FIRECRAWL_API_KEY in .env)'}")
    mcp_summary = [
        f"{name}({'enabled' if cfg.get('enabled') else 'disabled'})"
        for name, cfg in config.mcp_servers.items()
    ]
    print(f"External MCPs     : {', '.join(mcp_summary) if mcp_summary else '(none)'}")
    print("Built-in MCP srv  : python3 -m job_agent mcp-serve")
    if last_json.exists():
        data = json.loads(last_json.read_text(encoding="utf-8"))
        summary = data.get("summary", {})
        print(
            f"Last run          : {data.get('generated_at')} | "
            f"{summary.get('total_jobs', 0)} jobs "
            f"(avg score {summary.get('avg_match_score', 0)})"
        )
    else:
        print("Last run          : No output yet (run `python3 -m job_agent search`).")
    return 0


def cmd_search(args: argparse.Namespace, config: SearchConfig) -> int:
    load_dotenv()
    sites = _parse_csv_arg(args.sites) or config.sites
    queries = _parse_csv_arg(args.queries) or config.queries
    locations = _parse_csv_arg(args.locations) or config.locations
    max_per_query = args.max_per_query or config.max_results_per_query
    if args.no_enrich:
        config.enrich_details = False
    elif args.enrich_details:
        config.enrich_details = True
    if args.max_detail_fetches is not None:
        config.max_detail_fetches = args.max_detail_fetches
    if args.min_exp is not None:
        config.min_experience_years = args.min_exp
    if args.max_age_hours is not None:
        config.max_age_hours = args.max_age_hours
    if args.include_unverified_exp:
        config.strict_experience_filter = False
    if args.include_unverified_freshness:
        config.strict_freshness_filter = False

    unknown = [s for s in sites if s not in PROVIDERS]
    if unknown:
        print(
            f"Error: Unknown site(s): {', '.join(unknown)}. Valid: {', '.join(PROVIDERS)}",
            file=sys.stderr,
        )
        return 2

    all_jobs: list[JobListing] = []
    statuses: list[SiteRunStatus] = []

    print(f"Starting Data Analyst job search (mode={args.mode})...")
    print(f"  Sites      : {', '.join(sites)}")
    print(f"  Queries    : {', '.join(queries)}")
    print(f"  Locations  : {', '.join(locations)}")
    print(
        f"  Filters    : experience >= {config.min_experience_years}+ yrs "
        f"(strict={config.strict_experience_filter}) | "
        f"freshness <= {config.max_age_hours}h (strict={config.strict_freshness_filter})\n"
    )

    for site in sites:
        provider = PROVIDERS[site](config)
        print(f"-> Querying {site} ({args.mode} mode)...")
        site_jobs, status = provider.search(
            mode=args.mode,
            queries=queries,
            locations=locations,
            max_results_per_query=max_per_query,
            headless=not args.headed,
        )
        all_jobs.extend(site_jobs)
        statuses.append(status)
        print(f"   [{status.status}] {status.message}")

    history_path = config.output_dir / "seen_jobs.json"
    deduped = deduplicate_jobs(all_jobs, seen_history_path=history_path)
    filtered, filter_stats = filter_jobs(deduped, config)
    scored = score_jobs(filtered, config)
    skill_summary = summarize_skills(scored)

    payload = build_report_payload(
        scored,
        statuses,
        skill_summary,
        mode=args.mode,
        locations=locations,
        queries=queries,
        filter_stats=filter_stats,
    )

    csv_path = export_csv(scored, config.output_dir / "jobs.csv")
    json_path = export_json(payload, config.output_dir / "jobs.json")
    html_path = export_dashboard_html(payload, config.output_dir / "dashboard.html")

    print("\n=== Search Complete ===")
    print(
        f"Filter summary    : {filter_stats['input_count']} unique -> {filter_stats['kept_count']} kept "
        f"(rejected {filter_stats['rejected_freshness']} stale >{config.max_age_hours}h, "
        f"{filter_stats['rejected_experience']} below/unverified >{config.min_experience_years} yrs exp)"
    )
    print(f"Unique jobs saved : {len(scored)} ({payload['summary']['new_jobs']} new)")
    print(f"Avg match score   : {payload['summary']['avg_match_score']} / 100")
    print(f"CSV report        : {csv_path}")
    print(f"JSON report       : {json_path}")
    print(f"HTML dashboard    : {html_path}")
    if scored:
        print("\nTop 5 matches:")
        for idx, job in enumerate(scored[:5], start=1):
            skills = ", ".join(job.matched_core_skills) or "title match"
            exp_txt = f" | {job.experience}" if job.experience else ""
            date_txt = f" | {job.posted_date}" if job.posted_date else ""
            print(
                f"  {idx}. [{job.match_score:>3}] {job.title} @ {job.company} "
                f"({job.location}{exp_txt}{date_txt}) — {skills}"
            )
    return 0


def cmd_scrape(args: argparse.Namespace, config: SearchConfig) -> int:
    result = scrape_and_score_url(
        args.url,
        config,
        location_hint=args.location,
        engine=args.engine,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def cmd_mcp_serve(args: argparse.Namespace, config: SearchConfig) -> int:
    load_dotenv()
    server = JobSearchMCPServer(config)
    return server.serve_stdio()


def cmd_mcp_list_tools(args: argparse.Namespace, config: SearchConfig) -> int:
    load_dotenv()
    if args.server == "self":
        server_cfg = {
            "transport": "stdio",
            "command": sys.executable,
            "args": ["-m", "job_agent", "--config", str(args.config), "mcp-serve"],
        }
    else:
        if args.server not in config.mcp_servers:
            print(
                f"Error: Unknown MCP server '{args.server}'. Configured: {', '.join(config.mcp_servers) or 'none'} (or 'self').",
                file=sys.stderr,
            )
            return 2
        server_cfg = config.mcp_servers[args.server]

    with create_mcp_client(server_cfg) as client:
        tools = client.list_tools()
    print(json.dumps({"server": args.server, "tools": tools}, indent=2))
    return 0


def cmd_match_resumes(args: argparse.Namespace, config: SearchConfig) -> int:
    jobs_path = Path(args.input) if args.input else (config.output_dir / "jobs.json")
    if not jobs_path.exists():
        print(f"Error: {jobs_path} not found. Run `python3 -m job_agent search` first.", file=sys.stderr)
        return 1

    resumes_dir = Path(args.resumes_dir) if args.resumes_dir else (Path(__file__).resolve().parent.parent / "resumes")
    profiles = build_profiles_from_drive_resumes(resumes_dir)
    save_resume_profiles(profiles, config.output_dir / "resume_profiles.json")

    raw_payload = json.loads(jobs_path.read_text(encoding="utf-8"))
    jobs = [JobListing(**item) for item in raw_payload.get("jobs", [])]

    all_matches, qualified = match_jobs_to_resumes(jobs, profiles, min_match_pct=args.min_match)
    q_json, q_csv = export_apply_queue(
        qualified,
        all_matches,
        profiles,
        config.output_dir,
        min_match_pct=args.min_match,
    )

    print(f"=== Resume Matching Complete (threshold >= {args.min_match}%) ===")
    print(f"Resumes loaded    : {len(profiles)} tracks ({len(profiles[1].skills)} unique skills extracted)")
    print(f"Jobs evaluated    : {len(all_matches)}")
    print(f"Qualified (>={args.min_match}%): {len(qualified)}")
    print(f"Apply queue JSON  : {q_json}")
    print(f"Apply queue CSV   : {q_csv}")
    if qualified:
        print("\nReady-to-Apply Matches (>= 80%):")
        for idx, r in enumerate(qualified, start=1):
            print(
                f"  {idx}. [{r.resume_match_pct:>3}% | JD cov {r.jd_skill_coverage_pct:>3}%] "
                f"{r.title} @ {r.company} ({r.location} | {r.experience} | {r.posted_date})"
            )
            print(f"      Best Resume : {r.best_resume_track} ({r.best_resume_name})")
            print(f"      Matched     : {', '.join(r.matched_skills)}")
            if r.missing_skills:
                print(f"      Skill Gaps  : {', '.join(r.missing_skills)}")
    return 0


def cmd_apply(args: argparse.Namespace, config: SearchConfig) -> int:
    queue_path = Path(args.queue) if args.queue else (config.output_dir / "apply_queue.json")
    return run_assisted_apply(queue_path, config.profile_dir, limit=args.limit)


def cmd_build_dashboard(args: argparse.Namespace, config: SearchConfig) -> int:
    json_path = Path(args.input) if args.input else (config.output_dir / "jobs.json")
    if not json_path.exists():
        print(f"Error: {json_path} does not exist. Run `search` first.", file=sys.stderr)
        return 1
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    out_path = Path(args.output) if args.output else (config.output_dir / "dashboard.html")
    export_dashboard_html(payload, out_path)
    print(f"Dashboard generated: {out_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m job_agent",
        description=(
            "Hybrid Data Analyst / Gen AI / ML Job Search Agent for LinkedIn, Naukri, ZipRecruiter, "
            "Exa, Firecrawl, and MCP web-search servers."
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="Path to config.json (default: ./config.json)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_search = sub.add_parser("search", help="Search jobs, filter (>3y, <=48h), score skills, and export reports.")
    p_search.add_argument(
        "--mode",
        choices=("public", "browser", "hybrid"),
        default="public",
        help="public (no login + APIs), browser (persistent Playwright profile), or hybrid (public + browser fallback).",
    )
    p_search.add_argument(
        "--sites",
        help="Comma-separated providers: linkedin,naukri,ziprecruiter,exa,firecrawl,mcp",
    )
    p_search.add_argument("--queries", help="Comma-separated job queries")
    p_search.add_argument("--locations", help="Comma-separated locations")
    p_search.add_argument("--max-per-query", type=int, help="Max jobs per query+location")
    p_search.add_argument("--max-detail-fetches", type=int, help="Max public LinkedIn detail pages to fetch")
    p_search.add_argument("--min-exp", type=int, help="Minimum required experience years (default: 3; 0 to disable)")
    p_search.add_argument("--max-age-hours", type=int, help="Maximum job age in hours (default: 48; 0 to disable)")
    p_search.add_argument(
        "--include-unverified-exp",
        action="store_true",
        help="Keep jobs that do not explicitly state years of experience",
    )
    p_search.add_argument(
        "--include-unverified-freshness",
        action="store_true",
        help="Keep jobs whose posted timestamp is missing",
    )
    p_search.add_argument("--enrich-details", action="store_true", help="Fetch full job descriptions for scoring")
    p_search.add_argument("--no-enrich", action="store_true", help="Skip fetching detail descriptions (faster)")
    p_search.add_argument("--headed", action="store_true", help="Show visible Chromium window in browser/hybrid mode")

    p_login = sub.add_parser(
        "login",
        help="Open a visible Chromium window to sign in manually once and save your local session profile.",
    )
    p_login.add_argument(
        "--site",
        choices=("linkedin", "naukri", "ziprecruiter", "all"),
        default="all",
        help="Which site(s) to open for manual login",
    )
    p_login.add_argument("--email", help="Optional email hint to pre-fill (passwords are never stored)")

    p_match = sub.add_parser(
        "match-resumes",
        help="Match saved jobs against your Google Drive resumes (Gen AI, ML, Data Analyst) and build >=80% Apply Queue.",
    )
    p_match.add_argument("--min-match", type=int, default=80, help="Minimum resume match percentage (default: 80)")
    p_match.add_argument("--input", help="Path to jobs.json")
    p_match.add_argument("--resumes-dir", help="Path to downloaded resumes folder")

    p_apply = sub.add_parser(
        "apply",
        help="Open >=80% matched jobs one-by-one in your visible local Chromium session for human-reviewed submission.",
    )
    p_apply.add_argument("--queue", help="Path to apply_queue.json")
    p_apply.add_argument("--limit", type=int, default=10, help="Max jobs to open in one session")

    p_scrape = sub.add_parser(
        "scrape",
        help="Scrape and score a single job posting webpage via Firecrawl, Exa, or direct HTTP.",
    )
    p_scrape.add_argument("url", help="Job posting URL to scrape and score")
    p_scrape.add_argument("--engine", choices=("auto", "firecrawl", "exa", "http"), default="auto")
    p_scrape.add_argument("--location", default="India", help="Fallback location hint")

    sub.add_parser("mcp-serve", help="Run the built-in MCP JSON-RPC 2.0 stdio server.")

    p_mcp_ls = sub.add_parser("mcp-list-tools", help="Connect to an MCP server and list its tools.")
    p_mcp_ls.add_argument("--server", default="self", help="Server name from config.json `mcp_servers` or `self`")

    sub.add_parser("status", help="Show config, filters, Playwright/Exa/Firecrawl/MCP readiness, and last run.")

    p_dash = sub.add_parser("build-dashboard", help="Rebuild the offline HTML dashboard from jobs.json.")
    p_dash.add_argument("--input", help="Path to jobs.json")
    p_dash.add_argument("--output", help="Path to output dashboard.html")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = SearchConfig.from_file(args.config)

    if args.command == "search":
        return cmd_search(args, config)
    if args.command == "login":
        return cmd_login(args, config)
    if args.command == "match-resumes":
        return cmd_match_resumes(args, config)
    if args.command == "apply":
        return cmd_apply(args, config)
    if args.command == "scrape":
        return cmd_scrape(args, config)
    if args.command == "mcp-serve":
        return cmd_mcp_serve(args, config)
    if args.command == "mcp-list-tools":
        return cmd_mcp_list_tools(args, config)
    if args.command == "status":
        return cmd_status(args, config)
    if args.command == "build-dashboard":
        return cmd_build_dashboard(args, config)
    return 1
