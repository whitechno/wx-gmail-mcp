from __future__ import annotations

from pathlib import Path
from typing import Any

import httplib2
from googleapiclient.errors import HttpError

from wx_gmail_mcp.config import BASE_SCOPES

from .conftest import LABELS, call
from .fake_gmail import FakeGmail
from .test_bulk import get_by_id, paged_list
from .test_tools_filters import FILTER_A, FILTER_B, filters_server

CREATED = {"id": "ANe1Bmj-new", "criteria": {}, "action": {}}
FILTER_A_TEXT = (
    "ANe1Bmj-a\n"
    '  match: from "news@example.com", has attachment\n'
    "  query: from:(news@example.com) has:attachment\n"
    "  do: add wx-test; remove INBOX, UNREAD"
)


def _get(**kwargs: Any) -> dict[str, Any]:
    by_id = {FILTER_A["id"]: FILTER_A, FILTER_B["id"]: FILTER_B}
    if kwargs["id"] not in by_id:
        raise HttpError(
            httplib2.Response({"status": 404}),
            b'{"error": {"message": "Requested entity was not found."}}',
        )
    return by_id[kwargs["id"]]


def _fake(ids: list[str] | None = None, /, **responses: Any) -> FakeGmail:
    base: dict[str, Any] = {
        "users.labels.list": {"labels": LABELS},
        "users.settings.filters.get": _get,
        "users.settings.filters.create": CREATED,
        "users.messages.list": paged_list(ids or []),
        "users.messages.get": get_by_id,
    }
    base.update(responses)
    return FakeGmail(base)


def _paths(fake: FakeGmail, *prefixes: str) -> list[str]:
    return [p for p, _ in fake.calls if p.startswith(prefixes)]


# --- delete_filter --------------------------------------------------------------


def test_delete_filter_shows_each_filter_before_deleting(tmp_path: Path) -> None:
    fake = _fake()
    text = call(
        filters_server(tmp_path, fake),
        "delete_filter",
        account="work",
        filter_ids=[" ANe1Bmj-a ", "ANe1Bmj-b"],
    )
    assert text.startswith("Deleted 2 filters:\n" + FILTER_A_TEXT + "\nANe1Bmj-b\n")
    assert _paths(fake, "users.settings") == [
        "users.settings.filters.get",
        "users.settings.filters.delete",
        "users.settings.filters.get",
        "users.settings.filters.delete",
    ]
    assert [c["id"] for c in fake.calls_to("users.settings.filters.delete")] == [
        "ANe1Bmj-a",
        "ANe1Bmj-b",
    ]


def test_delete_filter_stops_at_the_first_error(tmp_path: Path) -> None:
    fake = _fake()
    text = call(
        filters_server(tmp_path, fake),
        "delete_filter",
        account="work",
        filter_ids=["ANe1Bmj-a", "nope", "ANe1Bmj-b"],
    )
    assert text == (
        "Deleted 1 of 3 filters before an error on filter nope: "
        "HTTP 404: Requested entity was not found.\n" + FILTER_A_TEXT
    )
    assert [c["id"] for c in fake.calls_to("users.settings.filters.delete")] == [
        "ANe1Bmj-a"
    ]


def test_delete_filter_validation_and_scope(tmp_path: Path) -> None:
    fake = _fake()
    mcp = filters_server(tmp_path, fake)
    assert call(mcp, "delete_filter", account="work", filter_ids=[" "]) == (
        "Error: filter_ids must contain at least one id."
    )
    too_many = [f"f{i}" for i in range(101)]
    assert call(mcp, "delete_filter", account="work", filter_ids=too_many) == (
        "Error: filter_ids holds 101 ids; the cap is 100."
    )
    assert fake.calls == []
    mcp = filters_server(tmp_path, fake, scopes=BASE_SCOPES)
    assert call(mcp, "delete_filter", account="work", filter_ids=["f1"]).startswith(
        "Error: Account 'work' has not granted the settings.basic scope."
    )
    assert fake.calls == []


# --- replace_filter -------------------------------------------------------------

NEW: dict[str, Any] = {
    "from_": "news@example.com",
    "add_labels": ["wx-test/sub"],
    "skip_inbox": True,
}


def test_replace_filter_dry_run_shows_both(tmp_path: Path) -> None:
    fake = _fake(["m1"])
    text = call(
        filters_server(tmp_path, fake),
        "replace_filter",
        account="work",
        filter_id="ANe1Bmj-a",
        **NEW,
        apply=True,
    )
    assert text == (
        "Dry run: replace the filter.\n"
        "Current:\n"
        '  match: from "news@example.com", has attachment\n'
        "  query: from:(news@example.com) has:attachment\n"
        "  do: add wx-test; remove INBOX, UNREAD\n"
        "New:\n"
        '  match: from "news@example.com"\n'
        "  query: from:(news@example.com)\n"
        "  do: add wx-test/sub; remove INBOX\n"
        "Existing mail: 1 message matches 'from:(news@example.com)'.\n"
        "Sample:\n"
        "  [m1] Fri, 02 Oct 2026 10:00:00 +0000 | Sender <sender@example.com> | "
        "subj m1\n"
        "Run again with dry_run=false to replace the filter and apply it to that "
        "message."
    )
    assert _paths(fake, "users.settings") == ["users.settings.filters.get"]
    assert fake.calls_to("users.messages.batchModify") == []


