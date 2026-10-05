"""The version, the changelog and the README status line agree."""

from __future__ import annotations

import re
from pathlib import Path

from wx_gmail_mcp import __version__

ROOT = Path(__file__).resolve().parents[1]
RELEASE_RE = re.compile(r"^\d+\.\d+\.\d+$")
HEADING_RE = re.compile(r"^## \[(\d+\.\d+\.\d+)\] - (\d{4}-\d{2}-\d{2})$", re.MULTILINE)


def test_version_is_a_release() -> None:
    assert RELEASE_RE.fullmatch(__version__), __version__


def test_changelog_top_release_is_the_version() -> None:
    text = (ROOT / "CHANGELOG.md").read_text()
    releases = HEADING_RE.findall(text)
    assert releases, "no release heading"
    assert releases[0][0] == __version__
    assert text.index("## [Unreleased]") < text.index(f"## [{__version__}]")
    assert f"[{__version__}]: https://github.com/whitechno/wx-gmail-mcp/" in text
    assert f"compare/v{__version__}...HEAD" in text


def test_readme_status_names_the_version() -> None:
    readme = (ROOT / "README.md").read_text()
    assert f"**Status:** `v{__version__}`" in readme
