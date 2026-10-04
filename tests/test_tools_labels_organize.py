from __future__ import annotations

from typing import Any

from wx_gmail_mcp.config import Settings

from .conftest import LABELS, call, tool_server
from .fake_gmail import FakeGmail


def _fake(**responses: Any) -> FakeGmail:
    base: dict[str, Any] = {"users.labels.list": {"labels": LABELS}}
    base.update(responses)
    return FakeGmail(base)


def test_list_labels_sorted_by_type_then_name(settings: Settings) -> None:
    fake = _fake()
    text = call(tool_server(settings, fake), "list_labels", account="work")
    assert text.split("\n") == [
        "INBOX: INBOX [system]",
        "STARRED: STARRED [system]",
        "UNREAD: UNREAD [system]",
        "Label_1: wx-test [user]",
        "Label_2: wx-test/sub [user]",
    ]
    assert fake.calls_to("users.labels.get") == []


def test_list_labels_with_counts_calls_get_per_label(settings: Settings) -> None:
    def get(**kwargs: Any) -> dict[str, Any]:
        label = next(x for x in LABELS if x["id"] == kwargs["id"])
        return {**label, "messagesTotal": 7, "messagesUnread": 2, "threadsTotal": 5}

    fake = _fake(**{"users.labels.get": get})
    text = call(
        tool_server(settings, fake), "list_labels", account="work", include_counts=True
    )
    assert "Label_1: wx-test [user] messages=7 unread=2 threads=5" in text
    assert len(fake.calls_to("users.labels.get")) == len(LABELS)


def test_list_labels_empty(settings: Settings) -> None:
    fake = FakeGmail({"users.labels.list": {}})
    assert (
        call(tool_server(settings, fake), "list_labels", account="work") == "No labels."
    )


def test_modify_labels_resolves_names_and_batches(settings: Settings) -> None:
    fake = _fake()
    text = call(
        tool_server(settings, fake),
        "modify_labels",
        account="work",
        message_ids=["m1", "m2"],
        add=["wx-test", "STARRED"],
        remove=["inbox"],
    )
    assert text == "Updated 2 messages: added wx-test, STARRED; removed INBOX."
    (batch,) = fake.calls_to("users.messages.batchModify")
    assert batch["body"] == {
        "ids": ["m1", "m2"],
        "addLabelIds": ["Label_1", "STARRED"],
        "removeLabelIds": ["INBOX"],
    }


def test_modify_labels_validation(settings: Settings) -> None:
    fake = _fake()
    mcp = tool_server(settings, fake)
    assert call(mcp, "modify_labels", account="work", message_ids=["m1"]) == (
        "Error: Give at least one label to add or remove."
    )
    assert call(mcp, "modify_labels", account="work", message_ids=[], add=["x"]) == (
        "Error: message_ids must contain at least one id."
    )
    assert call(
        mcp, "modify_labels", account="work", message_ids=["m1"], add=["nope"]
    ) == ("Error: Unknown label 'nope'. Use list_labels to see names and ids.")
    too_many = [str(i) for i in range(1001)]
    text = call(
        mcp, "modify_labels", account="work", message_ids=too_many, add=["INBOX"]
    )
    assert text == "Error: message_ids holds 1001 ids; the cap is 1000."
    assert fake.calls_to("users.messages.batchModify") == []


def test_mark_read_unread_archive(settings: Settings) -> None:
    fake = _fake()
    mcp = tool_server(settings, fake)
    assert (
        call(mcp, "mark_read", account="work", message_ids=["m1"])
        == "Marked 1 message read."
    )
    assert call(mcp, "mark_unread", account="work", message_ids=["m1", "m2"]) == (
        "Marked 2 messages unread."
    )
    assert call(mcp, "archive", account="work", message_ids=["m1", " m2 "]) == (
        "Archived 2 messages."
    )
    bodies = [c["body"] for c in fake.calls_to("users.messages.batchModify")]
    assert bodies == [
        {"ids": ["m1"], "addLabelIds": [], "removeLabelIds": ["UNREAD"]},
        {"ids": ["m1", "m2"], "addLabelIds": ["UNREAD"], "removeLabelIds": []},
        {"ids": ["m1", "m2"], "addLabelIds": [], "removeLabelIds": ["INBOX"]},
    ]
    # No labels.list is needed for the fixed-label tools.
    assert fake.calls_to("users.labels.list") == []


def test_organize_tools_reject_empty_ids(settings: Settings) -> None:
    mcp = tool_server(settings, _fake())
    for name in ("mark_read", "mark_unread", "archive"):
        assert call(mcp, name, account="work", message_ids=[""]).startswith(
            "Error: message_ids must contain"
        )
