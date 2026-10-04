from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httplib2
import pytest
from googleapiclient.errors import HttpError
from mcp.server.mcpserver import MCPServer

from wx_gmail_mcp import safety
from wx_gmail_mcp.config import Settings
from wx_gmail_mcp.errors import WxGmailError


def _http_error() -> HttpError:
    resp = httplib2.Response({"status": 404, "reason": "Not Found"})
    content = json.dumps({"error": {"message": "Requested entity was not found."}})
    return HttpError(resp, content.encode(), uri="https://gmail.example/messages/x")


def test_safe_turns_errors_into_text() -> None:
    def ok(account: str) -> str:
        return f"fine {account}"

    def api_fail(account: str) -> str:
        raise _http_error()

    def user_fail(account: str) -> str:
        raise WxGmailError("bad alias")

    def crash(account: str) -> str:
        raise KeyError("payload")

    assert safety.safe(ok)("a") == "fine a"
    text = safety.safe(api_fail)("a")
    assert text == "Gmail API error: HTTP 404: Requested entity was not found."
    assert "gmail.example" not in text
    assert safety.safe(user_fail)("a") == "Error: bad alias"
    assert safety.safe(crash)("a") == "Error: KeyError: 'payload'"


def test_describe_http_error_without_json_body() -> None:
    resp = httplib2.Response({"status": 503})
    resp.reason = "Service Unavailable"
    err = HttpError(resp, b"<html>oops</html>", uri="https://gmail.example/x")
    assert safety.describe_http_error(err) == "HTTP 503: Service Unavailable"
    bare = HttpError(httplib2.Response({"status": 500}), b"")
    bare.reason = ""
    assert safety.describe_http_error(bare) == "HTTP 500: request failed"


def _tool(account: str, query: str, max_results: int = 10, ids: list[str] = []) -> str:  # noqa: B006
    """Search things."""
    return account + query


def test_register_tool_keeps_schema_and_drops_output_schema() -> None:
    raw = MCPServer("raw")
    raw.add_tool(_tool)
    wrapped = MCPServer("wrapped")
    safety.register_tool(wrapped, _tool)

    (raw_tool,) = asyncio.run(raw.list_tools())
    (wrapped_tool,) = asyncio.run(wrapped.list_tools())
    assert wrapped_tool.name == "_tool"
    assert wrapped_tool.description == "Search things."
    assert wrapped_tool.input_schema == raw_tool.input_schema
    assert wrapped_tool.output_schema is None
    assert raw_tool.output_schema is not None

    result = asyncio.run(wrapped.call_tool("_tool", {"account": "a", "query": "q"}))
    assert not isinstance(result, dict)
    assert result.model_dump()["content"][0]["text"] == "aq"


def test_require_ids() -> None:
    assert safety.require_ids([" a ", "", "b"]) == ["a", "b"]
    with pytest.raises(WxGmailError, match="at least one id"):
        safety.require_ids(["", "  "])
    with pytest.raises(WxGmailError, match="the cap is 2"):
        safety.require_ids(["a", "b", "c"], cap=2)


@pytest.mark.parametrize("name", ["a.pdf", "sub/dir/a.pdf", "./a.pdf"])
def test_download_path_accepts_relative_names(settings: Settings, name: str) -> None:
    path = safety.download_path(settings, name)
    assert settings.downloads_dir.resolve() in path.parents


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        ("", "file name is required"),
        ("/etc/passwd", "not a full path"),
        ("../x", "escapes"),
        ("a/../../x", "escapes"),
        (".", "directory itself"),
    ],
)
def test_download_path_rejects(settings: Settings, name: str, reason: str) -> None:
    with pytest.raises(WxGmailError, match=reason):
        safety.download_path(settings, name)


def test_download_path_rejects_symlink_escape(
    settings: Settings, tmp_path: Path
) -> None:
    settings.downloads_dir.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (settings.downloads_dir / "link").symlink_to(outside)
    with pytest.raises(WxGmailError, match="escapes"):
        safety.download_path(settings, "link/x.pdf")


def test_outbox_path_requires_existing_file(settings: Settings) -> None:
    settings.outbox_dir.mkdir(parents=True)
    with pytest.raises(WxGmailError, match="not a file"):
        safety.outbox_path(settings, "missing.txt")
    (settings.outbox_dir / "a.txt").write_text("x")
    assert safety.outbox_path(settings, "a.txt").read_text() == "x"
    with pytest.raises(WxGmailError, match="escapes"):
        safety.outbox_path(settings, "../a.txt")
