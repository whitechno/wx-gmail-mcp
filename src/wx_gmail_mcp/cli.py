"""Command-line entry point.

Phase 1 provides only ``--version``. The ``--auth``, ``--list``,
``--doctor`` and ``--print-config`` commands, and the server itself,
arrive in later phases.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from wx_gmail_mcp import __version__

PROG = "wx-gmail-mcp"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Self-hosted, multi-account Gmail MCP server.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    print(f"{PROG}: the server is not implemented yet.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
