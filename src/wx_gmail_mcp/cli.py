"""Command-line entry point.

``--auth`` and ``--list`` run in a terminal (OAuth opens a browser, and
an MCP client's sandbox may block the loopback flow). With no command the
process serves MCP over stdio. ``--doctor`` and ``--print-config`` arrive
in later phases.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from google.auth.exceptions import GoogleAuthError
from googleapiclient.errors import HttpError

from wx_gmail_mcp import __version__, auth, server
from wx_gmail_mcp.config import Settings
from wx_gmail_mcp.errors import WxGmailError

PROG = "wx-gmail-mcp"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=(
            "Self-hosted, multi-account Gmail MCP server. With no command, "
            "serves MCP over stdio."
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    command = parser.add_mutually_exclusive_group()
    command.add_argument(
        "--auth",
        metavar="ALIAS",
        help="authorize a Gmail account in the browser and store its token",
    )
    command.add_argument(
        "--list", action="store_true", help="list accounts, token health, scopes"
    )
    parser.add_argument(
        "--email", metavar="ADDRESS", help="account to sign in with (for --auth)"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.auth and not args.email:
        parser.error("--email is required with --auth")
    if args.email and not args.auth:
        parser.error("--email only makes sense with --auth")
    settings = Settings.from_env()
    try:
        if args.auth:
            print(auth.run_oauth(settings, args.auth, args.email).text())
            return 0
        if args.list:
            print("\n".join(auth.account_status_lines(settings)))
            return 0
    except WxGmailError as e:
        print(f"{PROG}: error: {e}", file=sys.stderr)
        return 1
    except (HttpError, GoogleAuthError, OSError) as e:
        print(f"{PROG}: error: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    server.serve(settings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
