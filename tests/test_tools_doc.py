"""docs/TOOLS.md must list exactly the server's tools, with their parameters."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

import pytest

from wx_gmail_mcp import server
from wx_gmail_mcp.gmail import Runtime

from .conftest import make_settings
from .test_server import ALWAYS_ON, DELETE, SENDING, SETTINGS

DOC = Path(__file__).resolve().parents[1] / "docs" / "TOOLS.md"
CATALOGUE = set(ALWAYS_ON) | SENDING | SETTINGS | DELETE
HEADING_RE = re.compile(r"^### `([a-z_]+)`$", re.MULTILINE)
PARAM_HEADER = "| Parameter | Type | Default | Meaning |"


def doc_text() -> str:
    return DOC.read_text()


def sections() -> dict[str, str]:
    """Each tool's section text, from its heading to the next heading."""
    text = doc_text()
    found = list(HEADING_RE.finditer(text))
    out: dict[str, str] = {}
    for i, m in enumerate(found):
        end = found[i + 1].start() if i + 1 < len(found) else len(text)
        assert m.group(1) not in out, f"{m.group(1)} documented twice"
        out[m.group(1)] = text[m.end() : end]
    return out


def param_rows(section: str) -> list[tuple[str, str, str]]:
    """(name, type, default) per row of the section's parameter table."""
    lines = section.splitlines()
    start = lines.index(PARAM_HEADER)
    assert lines[start + 1].startswith("|---"), "separator row missing"
    rows: list[tuple[str, str, str]] = []
    for line in lines[start + 2 :]:
        if not line.startswith("| "):
            break
        cells = [c.strip() for c in line.strip("|").split("|")]
        assert len(cells) == 4, line
        name = cells[0]
        assert name.startswith("`") and name.endswith("`"), line
        rows.append((name.strip("`"), cells[1], cells[2]))
    return rows


def schema_rows(tool: Any) -> list[tuple[str, str, str]]:
    """The same triples, rendered from the tool's input schema."""
    schema = tool.input_schema
    required = set(schema.get("required", []))
    rows: list[tuple[str, str, str]] = []
    for name, prop in schema.get("properties", {}).items():
        ptype = "list of strings" if prop.get("type") == "array" else prop["type"]
        rows.append((name, ptype, render_default(prop, name in required)))
    return rows


def render_default(prop: dict[str, Any], required: bool) -> str:
    if required:
        return "required"
    value = prop["default"]
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        return "[]"
    return f'"{value}"'


@pytest.fixture(scope="module")
def tools(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    s = make_settings(
        tmp_path_factory.mktemp("home"), sending=True, settings=True, delete=True
    )
    listed = asyncio.run(server.build_server(Runtime(s)).list_tools())
    return {t.name: t for t in listed}


def test_tools_doc_lists_exactly_the_catalogue(tools: dict[str, Any]) -> None:
    assert set(tools) == CATALOGUE
    assert set(sections()) == CATALOGUE


def test_tools_doc_overview_table_lists_each_tool_once() -> None:
    text = doc_text()
    overview = text[: text.index("\n## ")]
    rows = [line for line in overview.splitlines() if line.startswith("| [")]
    listed = [name for row in rows for name in re.findall(r"`([a-z_]+)`", row)]
    assert sorted(listed) == sorted(CATALOGUE)


def test_tools_doc_parameter_tables_match_the_schemas(tools: dict[str, Any]) -> None:
    for name, section in sections().items():
        assert param_rows(section) == schema_rows(tools[name]), name


def test_tools_doc_names_gate_and_scope_per_group() -> None:
    text = doc_text()
    for group, gate in (
        ("## Trash and delete", "WX_GMAIL_ALLOW_DELETE"),
        ("## Send", "WX_GMAIL_ALLOW_SENDING"),
        ("## Filters", "WX_GMAIL_ALLOW_SETTINGS"),
        ("## Settings", "WX_GMAIL_ALLOW_SETTINGS"),
    ):
        start = text.index(f"\n{group}\n")
        intro = text[start : text.index("\n### ", start)]
        assert f"Gate: `{gate}`" in intro, group
        assert "Scope:" in intro, group
    for group in ("## Accounts", "## Read and search", "## Labels", "## Organize"):
        start = text.index(f"\n{group}\n")
        intro = text[start : text.index("\n### ", start)]
        assert "Gate: none" in intro, group


def test_tools_doc_examples_use_placeholders_only() -> None:
    addresses = set(re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[a-z]{2,}", doc_text()))
    assert addresses, "no example addresses?"
    domains = [a.rsplit("@", 1)[1].split(".") for a in addresses]
    assert all(d[-2:] == ["example", "com"] for d in domains), addresses
    assert "/Users/" not in doc_text()
