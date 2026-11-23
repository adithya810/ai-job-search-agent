"""Model Context Protocol (MCP) client connector for calling external web-search MCP servers.

Supports:
- Stdio transport (e.g., `npx -y exa-mcp-server`, `npx -y firecrawl-mcp`, or custom Python/Node MCP servers)
- Streamable HTTP transport (e.g., `https://mcp.exa.ai/mcp`, `http://localhost:3000/mcp`)

Zero external dependencies: implements MCP JSON-RPC 2.0 directly over stdlib `subprocess` / `urllib`.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Any
import urllib.error
import urllib.request

from ..base import BaseProvider
from ..env import load_dotenv
from ..models import JobListing, SearchConfig, SiteRunStatus
from .normalize import webpage_result_to_job

MCP_PROTOCOL_VERSION = "2024-11-05"


def _expand_env_map(env_spec: dict[str, str] | None) -> dict[str, str]:
    """Expand `${VAR}` references in configured MCP server environment maps."""
    load_dotenv()
    resolved = dict(os.environ)
    for key, val in (env_spec or {}).items():
        expanded = re.sub(
            r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}",
            lambda m: os.environ.get(m.group(1), ""),
            str(val),
        )
        if expanded:
            resolved[key] = expanded
    return resolved


def _missing_required_env(env_spec: dict[str, str] | None) -> list[str]:
    """Return environment variable names referenced as `${VAR}` that are currently unset."""
    load_dotenv()
    missing: list[str] = []
    for val in (env_spec or {}).values():
        for match in re.finditer(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", str(val)):
            var_name = match.group(1)
            if not os.environ.get(var_name):
                missing.append(var_name)
    return sorted(set(missing))


class StdioMCPClient:
    """JSON-RPC 2.0 MCP client over stdio subprocess transport."""

    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> None:
        self.command = command
        self.args = list(args or [])
        self.env = _expand_env_map(env)
        self.timeout = timeout
        self._proc: subprocess.Popen[str] | None = None
        self._next_id = 1

    def __enter__(self) -> "StdioMCPClient":
        self.connect()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def connect(self) -> dict[str, Any]:
        self._proc = subprocess.Popen(
            [self.command, *self.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=self.env,
            bufsize=1,
        )
        init_res = self._request(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "job-search-agent", "version": "1.1.0"},
            },
        )
        self._notify("notifications/initialized", {})
        return init_res

    def close(self) -> None:
        if self._proc is None:
            return
        try:
            if self._proc.stdin:
                self._proc.stdin.close()
            self._proc.wait(timeout=3)
        except Exception:
            try:
                self._proc.kill()
                self._proc.wait(timeout=2)
            except Exception:
                pass
        finally:
            for stream in (self._proc.stdout, self._proc.stderr):
                if stream:
                    try:
                        stream.close()
                    except Exception:
                        pass
            self._proc = None

    def _send(self, payload: dict[str, Any]) -> None:
        if not self._proc or not self._proc.stdin:
            raise RuntimeError("MCP stdio process is not running.")
        self._proc.stdin.write(json.dumps(payload) + "\n")
        self._proc.stdin.flush()

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        req_id = self._next_id
        self._next_id += 1
        self._send({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})

        if not self._proc or not self._proc.stdout:
            raise RuntimeError("MCP stdio stdout is unavailable.")

        while True:
            line = self._proc.stdout.readline()
            if not line:
                err_out = ""
                if self._proc.stderr:
                    try:
                        err_out = self._proc.stderr.read()[:400]
                    except Exception:
                        pass
                raise RuntimeError(f"MCP server exited before replying to {method}. {err_out}".strip())
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("id") != req_id:
                continue
            if "error" in msg:
                raise RuntimeError(f"MCP error on {method}: {msg['error']}")
            return dict(msg.get("result") or {})

    def list_tools(self) -> list[dict[str, Any]]:
        result = self._request("tools/list", {})
        return list(result.get("tools", []))

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._request("tools/call", {"name": name, "arguments": arguments})


class HttpMCPClient:
    """JSON-RPC 2.0 MCP client over Streamable HTTP POST transport."""

    def __init__(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> None:
        load_dotenv()
        self.url = url
        self.headers: dict[str, str] = {}
        for k, v in (headers or {}).items():
            self.headers[k] = re.sub(
                r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}",
                lambda m: os.environ.get(m.group(1), ""),
                str(v),
            )
        self.timeout = timeout
        self._next_id = 1
        self._session_id: str | None = None

    def __enter__(self) -> "HttpMCPClient":
        self.connect()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        hdrs = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": "job-search-agent/1.1",
            **self.headers,
        }
        if self._session_id:
            hdrs["Mcp-Session-Id"] = self._session_id

        req = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers=hdrs,
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                sid = resp.headers.get("Mcp-Session-Id")
                if sid:
                    self._session_id = sid
                raw = resp.read().decode("utf-8", errors="ignore").strip()
        except urllib.error.HTTPError as err:
            detail = err.read().decode("utf-8", errors="ignore")[:300]
            raise RuntimeError(f"HTTP MCP error {err.code}: {detail}") from err

        if not raw:
            return {}
        # Handle either direct JSON or SSE `data: {...}` lines.
        if raw.startswith("data:") or "\ndata:" in raw:
            for line in raw.splitlines():
                if line.startswith("data:"):
                    chunk = line[5:].strip()
                    if chunk:
                        return json.loads(chunk)
        return json.loads(raw)

    def connect(self) -> dict[str, Any]:
        req_id = self._next_id
        self._next_id += 1
        msg = self._post(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": "initialize",
                "params": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "job-search-agent", "version": "1.1.0"},
                },
            }
        )
        if "error" in msg:
            raise RuntimeError(f"HTTP MCP initialize failed: {msg['error']}")
        return dict(msg.get("result") or {})

    def list_tools(self) -> list[dict[str, Any]]:
        req_id = self._next_id
        self._next_id += 1
        msg = self._post({"jsonrpc": "2.0", "id": req_id, "method": "tools/list", "params": {}})
        return list((msg.get("result") or {}).get("tools", []))

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        req_id = self._next_id
        self._next_id += 1
        msg = self._post(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        )
        if "error" in msg:
            raise RuntimeError(f"HTTP MCP tool {name} failed: {msg['error']}")
        return dict(msg.get("result") or {})


def parse_mcp_tool_results(
    tool_result: dict[str, Any],
    *,
    server_name: str,
    query_matched: str = "",
    location_searched: str = "India",
) -> list[JobListing]:
    """Parse structured JSON or text content returned by an MCP web-search tool into JobListings."""
    content_blocks = tool_result.get("content") or []
    jobs: list[JobListing] = []

    for block in content_blocks:
        if not isinstance(block, dict):
            continue
        text = str(block.get("text") or "").strip()
        if not text:
            continue

        # Attempt JSON parse first (Exa MCP, Firecrawl MCP, and job-search-agent MCP return JSON).
        parsed_json: Any = None
        try:
            parsed_json = json.loads(text)
        except json.JSONDecodeError:
            parsed_json = None

        if parsed_json is not None:
            items: list[dict[str, Any]] = []
            if isinstance(parsed_json, list):
                items = [x for x in parsed_json if isinstance(x, dict)]
            elif isinstance(parsed_json, dict):
                for key in ("results", "jobs", "data", "web"):
                    val = parsed_json.get(key)
                    if isinstance(val, list):
                        items = [x for x in val if isinstance(x, dict)]
                        break
                    if isinstance(val, dict) and isinstance(val.get("web"), list):
                        items = [x for x in val["web"] if isinstance(x, dict)]
                        break
            for item in items:
                url = str(item.get("url") or item.get("link") or "").strip()
                title = str(item.get("title") or "").strip()
                if not url and not title:
                    continue
                body = str(
                    item.get("text")
                    or item.get("markdown")
                    or item.get("description")
                    or item.get("snippet")
                    or ""
                )
                jobs.append(
                    webpage_result_to_job(
                        url=url,
                        raw_title=title,
                        content_text=body,
                        connector_name=f"mcp:{server_name}",
                        posted_date=str(item.get("publishedDate") or item.get("posted_date") or ""),
                        query_matched=query_matched,
                        location_searched=location_searched,
                    )
                )
            continue

        # Fallback: extract markdown links `[Title](https://...)` from plain-text MCP outputs.
        for match in re.finditer(r"\[([^\]]{4,160})\]\((https?://[^\s)]+)\)", text):
            title, url = match.group(1).strip(), match.group(2).strip()
            jobs.append(
                webpage_result_to_job(
                    url=url,
                    raw_title=title,
                    content_text=text[:1500],
                    connector_name=f"mcp:{server_name}",
                    query_matched=query_matched,
                    location_searched=location_searched,
                )
            )

    return jobs


def create_mcp_client(server_cfg: dict[str, Any]) -> StdioMCPClient | HttpMCPClient:
    """Instantiate a stdio or HTTP MCP client from a `config.json` mcp_servers entry."""
    transport = str(server_cfg.get("transport", "stdio")).lower()
    if transport == "http":
        return HttpMCPClient(
            url=str(server_cfg["url"]),
            headers=dict(server_cfg.get("headers") or {}),
        )
    return StdioMCPClient(
        command=str(server_cfg["command"]),
        args=list(server_cfg.get("args") or []),
        env=dict(server_cfg.get("env") or {}),
    )


class MCPWebSearchProvider(BaseProvider):
    """Provider that queries enabled external MCP web-search servers (Exa MCP, Firecrawl MCP, etc.)."""

    site_name = "mcp"
    login_url = ""

    def __init__(self, config: SearchConfig) -> None:
        super().__init__(config)

    def search_public(
        self,
        queries: list[str],
        locations: list[str],
        max_results_per_query: int,
    ) -> tuple[list[JobListing], SiteRunStatus]:
        servers = self.config.mcp_servers or {}
        enabled = {name: cfg for name, cfg in servers.items() if cfg.get("enabled", False)}
        if not enabled:
            return [], SiteRunStatus(
                site=self.site_name,
                mode_used="mcp",
                status="not_configured",
                jobs_found=0,
                message=(
                    "No external MCP servers are enabled in config.json (`mcp_servers`). "
                    "Set `enabled: true` on `exa` or `firecrawl` in config.json and configure its API key "
                    "in `.env`, or connect your AI client directly to `python3 -m job_agent mcp-serve`."
                ),
            )

        collected: list[JobListing] = []
        seen_urls: set[str] = set()
        notes: list[str] = []

        for server_name, server_cfg in enabled.items():
            missing = _missing_required_env(server_cfg.get("env"))
            if missing:
                notes.append(f"{server_name}: missing env {', '.join(missing)}")
                continue

            tool_name = str(server_cfg.get("search_tool") or "web_search_exa")
            query_arg = str(server_cfg.get("query_arg") or "query")
            limit_arg = str(server_cfg.get("limit_arg") or "numResults")
            extra_args = dict(server_cfg.get("extra_args") or {})

            try:
                with create_mcp_client(server_cfg) as client:
                    for query in queries:
                        for location in locations:
                            city = location.split(",")[0].strip()
                            full_query = f"{query} job opening in {city} India SQL Python Power BI Tableau"
                            call_args = {
                                **extra_args,
                                query_arg: full_query,
                                limit_arg: max_results_per_query,
                            }
                            result = client.call_tool(tool_name, call_args)
                            parsed = parse_mcp_tool_results(
                                result,
                                server_name=server_name,
                                query_matched=query,
                                location_searched=location,
                            )
                            for job in parsed:
                                if job.url and job.url in seen_urls:
                                    continue
                                if job.url:
                                    seen_urls.add(job.url)
                                collected.append(job)
                            self.polite_sleep()
                notes.append(f"{server_name}: ok")
            except Exception as exc:
                notes.append(f"{server_name}: error ({exc})")

        status = "ok" if collected else ("missing_api_key" if any("missing env" in n for n in notes) else "partial")
        return collected, SiteRunStatus(
            site=self.site_name,
            mode_used="mcp",
            status=status,
            jobs_found=len(collected),
            message=f"MCP web search completed ({len(collected)} jobs). Details: {'; '.join(notes)}",
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
