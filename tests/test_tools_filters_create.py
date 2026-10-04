from __future__ import annotations

from pathlib import Path
from typing import Any

import httplib2
from googleapiclient.errors import HttpError

from wx_gmail_mcp.config import BASE_SCOPES, SCOPE_FULL, SCOPE_SETTINGS_BASIC

from .conftest import LABELS, call
from .fake_gmail import FakeGmail
from .test_bulk import get_by_id, paged_list
from .test_tools_filters import filters_server

CREATED = {"id": "ANe1Bmj-new", "criteria": {}, "action": {}}


def _fake(ids: list[str] | None = None, /, **responses: Any) -> FakeGmail:
    base: dict[str, Any] = {
        "users.labels.list": {"labels": LABELS},
        "users.settings.filters.create": CREATED,
        "users.messages.list": paged_list(ids or []),
        "users.messages.get": get_by_id,
    }
    base.update(responses)
    return FakeGmail(base)


def _writes(fake: FakeGmail) -> list[str]:
    return [
        p
        for p, _ in fake.calls
        if p
        in {
            "users.settings.filters.create",
            "users.labels.create",
            "users.messages.batchModify",
        }
    ]


# --- dry run (the default) ------------------------------------------------------


def test_create_filter_dry_run_by_default(tmp_path: Path) -> None:
    fake = _fake(["m1"])
    text = call(
        filters_server(tmp_path, fake),
        "create_filter",
        account="work",
        from_="news@example.com",
        add_labels=["wx-test"],
        skip_inbox=True,
    )
    assert text == (
        "Dry run: create the filter.\n"
        '  match: from "news@example.com"\n'
        "  query: from:(news@example.com)\n"
        "  do: add wx-test; remove INBOX\n"
        "Run again with dry_run=false to create the filter."
    )
    assert _writes(fake) == []
    assert fake.calls_to("users.messages.list") == []  # no apply: no search


def test_create_filter_dry_run_with_apply_counts_matches(tmp_path: Path) -> None:
    fake = _fake(["m1", "m2", "m3"])
    text = call(
        filters_server(tmp_path, fake),
        "create_filter",
        account="work",
        subject="digest",
        mark_read=True,
        apply=True,
        apply_limit=10,
    )
    lines = text.split("\n")
    assert lines[:4] == [
        "Dry run: create the filter.",
        '  match: subject "digest"',
        "  query: subject:(digest)",
        "  do: remove UNREAD",
    ]
    assert lines[4] == "Existing mail: 3 messages match 'subject:(digest)'."
    assert lines[5] == "Sample:"
    assert lines[6].startswith("  [m1] ")
    assert lines[-1] == (
        "Run again with dry_run=false to create the filter and apply it to them."
    )
    assert _writes(fake) == []
    (list_call,) = fake.calls_to("users.messages.list")
    assert (list_call["q"], list_call["maxResults"]) == ("subject:(digest)", 11)
    assert list_call["includeSpamTrash"] is False


def test_create_filter_dry_run_with_apply_one_or_no_match(tmp_path: Path) -> None:
    fake = _fake(["m1"])
    text = call(
        filters_server(tmp_path, fake),
        "create_filter",
        account="work",
        to="me@example.com",
        star=True,
        apply=True,
    )
    assert "Existing mail: 1 message matches 'to:(me@example.com)'." in text
    assert text.endswith(" and apply it to that message.")
    fake = _fake([])
    text = call(
        filters_server(tmp_path, fake),
        "create_filter",
        account="work",
        to="me@example.com",
        star=True,
        apply=True,
    )
    assert "Existing mail: nothing matches 'to:(me@example.com)'." in text
    assert text.endswith("Run again with dry_run=false to create the filter.")


def test_create_filter_dry_run_lists_labels_to_create(tmp_path: Path) -> None:
    fake = _fake()
    text = call(
        filters_server(tmp_path, fake),
        "create_filter",
        account="work",
        from_="a@example.com",
        add_labels=["wx-test/new", "wx-test"],
        create_missing_labels=True,
    )
    assert "  do: add wx-test, wx-test/new\n" in text
    assert "Labels to create: wx-test/new.\n" in text
    assert _writes(fake) == []


# --- real run -------------------------------------------------------------------


