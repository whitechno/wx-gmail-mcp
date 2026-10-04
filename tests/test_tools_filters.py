from __future__ import annotations

from pathlib import Path
from typing import Any

import httplib2
from googleapiclient.errors import HttpError
from mcp.server.mcpserver import MCPServer

from wx_gmail_mcp import filters
from wx_gmail_mcp.config import BASE_SCOPES, SCOPE_FULL, SCOPE_SETTINGS_BASIC
from wx_gmail_mcp.labels import LabelMap
from wx_gmail_mcp.server import build_server

from .conftest import LABELS, FakeRuntime, call, make_settings, tool_names
from .fake_gmail import FakeGmail

SETTINGS_SCOPES = (*BASE_SCOPES, SCOPE_SETTINGS_BASIC)

FILTER_A: dict[str, Any] = {
    "id": "ANe1Bmj-a",
    "criteria": {"from": "news@example.com", "hasAttachment": True},
    "action": {"addLabelIds": ["Label_1"], "removeLabelIds": ["INBOX", "UNREAD"]},
}
FILTER_B: dict[str, Any] = {
    "id": "ANe1Bmj-b",
    "criteria": {
        "subject": "invoice",
        "negatedQuery": "paid",
        "size": 5 * 1024 * 1024,
        "sizeComparison": "larger",
    },
    "action": {"addLabelIds": ["Label_2", "STARRED"], "forward": "x@example.com"},
}


def filters_server(
    tmp_path: Path,
    fake: FakeGmail,
    scopes: tuple[str, ...] = SETTINGS_SCOPES,
    **gates: bool,
) -> MCPServer:
    settings = make_settings(tmp_path, settings=True, **gates)
    return build_server(FakeRuntime(settings, {"work": fake}, {"work": scopes}))


def _fake(**responses: Any) -> FakeGmail:
    base: dict[str, Any] = {"users.labels.list": {"labels": LABELS}}
    base.update(responses)
    return FakeGmail(base)


# --- rendering ------------------------------------------------------------------


def test_describe_criteria() -> None:
    assert filters.describe_criteria(FILTER_A["criteria"]) == (
        'from "news@example.com", has attachment'
    )
    assert filters.describe_criteria(FILTER_B["criteria"]) == (
        'subject "invoice", lacks words "paid", larger than 5M'
    )
    assert filters.describe_criteria(
        {"to": "me@example.com", "query": "is:unread", "excludeChats": True}
    ) == ('to "me@example.com", has words "is:unread", no chats')
    assert filters.describe_criteria({}) == "(none)"


def test_describe_action_uses_label_names() -> None:
    labels = LabelMap(LABELS)
    assert filters.describe_action(FILTER_A["action"], labels) == (
        "add wx-test; remove INBOX, UNREAD"
    )
    assert filters.describe_action(FILTER_B["action"], labels) == (
        "add wx-test/sub, STARRED; forward to x@example.com"
    )
    # A label deleted after the filter was made still shows as its id.
    assert filters.describe_action({"addLabelIds": ["Label_9"]}, labels) == (
        "add Label_9"
    )
    assert filters.describe_action({}, labels) == "(none)"


def test_filter_text() -> None:
    assert filters.filter_text(FILTER_A, LabelMap(LABELS)) == (
        "ANe1Bmj-a\n"
        '  match: from "news@example.com", has attachment\n'
        "  query: from:(news@example.com) has:attachment\n"
        "  do: add wx-test; remove INBOX, UNREAD"
    )
    assert filters.filter_text({}, LabelMap(LABELS)) == (
        "(no id)\n  match: (none)\n  query: (none)\n  do: (none)"
    )


# --- registration and scope -----------------------------------------------------


