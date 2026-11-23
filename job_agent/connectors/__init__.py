"""Web search & scraping connectors (Exa, Firecrawl, and MCP client)."""

from .exa import ExaConnector, ExaProvider
from .firecrawl import FirecrawlConnector, FirecrawlProvider
from .mcp_client import HttpMCPClient, MCPWebSearchProvider, StdioMCPClient

__all__ = [
    "ExaConnector",
    "ExaProvider",
    "FirecrawlConnector",
    "FirecrawlProvider",
    "StdioMCPClient",
    "HttpMCPClient",
    "MCPWebSearchProvider",
]
