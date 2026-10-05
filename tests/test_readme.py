"""The README's tool overview and counts must match the server catalogue."""

from __future__ import annotations

import re
from pathlib import Path

from .test_server import ALWAYS_ON, DELETE, SENDING, SETTINGS

README = Path(__file__).resolve().parents[1] / "README.md"


def tools_section() -> str:
    text = README.read_text()
    start = text.index("\n## Tools\n")
    end = text.index("\n## ", start + 1)
    return text[start:end]


def test_readme_tool_table_matches_the_catalogue() -> None:
    section = tools_section()
    rows = [line for line in section.splitlines() if line.startswith("| ")]
    # The header row has no backticks, so every row can be scanned.
    listed = {name for row in rows for name in re.findall(r"`([a-z_]+)`", row)}
    assert listed == set(ALWAYS_ON) | SENDING | SETTINGS | DELETE


def test_readme_tool_counts() -> None:
    base = len(ALWAYS_ON)
    total = base + len(SENDING) + len(SETTINGS) + len(DELETE)
    assert f"{base} tools with no gate, {total} with all three" in tools_section()
    # The same numbers appear in docs/CLIENTS.md's matrix note.
    clients = re.sub(r"\s+", " ", (README.parent / "docs/CLIENTS.md").read_text())
    assert f"out of the {total} the server registers" in clients
    assert f"({base} with none)" in clients