def test_create_filter_creates_without_apply(tmp_path: Path) -> None:
    fake = _fake(["m1"])
    text = call(
        filters_server(tmp_path, fake),
        "create_filter",
        account="work",
        from_="news@example.com",
        has_attachment=True,
        size=5 * 1024 * 1024,
        size_comparison="larger",
        add_labels=["wx-test/sub"],
        skip_inbox=True,
        category="updates",
        dry_run=False,
    )
    assert text == (
        "Created filter ANe1Bmj-new.\n"
        '  match: from "news@example.com", has attachment, larger than 5M\n'
        "  query: from:(news@example.com) has:attachment larger:5M\n"
        "  do: add wx-test/sub, CATEGORY_UPDATES; remove INBOX"
    )
    assert fake.calls_to("users.settings.filters.create") == [
        {
            "userId": "me",
            "body": {
                "criteria": {
                    "from": "news@example.com",
                    "hasAttachment": True,
                    "size": 5 * 1024 * 1024,
                    "sizeComparison": "larger",
                },
                "action": {
                    "addLabelIds": ["Label_2", "CATEGORY_UPDATES"],
                    "removeLabelIds": ["INBOX"],
                },
            },
        }
    ]
    assert fake.calls_to("users.messages.list") == []
    assert fake.calls_to("users.messages.batchModify") == []


def test_create_filter_with_apply_creates_first_then_relabels(tmp_path: Path) -> None:
    fake = _fake(["m1", "m2"])
    text = call(
        filters_server(tmp_path, fake),
        "create_filter",
        account="work",
        query="list:dev@example.com",
        add_labels=["wx-test"],
        mark_read=True,
        apply=True,
        dry_run=False,
    )
    assert text == (
        "Created filter ANe1Bmj-new.\n"
        '  match: has words "list:dev@example.com"\n'
        "  query: list:dev@example.com\n"
        "  do: add wx-test; remove UNREAD\n"
        "Existing mail: Modified 2 messages matching 'list:dev@example.com': "
        "added wx-test; removed UNREAD.\n"
        "Sample:\n"
        "  [m1] Fri, 02 Oct 2026 10:00:00 +0000 | Sender <sender@example.com> | "
        "subj m1\n"
        "  [m2] Fri, 02 Oct 2026 10:00:00 +0000 | Sender <sender@example.com> | "
        "subj m2"
    )
    order = [p for p, _ in fake.calls if p != "users.messages.get"]
    assert order == [
        "users.labels.list",
        "users.settings.filters.create",
        "users.messages.list",
        "users.messages.batchModify",
    ]
    (batch,) = fake.calls_to("users.messages.batchModify")
    assert batch["body"] == {
        "ids": ["m1", "m2"],
        "addLabelIds": ["Label_1"],
        "removeLabelIds": ["UNREAD"],
    }


def test_create_filter_apply_partial_failure_keeps_the_filter(tmp_path: Path) -> None:
    def broken(**kwargs: Any) -> dict[str, Any]:
        raise HttpError(
            httplib2.Response({"status": 500}), b'{"error": {"message": "Backend"}}'
        )

    fake = _fake(["m1"], **{"users.messages.batchModify": broken})
    text = call(
        filters_server(tmp_path, fake),
        "create_filter",
        account="work",
        from_="a@example.com",
        star=True,
        apply=True,
        dry_run=False,
    )
    assert text.startswith("Created filter ANe1Bmj-new.\n")
    assert (
        "Existing mail: Modified 0 of 1 message matching 'from:(a@example.com)' "
        "before an error: HTTP 500: Backend"
    ) in text
    assert text.endswith(
        "Finish with modify_by_query on the query above; messages already "
        "modified are unaffected."
    )


