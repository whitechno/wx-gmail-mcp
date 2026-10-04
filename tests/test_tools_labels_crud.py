from __future__ import annotations

import json
from typing import Any

import httplib2
import pytest
from googleapiclient.errors import HttpError

from wx_gmail_mcp.config import Settings
from wx_gmail_mcp.errors import WxGmailError
from wx_gmail_mcp.labels import LabelMap, check_label_name, label_body

from .conftest import LABELS, call, tool_server
from .fake_gmail import FakeGmail


def _echo_create(**kwargs: Any) -> dict[str, Any]:
    body = kwargs["body"]
    return {"id": f"id-{body['name']}", "type": "user", **body}


def _fake(**responses: Any) -> FakeGmail:
    base: dict[str, Any] = {
        "users.labels.list": {"labels": LABELS},
        "users.labels.create": _echo_create,
        "users.labels.patch": lambda **kw: {"id": kw["id"], **kw["body"]},
    }
    base.update(responses)
    return FakeGmail(base)


# --- helpers ------------------------------------------------------------------


def test_check_label_name() -> None:
    assert check_label_name("  Work/Clients ") == "Work/Clients"
    for bad, reason in [
        ("", "required"),
        ("   ", "required"),
        ("a//b", "empty segment"),
        ("/a", "empty segment"),
        ("a/", "empty segment"),
        ("inbox", "system label"),
        ("x" * 226, "longer than 225"),
    ]:
        with pytest.raises(WxGmailError, match=reason):
            check_label_name(bad)


def test_label_body_validation() -> None:
    assert label_body() == {}
    body = label_body(
        name="a",
        color_background="#16A765",
        color_text="#ffffff",
        label_list_visibility="labelHide",
        message_list_visibility="hide",
    )
    assert body == {
        "name": "a",
        "color": {"backgroundColor": "#16a765", "textColor": "#ffffff"},
        "labelListVisibility": "labelHide",
        "messageListVisibility": "hide",
    }
    with pytest.raises(WxGmailError, match="both color_background and color_text"):
        label_body(color_background="#16a765")
    with pytest.raises(WxGmailError, match="hex color"):
        label_body(color_background="green", color_text="#ffffff")
    with pytest.raises(WxGmailError, match="label_list_visibility must be one of"):
        label_body(label_list_visibility="show")
    with pytest.raises(WxGmailError, match="message_list_visibility must be one of"):
        label_body(message_list_visibility="labelShow")


def test_label_map_lookups() -> None:
    lm = LabelMap(LABELS)
    assert lm.find("WX-TEST") == LABELS[3]
    assert lm.find("nope") is None
    assert lm.missing_ancestors("wx-test/sub/deep") == []
    assert lm.missing_ancestors("proj/a/b") == ["proj", "proj/a"]
    assert lm.missing_ancestors("flat") == []
    assert [x["name"] for x in lm.children("WX-test")] == ["wx-test/sub"]
    assert lm.children("wx-test/sub") == []
    assert lm.require_user_label("Label_2")["name"] == "wx-test/sub"
    for ref in ("INBOX", "inbox", "STARRED", "TRASH"):
        with pytest.raises(WxGmailError, match="system label"):
            lm.require_user_label(ref)
    with pytest.raises(WxGmailError, match="Unknown label"):
        lm.require_user_label("nope")


# --- create_label -------------------------------------------------------------


def test_create_label_simple(settings: Settings) -> None:
    fake = _fake()
    text = call(
        tool_server(settings, fake), "create_label", account="work", name="Receipts"
    )
    assert text == "Created label 'Receipts' (id id-Receipts)."
    assert fake.calls_to("users.labels.create") == [
        {"userId": "me", "body": {"name": "Receipts"}}
    ]


def test_create_label_creates_missing_parents_first(settings: Settings) -> None:
    fake = _fake()
    text = call(
        tool_server(settings, fake), "create_label", account="work", name="proj/a/b"
    )
    assert text == (
        "Created label 'proj/a/b' (id id-proj/a/b). Also created parent proj, proj/a."
    )
    # The label itself goes first, so a rejected label leaves no parents behind.
    names = [c["body"]["name"] for c in fake.calls_to("users.labels.create")]
    assert names == ["proj/a/b", "proj", "proj/a"]


def _http_error(status: int, msg: str) -> HttpError:
    return HttpError(
        httplib2.Response({"status": status}),
        json.dumps({"error": {"message": msg}}).encode(),
    )


def test_create_label_rejected_leaf_creates_no_parents(settings: Settings) -> None:
    def reject(**kwargs: Any) -> dict[str, Any]:
        raise _http_error(400, "Invalid label color")

    fake = _fake(**{"users.labels.create": reject})
    text = call(
        tool_server(settings, fake),
        "create_label",
        account="work",
        name="proj/a/b",
        color_background="#123456",
        color_text="#ffffff",
    )
    assert text == "Gmail API error: HTTP 400: Invalid label color"
    assert len(fake.calls_to("users.labels.create")) == 1


