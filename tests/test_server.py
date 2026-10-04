from __future__ import annotations

import asyncio
import itertools
import re
from pathlib import Path
from typing import Any

import pytest

from wx_gmail_mcp import __version__, server
from wx_gmail_mcp.config import Gates
from wx_gmail_mcp.gmail import Runtime

from .conftest import make_settings, tool_names

# The tool catalogue (plan §5), by gate. Registration must match exactly.
ALWAYS_ON = {
    "list_accounts",
    "add_account",
    "remove_account",
    "search",
    "read_message",
    "read_thread",
    "list_labels",
    "modify_labels",
    "mark_read",
    "mark_unread",
    "archive",
}
SENDING: set[str] = set()
SETTINGS: set[str] = set()
DELETE: set[str] = set()

TOOL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,40}$")
SIMPLE_TYPES = {"string", "integer", "number", "boolean"}
BANNED_KEYS = {"$ref", "$defs", "anyOf", "oneOf", "allOf", "not"}


def _expected(sending: bool, settings: bool, delete: bool) -> set[str]:
    names = set(ALWAYS_ON)
    if sending:
        names |= SENDING
    if settings:
        names |= SETTINGS
    if delete:
        names |= DELETE
    return names


@pytest.mark.parametrize(
    ("sending", "settings", "delete"), list(itertools.product([False, True], repeat=3))
)
def test_registered_tools_match_catalogue_per_gate(
    tmp_path: Path, sending: bool, settings: bool, delete: bool
) -> None:
    s = make_settings(tmp_path, sending=sending, settings=settings, delete=delete)
    mcp = server.build_server(Runtime(s))
    assert mcp.name == "wx-gmail-mcp"
    assert mcp.version == __version__
    assert mcp.instructions is not None
    assert "list_accounts" in mcp.instructions
    assert tool_names(mcp) == _expected(sending, settings, delete)


def test_tool_groups_cover_each_gate() -> None:
    always, send, settings, delete = (is_on for is_on, _ in server.TOOL_GROUPS)
    off = Gates()
    assert (always(off), send(off), settings(off), delete(off)) == (
        True,
        False,
        False,
        False,
    )
    assert send(Gates(sending=True)) and not send(Gates(settings=True))
    assert settings(Gates(settings=True)) and not settings(Gates(delete=True))
    assert delete(Gates(delete=True)) and not delete(Gates(sending=True))
    assert always(Gates(sending=True, settings=True, delete=True))


def _walk(node: Any) -> Any:
    if isinstance(node, dict):
        for key, value in node.items():
            yield key, value
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def test_every_tool_schema_is_portable(tmp_path: Path) -> None:
    """Plan §9.2: flat schemas, simple types, no unions or nested objects."""
    s = make_settings(tmp_path, sending=True, settings=True, delete=True)
    tools = asyncio.run(server.build_server(Runtime(s)).list_tools())
    assert tools, "no tools registered"
    for tool in tools:
        assert TOOL_NAME_RE.fullmatch(tool.name), tool.name
        assert tool.description and tool.description.strip(), tool.name
        assert "claude" not in tool.description.lower(), tool.name
        assert tool.output_schema is None, tool.name
        schema = tool.input_schema
        assert schema["type"] == "object"
        banned = {k for k, _ in _walk(schema)} & BANNED_KEYS
        assert not banned, f"{tool.name}: {banned}"
        for pname, prop in schema.get("properties", {}).items():
            where = f"{tool.name}.{pname}"
            ptype = prop.get("type")
            if ptype == "array":
                assert prop["items"].get("type") in SIMPLE_TYPES, where
            else:
                assert ptype in SIMPLE_TYPES, where
            if pname not in schema.get("required", []):
                assert "default" in prop and prop["default"] is not None, where