def test_create_filter_creates_missing_labels_before_the_filter(tmp_path: Path) -> None:
    created_labels: list[dict[str, Any]] = []
    snapshots = [list(LABELS)]

    def create_label(**kwargs: Any) -> dict[str, Any]:
        label = {
            "id": f"Label_{10 + len(created_labels)}",
            "name": kwargs["body"]["name"],
            "type": "user",
        }
        created_labels.append(label)
        snapshots.append(snapshots[-1] + [label])
        return label

    fake = _fake(
        **{
            "users.labels.create": create_label,
            "users.labels.list": lambda **kw: {"labels": snapshots[-1]},
        }
    )
    text = call(
        filters_server(tmp_path, fake),
        "create_filter",
        account="work",
        from_="a@example.com",
        add_labels=["wx-test/new", "fresh/leaf"],
        create_missing_labels=True,
        dry_run=False,
    )
    assert text == (
        "Created filter ANe1Bmj-new.\n"
        '  match: from "a@example.com"\n'
        "  query: from:(a@example.com)\n"
        "  do: add wx-test/new, fresh/leaf\n"
        "Created labels: wx-test/new (Label_10), fresh/leaf (Label_11). "
        "Also created parent fresh."
    )
    # The leaf first, then its missing parent; the existing wx-test is reused.
    assert [c["body"]["name"] for c in fake.calls_to("users.labels.create")] == [
        "wx-test/new",
        "fresh/leaf",
        "fresh",
    ]
    (create,) = fake.calls_to("users.settings.filters.create")
    assert create["body"]["action"]["addLabelIds"] == ["Label_10", "Label_11"]
    order = [
        p
        for p, _ in fake.calls
        if p in {"users.labels.create", "users.settings.filters.create"}
    ]
    assert order[-1] == "users.settings.filters.create"


# --- validation and gates -------------------------------------------------------


def test_create_filter_validation_calls_nothing(tmp_path: Path) -> None:
    fake = _fake()
    mcp = filters_server(tmp_path, fake)
    base: dict[str, Any] = {"account": "work", "from_": "a@example.com"}
    assert call(mcp, "create_filter", account="work", star=True) == (
        "Error: Give at least one criterion: from_, to, subject, query, "
        "negated_query, has_attachment, exclude_chats or size."
    )
    assert call(mcp, "create_filter", **base) == (
        "Error: Give at least one action: add_labels, remove_labels or a shortcut "
        "such as skip_inbox, mark_read, star or category."
    )
    assert call(mcp, "create_filter", **base, add_labels=["nope"]) == (
        "Error: Unknown label 'nope'. Use list_labels to see names and ids, or "
        "pass create_missing_labels=true with a name."
    )
    assert call(mcp, "create_filter", **base, add_labels=["TRASH"]) == (
        "Error: A filter cannot add TRASH: pass delete=true (needs "
        "WX_GMAIL_ALLOW_DELETE=true)."
    )
    assert call(mcp, "create_filter", **base, star=True, apply=True, apply_limit=0) == (
        "Error: apply_limit must be between 1 and 100000."
    )
    assert call(mcp, "create_filter", **base, size=1, size_comparison="huge") == (
        "Error: size_comparison must be one of: larger, smaller."
    )
    assert _writes(fake) == []
    assert fake.calls_to("users.messages.list") == []


def test_create_filter_over_apply_limit_names_the_parameter(tmp_path: Path) -> None:
    fake = _fake(["m1", "m2", "m3"])
    text = call(
        filters_server(tmp_path, fake),
        "create_filter",
        account="work",
        from_="a@example.com",
        star=True,
        apply=True,
        apply_limit=2,
    )
    assert text == (
        "Error: More than 2 messages match 'from:(a@example.com)'. Narrow the "
        "query or raise apply_limit (at most 100000)."
    )
    assert _writes(fake) == []


def test_create_filter_apply_failure_after_creation_keeps_the_report(
    tmp_path: Path,
) -> None:
    """Over the limit on a real run: the filter exists and the text says so."""
    fake = _fake(["m1", "m2", "m3"])
    text = call(
        filters_server(tmp_path, fake),
        "create_filter",
        account="work",
        from_="a@example.com",
        star=True,
        apply=True,
        apply_limit=2,
        dry_run=False,
    )
    assert text == (
        "Created filter ANe1Bmj-new.\n"
        '  match: from "a@example.com"\n'
        "  query: from:(a@example.com)\n"
        "  do: add STARRED\n"
        "Existing mail was not changed: More than 2 messages match "
        "'from:(a@example.com)'. Narrow the query or raise apply_limit (at most "
        "100000). The filter exists, so do not create it again; relabel existing "
        "mail with modify_by_query on the query above (it has its own limit)."
    )
    assert _writes(fake) == ["users.settings.filters.create"]

    def broken(**kwargs: Any) -> dict[str, Any]:
        raise ConnectionResetError("peer closed")

    fake = _fake(["m1"], **{"users.messages.list": broken})
    text = call(
        filters_server(tmp_path, fake),
        "create_filter",
        account="work",
        from_="a@example.com",
        star=True,
        apply=True,
        dry_run=False,
    )
    assert text.startswith("Created filter ANe1Bmj-new.\n")
    assert (
        "Existing mail was not changed: ConnectionResetError: peer closed The "
        "filter exists"
    ) in text