def test_replace_filter_creates_then_deletes_then_applies(tmp_path: Path) -> None:
    fake = _fake(["m1", "m2"])
    text = call(
        filters_server(tmp_path, fake),
        "replace_filter",
        account="work",
        filter_id="ANe1Bmj-a",
        **NEW,
        apply=True,
        dry_run=False,
    )
    assert text.startswith(
        "Replaced filter ANe1Bmj-a with ANe1Bmj-new.\n"
        '  match: from "news@example.com"\n'
        "  query: from:(news@example.com)\n"
        "  do: add wx-test/sub; remove INBOX\n"
        "Existing mail: Modified 2 messages matching 'from:(news@example.com)': "
        "added wx-test/sub; removed INBOX.\n"
    )
    order = [p for p, _ in fake.calls if p != "users.messages.get"]
    assert order == [
        "users.labels.list",
        "users.settings.filters.get",
        "users.settings.filters.create",
        "users.settings.filters.delete",
        "users.messages.list",
        "users.messages.batchModify",
    ]
    (create,) = fake.calls_to("users.settings.filters.create")
    assert create["body"] == {
        "criteria": {"from": "news@example.com"},
        "action": {"addLabelIds": ["Label_2"], "removeLabelIds": ["INBOX"]},
    }
    assert fake.calls_to("users.settings.filters.delete") == [
        {"userId": "me", "id": "ANe1Bmj-a"}
    ]


def test_replace_filter_without_apply_touches_no_mail(tmp_path: Path) -> None:
    fake = _fake(["m1"])
    text = call(
        filters_server(tmp_path, fake),
        "replace_filter",
        account="work",
        filter_id="ANe1Bmj-b",
        **NEW,
        dry_run=False,
    )
    assert text == (
        "Replaced filter ANe1Bmj-b with ANe1Bmj-new.\n"
        '  match: from "news@example.com"\n'
        "  query: from:(news@example.com)\n"
        "  do: add wx-test/sub; remove INBOX"
    )
    assert fake.calls_to("users.messages.list") == []


def test_replace_filter_missing_old_filter_creates_nothing(tmp_path: Path) -> None:
    fake = _fake()
    text = call(
        filters_server(tmp_path, fake),
        "replace_filter",
        account="work",
        filter_id="nope",
        **NEW,
        dry_run=False,
    )
    assert text == "Gmail API error: HTTP 404: Requested entity was not found."
    assert fake.calls_to("users.settings.filters.create") == []
    assert fake.calls_to("users.settings.filters.delete") == []


def test_replace_filter_validates_the_new_filter_first(tmp_path: Path) -> None:
    fake = _fake()
    mcp = filters_server(tmp_path, fake)
    assert call(mcp, "replace_filter", account="work", filter_id="", **NEW) == (
        "Error: filter_id is required."
    )
    assert call(mcp, "replace_filter", account="work", filter_id="ANe1Bmj-a") == (
        "Error: Give at least one criterion: from_, to, subject, query, "
        "negated_query, has_attachment, exclude_chats or size."
    )
    assert call(
        mcp, "replace_filter", account="work", filter_id="ANe1Bmj-a", from_="x"
    ) == (
        "Error: Give at least one action: add_labels, remove_labels or a shortcut "
        "such as skip_inbox, mark_read, star or category."
    )
    assert call(
        mcp,
        "replace_filter",
        account="work",
        filter_id="ANe1Bmj-a",
        from_="x",
        delete=True,
    ).startswith("Error: delete=true adds TRASH")
    assert _paths(fake, "users.settings") == []


def test_replace_filter_delete_failure_reports_both_ids(tmp_path: Path) -> None:
    def broken(**kwargs: Any) -> dict[str, Any]:
        raise HttpError(
            httplib2.Response({"status": 500}), b'{"error": {"message": "Backend"}}'
        )

    fake = _fake(["m1"], **{"users.settings.filters.delete": broken})
    text = call(
        filters_server(tmp_path, fake),
        "replace_filter",
        account="work",
        filter_id="ANe1Bmj-a",
        **NEW,
        apply=True,
        dry_run=False,
    )
    assert text.startswith(
        "Created filter ANe1Bmj-new, but deleting filter ANe1Bmj-a failed: "
        "HTTP 500: Backend Both exist; delete_filter the old one.\n"
        '  match: from "news@example.com"\n'
    )
    # The apply still runs: the new filter exists and was asked for.
    assert "Existing mail: Modified 1 message matching" in text
    assert len(fake.calls_to("users.messages.batchModify")) == 1


def test_replace_filter_with_missing_labels(tmp_path: Path) -> None:
    fake = _fake(**{"users.labels.create": {"id": "Label_10", "name": "wx-test/new"}})
    text = call(
        filters_server(tmp_path, fake),
        "replace_filter",
        account="work",
        filter_id="ANe1Bmj-a",
        from_="news@example.com",
        add_labels=["wx-test/new"],
        create_missing_labels=True,
    )
    assert "New:\n" in text
    assert "  do: add wx-test/new\n" in text
    assert "Labels to create: wx-test/new.\n" in text
    assert fake.calls_to("users.labels.create") == []