def test_create_label_reports_a_failed_parent(settings: Settings) -> None:
    def create(**kwargs: Any) -> dict[str, Any]:
        if kwargs["body"]["name"] == "proj/a":
            raise _http_error(500, "Backend Error")
        return _echo_create(**kwargs)

    fake = _fake(**{"users.labels.create": create})
    text = call(
        tool_server(settings, fake), "create_label", account="work", name="proj/a/b"
    )
    assert text == (
        "Created label 'proj/a/b' (id id-proj/a/b). Creating parent proj/a failed: "
        "HTTP 500: Backend Error. Created parent proj."
    )


def test_create_label_under_existing_parent_creates_only_child(
    settings: Settings,
) -> None:
    fake = _fake()
    text = call(
        tool_server(settings, fake), "create_label", account="work", name="wx-test/new"
    )
    assert text == "Created label 'wx-test/new' (id id-wx-test/new)."
    assert len(fake.calls_to("users.labels.create")) == 1


def test_create_label_passes_colors_and_visibility(settings: Settings) -> None:
    fake = _fake()
    call(
        tool_server(settings, fake),
        "create_label",
        account="work",
        name="Hot",
        color_background="#fb4c2f",
        color_text="#FFFFFF",
        label_list_visibility="labelShowIfUnread",
        message_list_visibility="hide",
    )
    (create,) = fake.calls_to("users.labels.create")
    assert create["body"] == {
        "name": "Hot",
        "color": {"backgroundColor": "#fb4c2f", "textColor": "#ffffff"},
        "labelListVisibility": "labelShowIfUnread",
        "messageListVisibility": "hide",
    }


def test_create_label_rejects_bad_input_without_calling_gmail(
    settings: Settings,
) -> None:
    fake = _fake()
    mcp = tool_server(settings, fake)
    assert call(mcp, "create_label", account="work", name="") == (
        "Error: Label name is required."
    )
    assert call(mcp, "create_label", account="work", name="Inbox") == (
        "Error: 'Inbox' is a system label name."
    )
    assert call(
        mcp, "create_label", account="work", name="x", color_text="#ffffff"
    ).startswith("Error: Give both color_background")
    assert fake.calls == []
    assert call(mcp, "create_label", account="work", name="WX-Test") == (
        "Error: Label 'wx-test' already exists (id Label_1)."
    )
    assert fake.calls_to("users.labels.create") == []


# --- update_label -------------------------------------------------------------


def test_update_label_renames_by_name(settings: Settings) -> None:
    fake = _fake()
    text = call(
        tool_server(settings, fake),
        "update_label",
        account="work",
        label="wx-test/sub",
        new_name="wx-test/renamed",
    )
    assert text == "Updated label 'wx-test/sub' (id Label_2): name 'wx-test/renamed'."
    assert fake.calls_to("users.labels.patch") == [
        {"userId": "me", "id": "Label_2", "body": {"name": "wx-test/renamed"}}
    ]
    assert fake.calls_to("users.labels.create") == []


def test_update_label_move_creates_new_parents(settings: Settings) -> None:
    fake = _fake()
    text = call(
        tool_server(settings, fake),
        "update_label",
        account="work",
        label="Label_2",
        new_name="archive/2026/sub",
    )
    assert text.endswith(
        "name 'archive/2026/sub'. Also created parent archive, archive/2026."
    )
    names = [c["body"]["name"] for c in fake.calls_to("users.labels.create")]
    assert names == ["archive", "archive/2026"]
    # The patch goes before the parents are created, from a fresh snapshot.
    assert [p for p, _ in fake.calls if p != "users.labels.list"] == [
        "users.labels.patch",
        "users.labels.create",
        "users.labels.create",
    ]
    assert len(fake.calls_to("users.labels.list")) == 2


