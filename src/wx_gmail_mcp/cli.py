"""Command-line entry point.

``--auth`` and ``--list`` run in a terminal (OAuth opens a browser, and
an MCP client's sandbox may block the loopback flow). ``--print-config``
prints the registration block for a client and ``--doctor`` checks the
installation. With no command the process serves MCP over stdio.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from google.auth.exceptions import GoogleAuthError
from googleapiclient.errors import HttpError

from wx_gmail_mcp import __version__, auth, clients, doctor, server
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
    command.add_argument(
        "--doctor",
        action="store_true",
        help=(
            "check the installation: tools, home directory, OAuth client, "
            "accounts and scopes, client registrations; exit 1 on any failure"
        ),
    )
    command.add_argument(
        "--print-config",
        metavar="CLIENT",
        choices=clients.HARNESS_NAMES,
        help=(
            "print a ready-to-paste registration block for an MCP client "
            f"({', '.join(clients.HARNESS_NAMES)}), with the gates on in the "
            "current environment"
        ),
    )
    parser.add_argument(
        "--email", metavar="ADDRESS", help="account to sign in with (for --auth)"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.auth is not None and not args.email:
        parser.error("--email is required with --auth")
    if args.email and args.auth is None:
        parser.error("--email only makes sense with --auth")
    settings = Settings.from_env()
    try:
        if args.auth is not None:
            print(auth.run_oauth(settings, args.auth, args.email).text())
            return 0
        if args.list:
            print("\n".join(auth.account_status_lines(settings)))
            return 0
        if args.print_config is not None:
            block, hint = clients.print_config(args.print_config, settings, os.environ)
            print(block, end="")
            print(f"# {hint}", file=sys.stderr)
            return 0
        if args.doctor:
            loc = doctor.Locator(Path.home(), Path.cwd(), os.environ)
            checks = doctor.run_doctor(settings, os.environ, loc)
            print(doctor.doctor_text(checks))
            return 1 if any(c.failed for c in checks) else 0
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
