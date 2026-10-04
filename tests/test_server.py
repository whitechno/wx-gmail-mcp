from __future__ import annotations

import asyncio
import itertools
from pathlib import Path

import pytest

from wx_gmail_mcp import __version__, server
from wx_gmail_mcp.gmail import Runtime

from .conftest import make_settings


@pytest.mark.parametrize(
    ("sending", "settings", "delete"), list(itertools.product([False, True], repeat=3))
)
def test_build_server_for_every_gate_combination(
    tmp_path: Path, sending: bool, settings: bool, delete: bool
) -> None:
    s = make_settings(tmp_path, sending=sending, settings=settings, delete=delete)
    mcp = server.build_server(Runtime(s))
    assert mcp.name == "wx-gmail-mcp"
    assert mcp.version == __version__
    assert mcp.instructions is not None
    assert "list_accounts" in mcp.instructions
    # Tool modules arrive in the next pull requests; the table is wired already.
    assert asyncio.run(mcp.list_tools()) == []


def test_tool_groups_cover_each_gate() -> None:
    checks = [is_on for is_on, _ in server.TOOL_GROUPS]
    always, send, settings, delete = checks
    from wx_gmail_mcp.config import Gates

    off = Gates()
    assert [c(off) for c in checks] == [True, False, False, False]
    assert send(Gates(sending=True)) and not send(Gates(settings=True))
    assert settings(Gates(settings=True)) and not settings(Gates(delete=True))
    assert delete(Gates(delete=True)) and not delete(Gates(sending=True))
    assert always(Gates(sending=True, settings=True, delete=True))