def test_filter_tools_register_only_behind_the_settings_gate(
    tmp_path: Path,
) -> None:
    off = build_server(FakeRuntime(make_settings(tmp_path), {"work": FakeGmail()}))
    assert {"list_filters", "get_filter"} & tool_names(off) == set()
    on = filters_server(tmp_path, FakeGmail())
    assert {"list_filters", "get_filter"} <= tool_names(on)


def test_filter_tools_require_the_settings_scope(tmp_path: Path) -> None:
    fake = _fake()
    # The full mail scope does not cover the settings endpoints.
    mcp = filters_server(tmp_path, fake, scopes=(*BASE_SCOPES, SCOPE_FULL))
    text = call(mcp, "list_filters", account="work")
    assert text.startswith(
        "Error: Account 'work' has not granted the settings.basic scope. "
        "Set WX_GMAIL_ALLOW_SETTINGS=true and re-authorize with: "
    )
    assert "--auth work" in text
    assert call(mcp, "get_filter", account="work", filter_id="f1").startswith(
        "Error: Account 'work' has not granted the settings.basic scope."
    )
    assert fake.calls == []


# --- list_filters ---------------------------------------------------------------


def test_list_filters(tmp_path: Path) -> None:
    fake = _fake(**{"users.settings.filters.list": {"filter": [FILTER_A, FILTER_B]}})
    text = call(filters_server(tmp_path, fake), "list_filters", account="work")
    assert text == (
        "2 filters:\n"
        "ANe1Bmj-a\n"
        '  match: from "news@example.com", has attachment\n'
        "  query: from:(news@example.com) has:attachment\n"
        "  do: add wx-test; remove INBOX, UNREAD\n"
        "ANe1Bmj-b\n"
        '  match: subject "invoice", lacks words "paid", larger than 5M\n'
        "  query: subject:(invoice) -{paid} larger:5M\n"
        "  do: add wx-test/sub, STARRED; forward to x@example.com"
    )
    assert fake.calls_to("users.settings.filters.list") == [{"userId": "me"}]
    assert len(fake.calls_to("users.labels.list")) == 1


def test_list_filters_singular_and_empty(tmp_path: Path) -> None:
    fake = _fake(**{"users.settings.filters.list": {"filter": [FILTER_A]}})
    text = call(filters_server(tmp_path, fake), "list_filters", account="work")
    assert text.startswith("1 filter:\nANe1Bmj-a\n")
    fake = _fake(**{"users.settings.filters.list": {}})
    text = call(filters_server(tmp_path, fake), "list_filters", account="work")
    assert text == "No filters."
    assert fake.calls_to("users.labels.list") == []  # no names needed


# --- get_filter -----------------------------------------------------------------


def test_get_filter(tmp_path: Path) -> None:
    fake = _fake(**{"users.settings.filters.get": FILTER_B})
    text = call(
        filters_server(tmp_path, fake),
        "get_filter",
        account="work",
        filter_id=" ANe1Bmj-b ",
    )
    assert text == (
        "ANe1Bmj-b\n"
        '  match: subject "invoice", lacks words "paid", larger than 5M\n'
        "  query: subject:(invoice) -{paid} larger:5M\n"
        "  do: add wx-test/sub, STARRED; forward to x@example.com"
    )
    assert fake.calls_to("users.settings.filters.get") == [
        {"userId": "me", "id": "ANe1Bmj-b"}
    ]


def test_get_filter_validation_and_api_error(tmp_path: Path) -> None:
    def missing(**kwargs: Any) -> dict[str, Any]:
        raise HttpError(
            httplib2.Response({"status": 404}),
            b'{"error": {"message": "Filter not found"}}',
        )

    fake = _fake(**{"users.settings.filters.get": missing})
    mcp = filters_server(tmp_path, fake)
    assert call(mcp, "get_filter", account="work", filter_id="  ") == (
        "Error: filter_id is required."
    )
    assert fake.calls == []
    assert call(mcp, "get_filter", account="work", filter_id="nope") == (
        "Gmail API error: HTTP 404: Filter not found"
    )
