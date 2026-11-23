"""Minimal zero-dependency .env loader for API keys (EXA_API_KEY, FIRECRAWL_API_KEY)."""

from __future__ import annotations

import os
from pathlib import Path


def load_dotenv(env_path: Path | None = None) -> None:
    """Load KEY=VALUE pairs from a local .env file without overwriting existing env vars."""
    path = env_path or (Path(__file__).resolve().parent.parent / ".env")
    if not path.exists():
        return
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        return
