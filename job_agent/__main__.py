"""Module entry point for `python3 -m job_agent`."""

import sys

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
