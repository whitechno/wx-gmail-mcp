from __future__ import annotations

from typing import Any

import httplib2
from googleapiclient.errors import HttpError

from wx_gmail_mcp.config import Settings

from .conftest import LABELS, call, tool_server
from .fake_gmail import FakeGmail
from .test_bulk import get_by_id, paged_list


def _fake(ids: list[str], **responses: Any) -> FakeGmail:
    base: dict[str, Any] = {
        "users.labels.list": {"labels": LABELS},
        "users.messages.list": paged_list(ids),
        "users.messages.get": get_by_id,
    }
    base.update(responses)
    return FakeGmail(base)


# --- modify_by_query ----------------------------------------------------------


def test_modify_by_query_defaults_to_dry_run(settings: Settings) -> None:
    fake = _fake(["m1", "m2", "m3"])
    text = call(
        tool_server(settings, fake),
        "modify_by_query",
        account="work",
        query="from:a@example.com",
        add=["wx-test"],
        remove=["inbox"],
    )
    lines = text.split("\n")
    assert lines[0] == (
        "Dry run: 3 messages match 'from:a@example.com'. "
        "Would have added wx-test; removed INBOX."
    )
    assert lines[1] == "Sample:"
    assert lines[2].startswith("  [m1] ")
    assert lines[-1] == "Run again with dry_run=false to apply."
    assert fake.calls_to("users.messages.batchModify") == []
    (list_call,) = fake.calls_to("users.messages.list")
    assert list_call["maxResults"] == 500  # limit 5000 -> page cap


def test_modify_by_query_applies_with_dry_run_false(settings: Settings) -> None:
    fake = _fake(["m1", "m2"])
    text = call(
        tool_server(settings, fake),
        "modify_by_query",
        account="work",
        query="x",
        add=["STARRED"],
        dry_run=False,
        limit=50,
    )
    assert text.startswith("Modified 2 messages matching 'x': added STARRED.")
    (batch,) = fake.calls_to("users.messages.batchModify")
    assert batch["body"] == {
        "ids": ["m1", "m2"],
        "addLabelIds": ["STARRED"],
        "removeLabelIds": [],
    }
    assert fake.calls_to("users.messages.list")[0]["maxResults"] == 51


def test_modify_by_query_validation(settings: Settings) -> None:
    fake = _fake(["m1"])
    mcp = tool_server(settings, fake)
    assert call(mcp, "modify_by_query", account="work", query="x") == (
        "Error: Give at least one label in `add` or `remove`."
    )
    assert call(mcp, "modify_by_query", account="work", query="x", add=["TRASH"]) == (
        "Error: modify_by_query does not add TRASH: that makes mail disappear. "
        "Use the trash tools, which register only with WX_GMAIL_ALLOW_DELETE=true."
    )
    assert call(mcp, "modify_by_query", account="work", query="", add=["INBOX"]) == (
        "Error: query is required."
    )
    assert call(
        mcp, "modify_by_query", account="work", query="x", add=["INBOX"], limit=0
    ) == ("Error: limit must be between 1 and 100000.")
    assert call(
        mcp, "modify_by_query", account="work", query="x", add=["nope"]
    ).startswith("Error: Unknown label 'nope'")
    assert fake.calls_to("users.messages.list") == []
    assert fake.calls_to("users.messages.batchModify") == []


def test_modify_by_query_over_limit(settings: Settings) -> None:
    fake = _fake(["m1", "m2", "m3"])
    text = call(
        tool_server(settings, fake),
        "modify_by_query",
        account="work",
        query="x",
        add=["INBOX"],
        dry_run=False,
        limit=2,
    )
    assert text == (
        "Error: More than 2 messages match 'x'. Narrow the query or raise limit "
        "(at most 100000)."
    )
    assert fake.calls_to("users.messages.batchModify") == []


def test_modify_by_query_no_matches(settings: Settings) -> None:
    fake = _fake([])
    text = call(
        tool_server(settings, fake),
        "modify_by_query",
        account="work",
        query="x",
        add=["INBOX"],
        dry_run=False,
    )
    assert text == "No messages match 'x'. Nothing to do."


# --- modify_thread_labels -----------------------------------------------------


def test_modify_thread_labels_one_call_per_thread(settings: Settings) -> None:
    fake = _fake([])
    text = call(
        tool_server(settings, fake),
        "modify_thread_labels",
        account="work",
        thread_ids=["t1", " t2 "],
        add=["wx-test/sub"],
        remove=["UNREAD", "inbox"],
    )
    assert text == "Updated 2 threads: added wx-test/sub; removed UNREAD, INBOX."
    assert fake.calls_to("users.threads.modify") == [
        {
            "userId": "me",
            "id": "t1",
            "body": {"addLabelIds": ["Label_2"], "removeLabelIds": ["UNREAD", "INBOX"]},
        },
        {
            "userId": "me",
            "id": "t2",
            "body": {"addLabelIds": ["Label_2"], "removeLabelIds": ["UNREAD", "INBOX"]},
        },
    ]


def test_modify_thread_labels_validation(settings: Settings) -> None:
    fake = _fake([])
    mcp = tool_server(settings, fake)
    assert call(mcp, "modify_thread_labels", account="work", thread_ids=[""]) == (
        "Error: thread_ids must contain at least one id."
    )
    assert call(mcp, "modify_thread_labels", account="work", thread_ids=["t1"]) == (
        "Error: Give at least one label in `add` or `remove`."
    )
    assert call(
        mcp, "modify_thread_labels", account="work", thread_ids=["t1"], add=["spam"]
    ).startswith("Error: modify_thread_labels does not add SPAM")
    too_many = [f"t{i}" for i in range(101)]
    assert call(
        mcp, "modify_thread_labels", account="work", thread_ids=too_many, add=["INBOX"]
    ) == ("Error: thread_ids holds 101 ids; the cap is 100.")
    assert fake.calls_to("users.threads.modify") == []


def test_modify_thread_labels_partial_failure(settings: Settings) -> None:
    calls = 0

    def flaky(**kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise HttpError(
                httplib2.Response({"status": 404}),
                b'{"error": {"message": "Requested entity was not found."}}',
            )
        return {}

    fake = _fake([], **{"users.threads.modify": flaky})
    text = call(
        tool_server(settings, fake),
        "modify_thread_labels",
        account="work",
        thread_ids=["t1", "t2", "t3"],
        add=["STARRED"],
    )
    assert text == (
        "Updated 1 of 3 threads before an error on thread t2: "
        "HTTP 404: Requested entity was not found."
    )
    assert len(fake.calls_to("users.threads.modify")) == 2


def test_modify_thread_labels_transport_failure(settings: Settings) -> None:
    def broken(**kwargs: Any) -> dict[str, Any]:
        raise ConnectionResetError("peer closed")

    fake = _fake([], **{"users.threads.modify": broken})
    text = call(
        tool_server(settings, fake),
        "modify_thread_labels",
        account="work",
        thread_ids=["t1"],
        add=["STARRED"],
    )
    assert text == (
        "Updated 0 of 1 thread before an error on thread t1: "
        "ConnectionResetError: peer closed"
    )
