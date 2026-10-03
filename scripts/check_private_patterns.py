#!/usr/bin/env python3
"""Private-pattern guard: fail when maintainer-listed patterns appear.

The pattern list holds things that must never reach the public repo
(real addresses, home paths, project numbers, client-id prefixes). The
list itself is private, so it is read from:

1. the environment variable ``PRIVATE_PATTERNS`` (CI, from a repo
   secret), or
2. ``$WX_GMAIL_MCP_HOME/private-patterns.txt``, default
   ``~/.wx-gmail-mcp/private-patterns.txt`` (local pre-commit hook).

One regular expression per line; blank lines and ``#`` comments are
ignored. Matching is case-insensitive.

With no list available the guard is a no-op that prints a notice, so
forks and fresh clones still work.

Usage::

    check_private_patterns.py [FILE ...]      # given files (pre-commit)
    check_private_patterns.py --all           # every tracked file
    check_private_patterns.py --commits A..B  # also commit messages

Output names the file, line number and pattern index only. It never
prints the matched text or the pattern, so logs cannot leak either.
Exit status 1 when anything matched.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ENV_VAR = "PRIVATE_PATTERNS"
HOME_VAR = "WX_GMAIL_MCP_HOME"
LOCAL_NAME = "private-patterns.txt"
# Files that are binary or generated; skipped entirely.
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".gz"}


def load_patterns() -> tuple[list[re.Pattern[str]], str]:
    """Return (compiled patterns, source description)."""
    raw = os.environ.get(ENV_VAR)
    source = f"${ENV_VAR}"
    if not raw:
        home = Path(os.environ.get(HOME_VAR) or Path.home() / ".wx-gmail-mcp")
        path = home / LOCAL_NAME
        if not path.is_file():
            return [], ""
        raw = path.read_text(encoding="utf-8")
        source = str(path)
    patterns: list[re.Pattern[str]] = []
    for lineno, line in enumerate(raw.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            patterns.append(re.compile(line, re.IGNORECASE))
        except re.error:
            print(f"private-patterns: invalid regex on line {lineno} of {source}")
            sys.exit(2)
    return patterns, source


GIT = shutil.which("git") or "git"


def git(*args: str) -> str:
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        [GIT, *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def tracked_files() -> list[str]:
    return [line for line in git("ls-files", "-z").split("\0") if line]


def scan_text(label: str, text: str, patterns: list[re.Pattern[str]]) -> int:
    hits = 0
    for lineno, line in enumerate(text.splitlines(), 1):
        for index, pattern in enumerate(patterns, 1):
            if pattern.search(line):
                print(f"{label}:{lineno}: private pattern #{index} matched")
                hits += 1
    return hits


def scan_file(path: str, patterns: list[re.Pattern[str]]) -> int:
    file = Path(path)
    if not file.is_file() or file.suffix.lower() in SKIP_SUFFIXES:
        return 0
    data = file.read_bytes()
    if b"\0" in data:
        return 0
    return scan_text(path, data.decode("utf-8", errors="replace"), patterns)


def scan_commits(rev_range: str, patterns: list[re.Pattern[str]]) -> int:
    hits = 0
    log = git("log", "--format=%H%x00%B%x00", rev_range)
    parts = log.split("\0")
    for sha, body in zip(parts[0::2], parts[1::2], strict=False):
        if sha.strip():
            hits += scan_text(f"commit {sha.strip()[:12]}", body, patterns)
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("files", nargs="*", help="files to scan")
    parser.add_argument("--all", action="store_true", help="scan all tracked files")
    parser.add_argument("--commits", metavar="RANGE", help="also scan messages")
    args = parser.parse_args(argv)

    patterns, source = load_patterns()
    if not patterns:
        print("private-patterns: no pattern list found; nothing checked")
        return 0
    print(f"private-patterns: using {source}")

    files = tracked_files() if args.all or not args.files else args.files
    hits = sum(scan_file(f, patterns) for f in files)
    if args.commits:
        hits += scan_commits(args.commits, patterns)

    n = len(patterns)
    if hits:
        print(f"private-patterns: {hits} match(es) against {n} pattern(s)")
        return 1
    print(f"private-patterns: clean ({len(files)} files, {n} patterns)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