def test_create_filter_failed_create_names_the_labels_made_for_it(
    tmp_path: Path,
) -> None:
    def refused(**kwargs: Any) -> dict[str, Any]:
        raise HttpError(
            httplib2.Response({"status": 400}),
            b'{"error": {"message": "Filter already exists"}}',
        )

    fake = _fake(
        **{
            "users.labels.create": {"id": "Label_10", "name": "wx-test/new"},
            "users.settings.filters.create": refused,
        }
    )
    text = call(
        filters_server(tmp_path, fake),
        "create_filter",
        account="work",
        from_="a@example.com",
        add_labels=["wx-test/new"],
        create_missing_labels=True,
        dry_run=False,
    )
    assert text == (
        "Error: Creating the filter failed (HTTP 400: Filter already exists), "
        "after labels were made for it. Created labels: wx-test/new (Label_10). "
        "They remain; reuse or delete_label them."
    )
    # Without labels made, the plain API error comes through.
    fake = _fake(**{"users.settings.filters.create": refused})
    text = call(
        filters_server(tmp_path, fake),
        "create_filter",
        account="work",
        from_="a@example.com",
        star=True,
        dry_run=False,
    )
    assert text == "Gmail API error: HTTP 400: Filter already exists"


def test_create_filter_failed_label_names_the_labels_already_made(
    tmp_path: Path,
) -> None:
    calls = 0

    def second_fails(**kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise HttpError(
                httplib2.Response({"status": 403}),
                b'{"error": {"message": "Too many labels"}}',
            )
        return {"id": "Label_10", "name": kwargs["body"]["name"]}

    fake = _fake(**{"users.labels.create": second_fails})
    text = call(
        filters_server(tmp_path, fake),
        "create_filter",
        account="work",
        from_="a@example.com",
        add_labels=["wx-test/one", "wx-test/two"],
        create_missing_labels=True,
        dry_run=False,
    )
    assert text == (
        "Error: Creating label 'wx-test/two' failed (HTTP 403: Too many labels); "
        "no filter was created. Created labels: wx-test/one (Label_10). They "
        "remain."
    )
    assert fake.calls_to("users.settings.filters.create") == []
    # The first label failing: nothing to list.
    calls = 1
    fake = _fake(**{"users.labels.create": second_fails})
    text = call(
        filters_server(tmp_path, fake),
        "create_filter",
        account="work",
        from_="a@example.com",
        add_labels=["wx-test/one"],
        create_missing_labels=True,
        dry_run=False,
    )
    assert text == (
        "Error: Creating label 'wx-test/one' failed (HTTP 403: Too many labels); "
        "no filter was created."
    )


def test_create_filter_id_like_name_is_not_created(tmp_path: Path) -> None:
    fake = _fake()
    text = call(
        filters_server(tmp_path, fake),
        "create_filter",
        account="work",
        from_="a@example.com",
        add_labels=["Label_999"],
        create_missing_labels=True,
    )
    assert text.startswith("Error: Unknown label 'Label_999'.")
    assert _writes(fake) == []


def test_create_filter_delete_needs_the_delete_gate_and_scope(tmp_path: Path) -> None:
    args: dict[str, Any] = {
        "account": "work",
        "from_": "spammer@example.com",
        "delete": True,
        "dry_run": False,
    }
    fake = _fake()
    text = call(filters_server(tmp_path, fake), "create_filter", **args)
    assert text == (
        "Error: delete=true adds TRASH, which makes mail disappear; it is "
        "available only when the server runs with WX_GMAIL_ALLOW_DELETE=true."
    )
    assert fake.calls == []
    # Gate on, but the account did not grant the full scope.
    fake = _fake()
    text = call(filters_server(tmp_path, fake, delete=True), "create_filter", **args)
    assert text.startswith(
        "Error: Account 'work' has not granted the full scope. Set "
        "WX_GMAIL_ALLOW_DELETE=true and re-authorize with: "
    )
    assert fake.calls == []
    # Gate on and scope granted: TRASH is the action.
    fake = _fake()
    scopes = (*BASE_SCOPES, SCOPE_SETTINGS_BASIC, SCOPE_FULL)
    mcp = filters_server(tmp_path, fake, scopes=scopes, delete=True)
    text = call(mcp, "create_filter", **args)
    assert text.endswith("  do: add TRASH")
    (create,) = fake.calls_to("users.settings.filters.create")
    assert create["body"]["action"] == {"addLabelIds": ["TRASH"], "removeLabelIds": []}


def test_create_filter_delete_with_apply_trashes_only_when_both_are_on(
    tmp_path: Path,
) -> None:
    args: dict[str, Any] = {
        "account": "work",
        "from_": "spammer@example.com",
        "delete": True,
        "apply": True,
        "dry_run": False,
    }
    # Gate off: refused before any listing or write.
    fake = _fake(["m1"])
    text = call(filters_server(tmp_path, fake), "create_filter", **args)
    assert text.startswith("Error: delete=true adds TRASH")
    assert fake.calls == []
    # Gate on without the full scope: same.
    fake = _fake(["m1"])
    text = call(filters_server(tmp_path, fake, delete=True), "create_filter", **args)
    assert text.startswith("Error: Account 'work' has not granted the full scope.")
    assert fake.calls == []
    # Both on: the filter is created, then existing matches go to Trash.
    fake = _fake(["m1", "m2"])
    scopes = (*BASE_SCOPES, SCOPE_SETTINGS_BASIC, SCOPE_FULL)
    text = call(
        filters_server(tmp_path, fake, scopes=scopes, delete=True),
        "create_filter",
        **args,
    )
    assert text.startswith("Created filter ANe1Bmj-new.\n")
    assert (
        "Existing mail: Modified 2 messages matching 'from:(spammer@example.com)': "
        "added TRASH."
    ) in text
    assert _writes(fake) == [
        "users.settings.filters.create",
        "users.messages.batchModify",
    ]
    (batch,) = fake.calls_to("users.messages.batchModify")
    assert batch["body"] == {
        "ids": ["m1", "m2"],
        "addLabelIds": ["TRASH"],
        "removeLabelIds": [],
    }


def test_create_filter_delete_apply_failures_do_not_suggest_modify_by_query(
    tmp_path: Path,
) -> None:
    """modify_by_query refuses TRASH, so a delete filter's hint names trash."""
    args: dict[str, Any] = {
        "account": "work",
        "from_": "spammer@example.com",
        "delete": True,
        "apply": True,
        "dry_run": False,
    }
    scopes = (*BASE_SCOPES, SCOPE_SETTINGS_BASIC, SCOPE_FULL)

    def broken(**kwargs: Any) -> dict[str, Any]:
        raise HttpError(
            httplib2.Response({"status": 500}), b'{"error": {"message": "Backend"}}'
        )

    fake = _fake(["m1"], **{"users.messages.batchModify": broken})
    text = call(
        filters_server(tmp_path, fake, scopes=scopes, delete=True),
        "create_filter",
        **args,
    )
    assert text.startswith("Created filter ANe1Bmj-new.\n")
    assert text.endswith(
        "Finish with a trash tool on the remaining matches; messages already "
        "modified are unaffected."
    )
    assert "modify_by_query" not in text
    fake = _fake(["m1", "m2"])
    text = call(
        filters_server(tmp_path, fake, scopes=scopes, delete=True),
        "create_filter",
        **args,
        apply_limit=1,
    )
    assert text.endswith(
        "The filter exists, so do not create it again; trash existing matches "
        "separately (search the query above, then a trash tool, which needs "
        "WX_GMAIL_ALLOW_DELETE=true)."
    )
    assert "modify_by_query" not in text


def test_create_filter_requires_the_settings_scope(tmp_path: Path) -> None:
    fake = _fake()
    mcp = filters_server(tmp_path, fake, scopes=BASE_SCOPES)
    text = call(mcp, "create_filter", account="work", from_="a@example.com", star=True)
    assert text.startswith(
        "Error: Account 'work' has not granted the settings.basic scope."
    )
    assert fake.calls == []
