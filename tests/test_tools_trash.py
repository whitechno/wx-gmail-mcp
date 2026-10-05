from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httplib2
from googleapiclient.errors import HttpError

from wx_gmail_mcp.config import BASE_SCOPES, SCOPE_FULL
from wx_gmail_mcp.server import build_server

from .conftest import FakeRuntime, call, make_settings, tool_names, tool_server
from .fake_gmail import FakeGmail

FULL = (*BASE_SCOPES, SCOPE_FULL)


def _server(tmp_path: Path, fake: FakeGmail, scopes: tuple[str, ...] = FULL):
    s = make_settings(tmp_path, delete=True)
    return build_server(FakeRuntime(s, {"work": fake}, {"work": scopes}))


def _http_error(status: int, msg: str) -> HttpError:
    return HttpError(
        httplib2.Response({"status": status}),
        json.dumps({"error": {"message": msg}}).encode(),
    )


def test_trash_tools_register_only_with_delete_gate(tmp_path: Path) -> None:
    base = tool_names(tool_server(make_settings(tmp_path), FakeGmail()))
    assert not {"trash", "untrash"} & base
    gated = tool_names(_server(tmp_path, FakeGmail()))
    assert {"trash", "untrash"} <= gated


def test_trash_requires_full_scope(tmp_path: Path) -> None:
    fake = FakeGmail()
    mcp = _server(tmp_path, fake, BASE_SCOPES)
    for tool in ("trash", "untrash"):
        text = call(mcp, tool, account="work", ids=["m1"])
        assert text.startswith("Error: Account 'work' has not granted the full scope.")
        assert "WX_GMAIL_ALLOW_DELETE=true wx-gmail-mcp --auth work" in text
    assert fake.calls == []


def test_trash_messages_one_call_each(tmp_path: Path) -> None:
    fake = FakeGmail()
    text = call(_server(tmp_path, fake), "trash", account="work", ids=["m1", "m2"])
    assert text == "Trashed 2 messages."
    assert fake.calls_to("users.messages.trash") == [
        {"userId": "me", "id": "m1"},
        {"userId": "me", "id": "m2"},
    ]
    assert fake.calls_to("users.threads.trash") == []


def test_trash_threads(tmp_path: Path) -> None:
    fake = FakeGmail()
    mcp = _server(tmp_path, fake)
    text = call(mcp, "trash", account="work", ids=["t1"], kind="thread")
    assert text == "Trashed 1 thread."
    assert fake.calls_to("users.threads.trash") == [{"userId": "me", "id": "t1"}]
    assert fake.calls_to("users.messages.trash") == []


def test_untrash_messages_and_threads(tmp_path: Path) -> None:
    fake = FakeGmail()
    mcp = _server(tmp_path, fake)
    assert call(mcp, "untrash", account="work", ids=["m1"]) == "Untrashed 1 message."
    assert fake.calls_to("users.messages.untrash") == [{"userId": "me", "id": "m1"}]
    text = call(mcp, "untrash", account="work", ids=["t1", "t2"], kind="Thread")
    assert text == "Untrashed 2 threads."
    assert fake.calls_to("users.threads.untrash") == [
        {"userId": "me", "id": "t1"},
        {"userId": "me", "id": "t2"},
    ]


def test_trash_dedupes_and_trims_ids(tmp_path: Path) -> None:
    fake = FakeGmail()
    text = call(
        _server(tmp_path, fake), "trash", account="work", ids=[" m1", "m1", "", "m2 "]
    )
    assert text == "Trashed 2 messages."
    assert [kw["id"] for kw in fake.calls_to("users.messages.trash")] == ["m1", "m2"]


def test_trash_validation_before_any_call(tmp_path: Path) -> None:
    fake = FakeGmail()
    mcp = _server(tmp_path, fake)
    assert call(mcp, "trash", account="work", ids=[]) == (
        "Error: ids must contain at least one id."
    )
    assert call(mcp, "trash", account="work", ids=["m1"], kind="label") == (
        "Error: kind must be 'message' or 'thread', not 'label'."
    )
    too_many = [f"m{i}" for i in range(101)]
    assert call(mcp, "untrash", account="work", ids=too_many) == (
        "Error: ids holds 101 ids; the cap is 100."
    )
    assert fake.calls == []


def test_trash_failure_midway_keeps_the_count(tmp_path: Path) -> None:
    def trash(**kwargs: Any) -> dict[str, Any]:
        if kwargs["id"] == "m2":
            raise _http_error(404, "Requested entity was not found.")
        return {"id": kwargs["id"]}

    fake = FakeGmail({"users.messages.trash": trash})
    mcp = _server(tmp_path, fake)
    text = call(mcp, "trash", account="work", ids=["m1", "m2", "m3"])
    assert text == (
        "Trashed 1 of 3 messages before an error on message m2: "
        "HTTP 404: Requested entity was not found."
    )
    assert [kw["id"] for kw in fake.calls_to("users.messages.trash")] == ["m1", "m2"]


def test_trash_schema_is_flat(tmp_path: Path) -> None:
    import asyncio

    mcp = _server(tmp_path, FakeGmail())
    tools = {t.name: t for t in asyncio.run(mcp.list_tools())}
    for name in ("trash", "untrash"):
        props = tools[name].input_schema["properties"]
        assert set(props) == {"account", "ids", "kind"}
        assert props["ids"]["type"] == "array"
        assert props["ids"]["items"]["type"] == "string"
        assert props["kind"]["type"] == "string"
        assert props["kind"]["default"] == "message"
        assert set(tools[name].input_schema["required"]) == {"account", "ids"}
