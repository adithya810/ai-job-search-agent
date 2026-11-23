"""Job board and web search connector provider registry."""

from ..connectors.exa import ExaProvider
from ..connectors.firecrawl import FirecrawlProvider
from ..connectors.mcp_client import MCPWebSearchProvider
from .base import BaseProvider
from .linkedin import LinkedInProvider
from .naukri import NaukriProvider
from .ziprecruiter import ZipRecruiterProvider

PROVIDERS: dict[str, type[BaseProvider]] = {
    "linkedin": LinkedInProvider,
    "naukri": NaukriProvider,
    "ziprecruiter": ZipRecruiterProvider,
    "exa": ExaProvider,
    "firecrawl": FirecrawlProvider,
    "mcp": MCPWebSearchProvider,
}

__all__ = [
    "BaseProvider",
    "LinkedInProvider",
    "NaukriProvider",
    "ZipRecruiterProvider",
    "ExaProvider",
    "FirecrawlProvider",
    "MCPWebSearchProvider",
    "PROVIDERS",
]