def _lists(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> FakeGmail:
    return _fake(**{"users.labels.list": [{"labels": before}, {"labels": after}]})


def test_update_label_rename_parent_reports_moved_and_left_children(
    settings: Settings,
) -> None:
    left = {"id": "Label_3", "name": "wx-test/other", "type": "user"}
    before = [*LABELS, left]
    after = [
        *LABELS[:3],
        {"id": "Label_1", "name": "done", "type": "user"},
        {"id": "Label_2", "name": "done/sub", "type": "user"},
        left,
    ]
    text = call(
        tool_server(settings, _lists(before, after)),
        "update_label",
        account="work",
        label="wx-test",
        new_name="done",
    )
    assert text == (
        "Updated label 'wx-test' (id Label_1): name 'done'. "
        "Nested labels moved with it: done/sub. "
        "Nested labels kept the old path and need their own rename: wx-test/other."
    )


def test_update_label_rename_parent_all_children_moved(settings: Settings) -> None:
    after = [
        *LABELS[:3],
        {"id": "Label_1", "name": "done", "type": "user"},
        {"id": "Label_2", "name": "done/sub", "type": "user"},
    ]
    text = call(
        tool_server(settings, _lists(LABELS, after)),
        "update_label",
        account="work",
        label="Label_1",
        new_name="done",
    )
    assert text == (
        "Updated label 'wx-test' (id Label_1): name 'done'. "
        "Nested labels moved with it: done/sub."
    )


def test_update_label_move_under_own_old_path(settings: Settings) -> None:
    """A -> A/X: the parent A must be recreated, and A/X is not its own child."""
    after = [
        *LABELS[:3],
        {"id": "Label_1", "name": "wx-test/moved", "type": "user"},
        LABELS[4],
    ]
    fake = _lists(LABELS, after)
    text = call(
        tool_server(settings, fake),
        "update_label",
        account="work",
        label="wx-test",
        new_name="wx-test/moved",
    )
    assert text == (
        "Updated label 'wx-test' (id Label_1): name 'wx-test/moved'. "
        "Also created parent wx-test. "
        "Nested labels kept the old path and need their own rename: wx-test/sub."
    )
    assert [c["body"]["name"] for c in fake.calls_to("users.labels.create")] == [
        "wx-test"
    ]


def test_update_label_colors_and_visibility_by_id(settings: Settings) -> None:
    fake = _fake()
    text = call(
        tool_server(settings, fake),
        "update_label",
        account="work",
        label="Label_1",
        color_background="#16a765",
        color_text="#000000",
        label_list_visibility="labelHide",
        message_list_visibility="show",
    )
    assert text == (
        "Updated label 'wx-test' (id Label_1): color #000000 on #16a765, "
        "label list labelHide, message list show."
    )
    (patch,) = fake.calls_to("users.labels.patch")
    assert "name" not in patch["body"]
    assert patch["body"]["color"] == {
        "backgroundColor": "#16a765",
        "textColor": "#000000",
    }


def test_update_label_rename_to_same_name_is_allowed(settings: Settings) -> None:
    """Changing only the case of a label's own name is not a conflict."""
    fake = _fake()
    text = call(
        tool_server(settings, fake),
        "update_label",
        account="work",
        label="wx-test",
        new_name="WX-Test",
    )
    assert text == "Updated label 'wx-test' (id Label_1): name 'WX-Test'."
    # No second snapshot, no parents, no nested-label note.
    assert len(fake.calls_to("users.labels.list")) == 1
    assert fake.calls_to("users.labels.create") == []


def test_update_label_rejections(settings: Settings) -> None:
    fake = _fake()
    mcp = tool_server(settings, fake)
    assert call(mcp, "update_label", account="work", label="wx-test") == (
        "Error: Give a new_name, both colors, or a visibility."
    )
    assert call(mcp, "update_label", account="work", label="INBOX", new_name="x") == (
        "Error: 'INBOX' is a system label; only user labels can be created, "
        "changed or deleted."
    )
    assert call(
        mcp, "update_label", account="work", label="wx-test", new_name="wx-test/sub"
    ) == ("Error: Label 'wx-test/sub' already exists (id Label_2).")
    assert call(
        mcp, "update_label", account="work", label="nope", new_name="x"
    ).startswith("Error: Unknown label 'nope'")
    assert fake.calls_to("users.labels.patch") == []


# --- delete_label -------------------------------------------------------------


def test_delete_label_leaf(settings: Settings) -> None:
    fake = _fake()
    text = call(
        tool_server(settings, fake), "delete_label", account="work", label="wx-test/sub"
    )
    assert text == "Deleted label 'wx-test/sub' (id Label_2); no messages were removed."
    assert fake.calls_to("users.labels.delete") == [{"userId": "me", "id": "Label_2"}]
    # Only one labels.list: no children to re-check.
    assert len(fake.calls_to("users.labels.list")) == 1


def test_delete_label_parent_reports_surviving_children(settings: Settings) -> None:
    after = [x for x in LABELS if x["id"] != "Label_1"]
    fake = _fake(**{"users.labels.list": [{"labels": LABELS}, {"labels": after}]})
    text = call(
        tool_server(settings, fake), "delete_label", account="work", label="Label_1"
    )
    assert text == (
        "Deleted label 'wx-test' (id Label_1); no messages were removed. "
        "Nested labels still exist: wx-test/sub."
    )


def test_delete_label_parent_reports_cascade(settings: Settings) -> None:
    after = [x for x in LABELS if not str(x["name"]).startswith("wx-test")]
    fake = _fake(**{"users.labels.list": [{"labels": LABELS}, {"labels": after}]})
    text = call(
        tool_server(settings, fake), "delete_label", account="work", label="wx-test"
    )
    assert text.endswith("Its nested labels were deleted with it.")


def test_delete_label_refuses_system_and_unknown(settings: Settings) -> None:
    fake = _fake()
    mcp = tool_server(settings, fake)
    assert call(mcp, "delete_label", account="work", label="TRASH").startswith(
        "Error: 'TRASH' is a system label"
    )
    assert call(mcp, "delete_label", account="work", label="Label_99").startswith(
        "Error: Unknown label"
    )
    assert fake.calls_to("users.labels.delete") == []
