#!/usr/bin/env python3
"""Pre-install check for wx-gmail-mcp: one line per tool, exit 1 if uv is missing.

Runs with any Python 3 and no dependencies, before the server exists.
Once wx-gmail-mcp is installed, ``wx-gmail-mcp --doctor`` is the full
check; this script only answers "can this machine install it?".
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

MIN_PYTHON = (3, 14)


def run(argv: list[str]) -> str:
    """stdout of a command, or an empty string if it fails or is absent."""
    try:
        done = subprocess.run(  # noqa: S603 - fixed argv, no shell
            argv, capture_output=True, text=True, timeout=60, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def line(status: str, name: str, detail: str) -> None:
    print(f"{status:<4} {name}: {detail}")


def main() -> int:
    failed = False

    uv = shutil.which("uv")
    if uv:
        line("ok", "uv", f"{run([uv, '--version']) or 'present'} at {uv}")
    else:
        failed = True
        line(
            "FAIL",
            "uv",
            "not found; install it first: https://docs.astral.sh/uv/getting-started/",
        )

    # uv downloads a 3.14 interpreter on demand, so a missing one is a note.
    need = ".".join(str(v) for v in MIN_PYTHON)
    found = run([uv, "python", "find", f">={need}"]) if uv else ""
    if found:
        line("ok", "python", f"{need}+ at {found}")
    elif uv:
        line("info", "python", f"no {need}+ yet; uv installs one on first run")
    else:
        line("info", "python", f"wx-gmail-mcp needs Python {need} or newer")

    gcloud = shutil.which("gcloud")
    if not gcloud:
        line("info", "gcloud", "not installed; optional (the console steps replace it)")
    else:
        version = run([gcloud, "--version"]).splitlines()
        line("ok", "gcloud", f"{version[0] if version else 'present'} at {gcloud}")
        account = run(
            [
                gcloud,
                "auth",
                "list",
                "--filter=status:ACTIVE",
                "--format=value(account)",
            ]
        )
        if account:
            line("ok", "gcloud login", f"active account {account}")
        else:
            line("warn", "gcloud login", "no active account; run: gcloud auth login")

    server = shutil.which("wx-gmail-mcp")
    if server:
        line("ok", "wx-gmail-mcp", f"installed at {server}; run: wx-gmail-mcp --doctor")
    else:
        line(
            "info",
            "wx-gmail-mcp",
            "not installed yet; run: "
            "uv tool install git+https://github.com/whitechno/wx-gmail-mcp",
        )

    home = os.environ.get("WX_GMAIL_MCP_HOME", "").strip() or "~/.wx-gmail-mcp"
    line(
        "info",
        "home",
        f"{home}"
        + (" (WX_GMAIL_MCP_HOME)" if "WX_GMAIL_MCP_HOME" in os.environ else ""),
    )

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
