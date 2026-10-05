#!/usr/bin/env python3
"""Move a downloaded OAuth client JSON into the wx-gmail-mcp home. Idempotent.

    install_client_json.py              newest client_secret_*.json in ~/Downloads
    install_client_json.py PATH         that file
    install_client_json.py --check      report the installed file; fixes its modes

The file is checked for the Desktop app shape (an ``installed`` key with
client_id, client_secret, auth_uri and token_uri), moved (not copied) to
``$WX_GMAIL_MCP_HOME/oauth_client.json`` or ``~/.wx-gmail-mcp/oauth_client.json``,
and the directory and file get modes 700 and 600. Nothing from inside the
file is printed except the project id. Exit 1 on any problem.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

REQUIRED = ("client_id", "client_secret", "auth_uri", "token_uri")


def home_dir() -> Path:
    override = os.environ.get("WX_GMAIL_MCP_HOME", "").strip()
    return Path(override).expanduser() if override else Path.home() / ".wx-gmail-mcp"


def newest_download() -> Path | None:
    downloads = Path.home() / "Downloads"
    if not downloads.is_dir():
        return None
    candidates = sorted(
        downloads.glob("client_secret*.json"), key=lambda p: p.stat().st_mtime
    )
    return candidates[-1] if candidates else None


def shape_error(path: Path) -> str | None:
    """None if ``path`` holds a Desktop app client, else what is wrong."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        return f"{path} is not readable JSON ({e})"
    if not isinstance(data, dict):
        return f"{path} does not hold a JSON object"
    if "web" in data:
        return (
            f"{path} is a Web application client; create a Desktop app client "
            "instead and download its JSON"
        )
    installed = data.get("installed")
    if not isinstance(installed, dict):
        return f"{path} has no 'installed' key; download the Desktop app client JSON"
    missing = [k for k in REQUIRED if not installed.get(k)]
    if missing:
        return f"{path} lacks {', '.join(missing)}"
    return None


def project_of(path: Path) -> str:
    data = json.loads(path.read_text())
    return str(data.get("installed", {}).get("project_id") or "unknown")


def secure(home: Path, target: Path) -> None:
    home.mkdir(parents=True, exist_ok=True)
    home.chmod(0o700)
    target.chmod(0o600)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("path", nargs="?", help="downloaded client JSON")
    parser.add_argument(
        "--check", action="store_true", help="report the installed file, fix modes"
    )
    args = parser.parse_args(argv)

    home = home_dir()
    target = home / "oauth_client.json"

    if args.check:
        if not target.is_file():
            print(f"FAIL oauth client: {target} missing")
            return 1
        error = shape_error(target)
        if error:
            print(f"FAIL oauth client: {error}")
            return 1
        secure(home, target)
        print(f"ok   oauth client: {target}, project {project_of(target)}, mode 600")
        return 0

    if not args.path and target.is_file() and shape_error(target) is None:
        secure(home, target)
        print(f"ok   oauth client: already installed at {target}; a path replaces it")
        return 0
    source = Path(args.path).expanduser() if args.path else newest_download()
    if source is None:
        print("FAIL oauth client: no client_secret*.json in ~/Downloads; pass the path")
        return 1
    if not source.is_file():
        print(f"FAIL oauth client: {source} is not a file")
        return 1
    error = shape_error(source)
    if error:
        print(f"FAIL oauth client: {error}")
        return 1
    if source.resolve() == target.resolve():
        secure(home, target)
        print(f"ok   oauth client: already in place at {target}")
        return 0

    home.mkdir(parents=True, exist_ok=True)
    home.chmod(0o700)
    if target.exists():
        backup = target.with_suffix(".json.previous")
        shutil.move(target, backup)
        backup.chmod(0o600)
        print(f"info oauth client: previous file kept as {backup}")
    shutil.move(source, target)
    secure(home, target)
    print(
        f"ok   oauth client: moved to {target}, project {project_of(target)}, mode 600"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
