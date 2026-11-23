"""MCP (Model Context Protocol) JSON-RPC 2.0 stdio server for the Data Analyst Job Search Agent.

Run via:
    python3 -m job_agent mcp-serve

Exposes job-search and webpage-scraping tools (LinkedIn, Naukri, ZipRecruiter, Exa, Firecrawl)
to any MCP client (Claude Desktop, Cursor, Windsurf, Antigravity, or custom agents).
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

from .connectors.exa import ExaConnector, parse_exa_results
from .connectors.firecrawl import FirecrawlConnector, parse_firecrawl_results
from .connectors.normalize import webpage_result_to_job
from .dedup import deduplicate_jobs
from .env import load_dotenv
from .exporters import build_report_payload, export_csv, export_dashboard_html, export_json
from .filters import filter_jobs
from .models import JobListing, SearchConfig, SiteRunStatus
from .providers import PROVIDERS
from .providers.base import fetch_url, strip_html
from .scorer import score_job, score_jobs, summarize_skills

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "job-search-agent", "version": "1.1.0"}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "search_jobs",
        "description": (
            "Search for Data Analyst jobs across LinkedIn, Naukri, ZipRecruiter, Exa, Firecrawl, "
            "and/or external MCP servers; filter by experience (>3 yrs) and freshness (<=48h), "
            "deduplicate, score SQL/Python/Excel/Power BI/Tableau fit, and export CSV/JSON/HTML."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "queries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Job title queries, e.g. ['Data Analyst', 'Senior Data Analyst']",
                },
                "locations": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Target locations, e.g. ['Bengaluru, Karnataka, India', 'Hyderabad, Telangana, India']",
                },
                "sites": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Providers to run: linkedin, naukri, ziprecruiter, exa, firecrawl, mcp",
                },
                "mode": {
                    "type": "string",
                    "enum": ["public", "browser", "hybrid"],
                    "default": "public",
                },
                "min_experience_years": {"type": "integer", "default": 3},
                "max_age_hours": {"type": "integer", "default": 48},
                "max_per_query": {"type": "integer", "default": 15},
                "enrich_details": {"type": "boolean", "default": True},
            },
        },
    },
    {
        "name": "search_web_exa",
        "description": (
            "Search job webpages across LinkedIn, Naukri, ZipRecruiter, and company career pages "
            "using the Exa neural search connector (with <=48h freshness & >3 yrs experience filters)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural-language job search query"},
                "location": {"type": "string", "default": "India"},
                "domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional includeDomains list (defaults to config web_search_domains)",
                },
                "num_results": {"type": "integer", "default": 10},
                "max_age_hours": {"type": "integer", "default": 48},
                "min_experience_years": {"type": "integer", "default": 3},
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_web_firecrawl",
        "description": (
            "Search job webpages and extract clean Markdown via the Firecrawl connector "
            "(with freshness & experience filtering), returning Data Analyst skill-scored listings."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Web search query (supports site: filters)"},
                "location": {"type": "string", "default": "India"},
                "limit": {"type": "integer", "default": 10},
                "scrape_markdown": {"type": "boolean", "default": True},
                "max_age_hours": {"type": "integer", "default": 48},
                "min_experience_years": {"type": "integer", "default": 3},
            },
            "required": ["query"],
        },
    },
    {
        "name": "scrape_job_webpage",
        "description": (
            "Fetch any job posting webpage URL using Firecrawl (or Exa / polite HTTP fallback), "
            "extract text, and compute a 0-100 Data Analyst skill-match score."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Full URL of the job posting webpage"},
                "location_hint": {"type": "string", "default": "India"},
                "engine": {
                    "type": "string",
                    "enum": ["auto", "firecrawl", "exa", "http"],
                    "default": "auto",
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "get_saved_jobs",
        "description": "Read and filter previously saved jobs from output/jobs.json by min_score, city, source, or skill.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "min_score": {"type": "integer", "default": 0},
                "city": {"type": "string", "description": "Case-insensitive city substring filter"},
                "source": {"type": "string", "description": "Source filter (linkedin, naukri, ziprecruiter, etc.)"},
                "skill": {"type": "string", "description": "Core skill filter (SQL, Python, Excel, Power BI, Tableau)"},
                "limit": {"type": "integer", "default": 20},
            },
        },
    },
]


def scrape_and_score_url(
    url: str,
    config: SearchConfig,
    *,
    location_hint: str = "India",
    engine: str = "auto",
) -> dict[str, Any]:
    """Scrape a single job webpage using Firecrawl, Exa `/contents`, or polite HTTP fallback."""
    load_dotenv()
    used_engine = engine
    title = ""
    content = ""

    fc = FirecrawlConnector()
    exa = ExaConnector()

    if engine == "firecrawl" or (engine == "auto" and fc.is_configured):
        data = fc.scrape(url)
        meta = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        title = str(meta.get("title") or data.get("title") or "")
        content = str(data.get("markdown") or data.get("content") or "")
        used_engine = "firecrawl"
    elif engine == "exa" or (engine == "auto" and exa.is_configured):
        rows = exa.get_contents([url])
        if rows:
            title = str(rows[0].get("title") or "")
            content = str(rows[0].get("text") or "")
        used_engine = "exa"
    else:
        status_code, html = fetch_url(url)
        if status_code >= 400:
            raise RuntimeError(
                f"Direct HTTP fetch returned HTTP {status_code}. "
                "Configure FIRECRAWL_API_KEY or EXA_API_KEY in `.env` for JS/protected pages."
            )
        import re

        m_title = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        title = strip_html(m_title.group(1)) if m_title else ""
        content = strip_html(html)
        used_engine = "http"

    job = webpage_result_to_job(
        url=url,
        raw_title=title,
        content_text=content,
        connector_name=used_engine,
        query_matched="direct-scrape",
        location_searched=location_hint,
    )
    score_job(job, config)
    return {"engine": used_engine, "job": job.to_dict()}


class JobSearchMCPServer:
    """Handles MCP JSON-RPC 2.0 requests for job search & webpage extraction."""

    def __init__(self, config: SearchConfig) -> None:
        self.config = config

    def handle_tool_call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "search_jobs":
            return self._tool_search_jobs(args)
        if name == "search_web_exa":
            return self._tool_search_exa(args)
        if name == "search_web_firecrawl":
            return self._tool_search_firecrawl(args)
        if name == "scrape_job_webpage":
            return scrape_and_score_url(
                url=str(args["url"]),
                config=self.config,
                location_hint=str(args.get("location_hint", "India")),
                engine=str(args.get("engine", "auto")),
            )
        if name == "get_saved_jobs":
            return self._tool_get_saved_jobs(args)
        raise ValueError(f"Unknown MCP tool: {name}")

    def _tool_search_jobs(self, args: dict[str, Any]) -> dict[str, Any]:
        sites = list(args.get("sites") or self.config.sites)
        queries = list(args.get("queries") or self.config.queries[:1])
        locations = list(args.get("locations") or self.config.locations)
        mode = str(args.get("mode") or "public")
        max_per_query = int(args.get("max_per_query") or self.config.max_results_per_query)
        self.config.enrich_details = bool(args.get("enrich_details", True))
        if "min_experience_years" in args:
            self.config.min_experience_years = int(args["min_experience_years"])
        if "max_age_hours" in args:
            self.config.max_age_hours = int(args["max_age_hours"])

        all_jobs: list[JobListing] = []
        statuses: list[SiteRunStatus] = []
        for site in sites:
            if site not in PROVIDERS:
                statuses.append(
                    SiteRunStatus(site=site, mode_used=mode, status="error", message=f"Unknown site: {site}")
                )
                continue
            provider = PROVIDERS[site](self.config)
            found, st = provider.search(
                mode=mode,
                queries=queries,
                locations=locations,
                max_results_per_query=max_per_query,
                headless=True,
            )
            all_jobs.extend(found)
            statuses.append(st)

        deduped = deduplicate_jobs(all_jobs, seen_history_path=self.config.output_dir / "seen_jobs.json")
        filtered, filter_stats = filter_jobs(deduped, self.config)
        scored = score_jobs(filtered, self.config)
        summary = summarize_skills(scored)
        payload = build_report_payload(
            scored,
            statuses,
            summary,
            mode=mode,
            locations=locations,
            queries=queries,
            filter_stats=filter_stats,
        )
        export_csv(scored, self.config.output_dir / "jobs.csv")
        export_json(payload, self.config.output_dir / "jobs.json")
        export_dashboard_html(payload, self.config.output_dir / "dashboard.html")
        return {
            "filters": filter_stats,
            "summary": payload["summary"],
            "site_statuses": payload["site_statuses"],
            "skill_demand": payload["skill_demand"],
            "top_jobs": payload["jobs"][:15],
            "output_dir": str(self.config.output_dir),
        }

    def _tool_search_exa(self, args: dict[str, Any]) -> dict[str, Any]:
        from datetime import datetime, timedelta, timezone

        connector = ExaConnector()
        query = str(args["query"])
        location = str(args.get("location", "India"))
        domains = args.get("domains") or self.config.web_search_domains
        num_results = int(args.get("num_results", 10))
        max_age = int(args.get("max_age_hours", self.config.max_age_hours))
        min_exp = int(args.get("min_experience_years", self.config.min_experience_years))
        start_pub = (
            (datetime.now(timezone.utc) - timedelta(hours=max_age)).strftime("%Y-%m-%dT%H:%M:%SZ")
            if max_age > 0
            else None
        )
        raw = connector.search(
            query,
            num_results=num_results,
            include_domains=domains,
            start_published_date=start_pub,
        )
        jobs = parse_exa_results(raw, query_matched=query, location_searched=location)
        self.config.max_age_hours = max_age
        self.config.min_experience_years = min_exp
        filtered, fstats = filter_jobs(jobs, self.config)
        scored = score_jobs(filtered, self.config)
        return {"count": len(scored), "filters": fstats, "jobs": [j.to_dict() for j in scored]}

    def _tool_search_firecrawl(self, args: dict[str, Any]) -> dict[str, Any]:
        connector = FirecrawlConnector()
        query = str(args["query"])
        location = str(args.get("location", "India"))
        limit = int(args.get("limit", 10))
        scrape_md = bool(args.get("scrape_markdown", True))
        max_age = int(args.get("max_age_hours", self.config.max_age_hours))
        min_exp = int(args.get("min_experience_years", self.config.min_experience_years))
        tbs = "qdr:d" if 0 < max_age <= 24 else ("qdr:w" if max_age > 24 else None)
        raw = connector.search(query, limit=limit, scrape_markdown=scrape_md, tbs=tbs)
        jobs = parse_firecrawl_results(raw, query_matched=query, location_searched=location)
        self.config.max_age_hours = max_age
        self.config.min_experience_years = min_exp
        filtered, fstats = filter_jobs(jobs, self.config)
        scored = score_jobs(filtered, self.config)
        return {"count": len(scored), "filters": fstats, "jobs": [j.to_dict() for j in scored]}

    def _tool_get_saved_jobs(self, args: dict[str, Any]) -> dict[str, Any]:
        json_path = self.config.output_dir / "jobs.json"
        if not json_path.exists():
            return {"count": 0, "jobs": [], "message": "No saved jobs.json yet. Run search_jobs first."}
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        min_score = int(args.get("min_score", 0))
        city = str(args.get("city") or "").strip().lower()
        source = str(args.get("source") or "").strip().lower()
        skill = str(args.get("skill") or "").strip().lower()
        limit = int(args.get("limit", 20))

        matched: list[dict[str, Any]] = []
        for job in payload.get("jobs", []):
            if int(job.get("match_score", 0)) < min_score:
                continue
            if city and city not in str(job.get("location", "")).lower():
                continue
            if source and str(job.get("source", "")).lower() != source:
                continue
            if skill and not any(
                s.lower() == skill for s in (job.get("matched_core_skills") or [])
            ):
                continue
            matched.append(job)

        return {
            "generated_at": payload.get("generated_at"),
            "total_matching": len(matched),
            "jobs": matched[:limit],
        }

    def handle_message(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        method = msg.get("method")
        req_id = msg.get("id")

        # Notifications have no `id` and expect no reply.
        if req_id is None:
            return None

        try:
            if method == "initialize":
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {"tools": {}},
                        "serverInfo": SERVER_INFO,
                    },
                }
            if method == "ping":
                return {"jsonrpc": "2.0", "id": req_id, "result": {}}
            if method == "tools/list":
                return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}
            if method == "tools/call":
                params = msg.get("params") or {}
                tool_name = str(params.get("name") or "")
                arguments = dict(params.get("arguments") or {})
                data = self.handle_tool_call(tool_name, arguments)
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {"type": "text", "text": json.dumps(data, indent=2, ensure_ascii=False)}
                        ],
                        "isError": False,
                    },
                }
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }
        except Exception as exc:
            if method == "tools/call":
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": f"Error: {exc}"}],
                        "isError": True,
                    },
                }
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32000, "message": str(exc)},
            }

    def serve_stdio(self) -> int:
        """Run the blocking JSON-RPC 2.0 stdio loop."""
        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError as exc:
                err = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {exc}"},
                }
                sys.stdout.write(json.dumps(err) + "\n")
                sys.stdout.flush()
                continue

            response = self.handle_message(msg)
            if response is not None:
                sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                sys.stdout.flush()
        return 0
