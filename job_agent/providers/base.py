"""Re-export BaseProvider and HTTP helpers for backward compatibility."""

from ..base import BaseProvider, DEFAULT_USER_AGENT, fetch_url, strip_html

__all__ = ["BaseProvider", "DEFAULT_USER_AGENT", "fetch_url", "strip_html"]
