from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httplib2
from googleapiclient.errors import HttpError

from wx_gmail_mcp.config import BASE_SCOPES, SCOPE_FULL
from wx_gmail_mcp.server import build_server

from .conftest import FakeRuntime, call, make_settings, message, tool_names, tool_server
from .fake_gmail import FakeGmail

FULL = (*BASE_SCOPES, SCOPE_FULL)
TRASHED = ("TRASH", "Label_1")
HEADERS = {
    "userId": "me",
    "format": "metadata",
    "metadataHeaders": ["From", "Subject", "Date"],
}
DATE_FROM = "Fri, 02 Oct 2026 10:00:00 +0000 | From: Sender <sender@example.com>"
LINE_M1 = f"[m1] {DATE_FROM} | Subj: Test subject"


def _server(tmp_path: Path, fake: FakeGmail, scopes: tuple[str, ...] = FULL):
    s = make_settings(tmp_path, delete=True)
    return build_server(FakeRuntime(s, {"work": fake}, {"work": scopes}))


def _http_error(status: int, msg: str) -> HttpError:
    return HttpError(
        httplib2.Response({"status": status}),
        json.dumps({"error": {"message": msg}}).encode(),
    )


def _messages(**by_id: dict[str, Any]) -> FakeGmail:
    """A fake whose messages.get answers from ``by_id`` (404 otherwise)."""

    def get(**kwargs: Any) -> dict[str, Any]:
        if kwargs["id"] not in by_id:
            raise _http_error(404, "Requested entity was not found.")
        return by_id[kwargs["id"]]

    return FakeGmail({"users.messages.get": get})


def _threads(**by_id: dict[str, Any]) -> FakeGmail:
    def get(**kwargs: Any) -> dict[str, Any]:
        if kwargs["id"] not in by_id:
            raise _http_error(404, "Requested entity was not found.")
        return by_id[kwargs["id"]]

    return FakeGmail({"users.threads.get": get})


def test_delete_permanently_registers_only_with_delete_gate(tmp_path: Path) -> None:
    base = tool_names(tool_server(make_settings(tmp_path), FakeGmail()))
    assert "delete_permanently" not in base
    gated = tool_names(_server(tmp_path, FakeGmail()))
    assert "delete_permanently" in gated
    assert not {"empty_trash", "delete_by_query"} & gated


def test_delete_permanently_schema_has_no_query_form(tmp_path: Path) -> None:
    tools = {
        t.name: t for t in asyncio.run(_server(tmp_path, FakeGmail()).list_tools())
    }
    schema = tools["delete_permanently"].input_schema
    props = schema["properties"]
    assert set(props) == {"account", "ids", "kind", "require_trashed", "dry_run"}
    assert set(schema["required"]) == {"account", "ids"}
    assert props["ids"] == {**props["ids"], "type": "array"}
    assert props["ids"]["items"]["type"] == "string"
    assert (props["kind"]["type"], props["kind"]["default"]) == ("string", "message")
    for flag in ("require_trashed", "dry_run"):
        assert (props[flag]["type"], props[flag]["default"]) == ("boolean", True)


def test_delete_permanently_requires_full_scope(tmp_path: Path) -> None:
    fake = _messages(m1=message("m1", labels=TRASHED))
    text = call(
        _server(tmp_path, fake, BASE_SCOPES),
        "delete_permanently",
        account="work",
        ids=["m1"],
    )
    assert text.startswith("Error: Account 'work' has not granted the full scope.")
    assert "WX_GMAIL_ALLOW_DELETE=true wx-gmail-mcp --auth work" in text
    assert fake.calls == []


def test_dry_run_is_the_default_and_deletes_nothing(tmp_path: Path) -> None:
    fake = _messages(
        m1=message("m1", labels=TRASHED),
        m2=message("m2", labels=("TRASH",), headers={"Subject": "Second"}),
    )
    text = call(
        _server(tmp_path, fake), "delete_permanently", account="work", ids=["m1", "m2"]
    )
    assert text.splitlines() == [
        "Dry run: 2 messages would be permanently deleted. Run again with "
        "dry_run=false to delete; there is no undo.",
        LINE_M1,
        f"[m2] {DATE_FROM} | Subj: Second",
    ]
    assert fake.calls_to("users.messages.get") == [
        {**HEADERS, "id": "m1"},
        {**HEADERS, "id": "m2"},
    ]
    assert fake.calls_to("users.messages.batchDelete") == []


def test_delete_trashed_messages_with_audit_trail(tmp_path: Path) -> None:
    fake = _messages(
        m1=message("m1", labels=TRASHED), m2=message("m2", labels=("TRASH",))
    )
    text = call(
        _server(tmp_path, fake),
        "delete_permanently",
        account="work",
        ids=["m1", "m2", "m1"],
        dry_run=False,
    )
    lines = text.splitlines()
    assert lines[0] == "Permanently deleted 2 messages:"
    assert lines[1] == LINE_M1
    assert lines[2].startswith("[m2] ")
    assert fake.calls_to("users.messages.batchDelete") == [
        {"userId": "me", "body": {"ids": ["m1", "m2"]}}
    ]
    # The audit fetch happens before the delete.
    paths = [p for p, _ in fake.calls]
    assert paths.index("users.messages.batchDelete") > paths.index("users.messages.get")


def test_require_trashed_refuses_mail_outside_trash(tmp_path: Path) -> None:
    fake = _messages(
        m1=message("m1", labels=TRASHED),
        m2=message("m2", labels=("INBOX",)),
        m3=message("m3", labels=("SPAM",)),
    )
    mcp = _server(tmp_path, fake)
    for dry_run in (True, False):
        text = call(
            mcp,
            "delete_permanently",
            account="work",
            ids=["m1", "m2", "m3"],
            dry_run=dry_run,
        )
        assert text == (
            "Error: 2 messages are not in Trash: m2, m3. Trash them first, or pass "
            "require_trashed=false to delete them anyway. Nothing was deleted."
        )
    assert fake.calls_to("users.messages.batchDelete") == []
    one = call(mcp, "delete_permanently", account="work", ids=["m2"], dry_run=False)
    assert one == (
        "Error: 1 message is not in Trash: m2. Trash it first, or pass "
        "require_trashed=false to delete it anyway. Nothing was deleted."
    )


def test_require_trashed_false_deletes_mail_outside_trash(tmp_path: Path) -> None:
    fake = _messages(m2=message("m2", labels=("INBOX",)))
    text = call(
        _server(tmp_path, fake),
        "delete_permanently",
        account="work",
        ids=["m2"],
        require_trashed=False,
        dry_run=False,
    )
    assert text.startswith("Permanently deleted 1 message:\n[m2] ")
    assert fake.calls_to("users.messages.batchDelete") == [
        {"userId": "me", "body": {"ids": ["m2"]}}
    ]


def test_cap_is_100_ids_before_any_call(tmp_path: Path) -> None:
    fake = _messages(
        **{f"m{i}": message(f"m{i}", labels=("TRASH",)) for i in range(101)}
    )
    mcp = _server(tmp_path, fake)
    text = call(
        mcp, "delete_permanently", account="work", ids=[f"m{i}" for i in range(101)]
    )
    assert text == "Error: ids holds 101 ids; the cap is 100."
    assert call(mcp, "delete_permanently", account="work", ids=[]) == (
        "Error: ids must contain at least one id."
    )
    assert fake.calls == []
    ids = [f"m{i}" for i in range(100)]
    text = call(mcp, "delete_permanently", account="work", ids=ids, dry_run=False)
    assert text.startswith("Permanently deleted 100 messages:")
    (batch,) = fake.calls_to("users.messages.batchDelete")
    assert batch["body"]["ids"] == ids


def test_batch_delete_failure_keeps_the_audit_trail(tmp_path: Path) -> None:
    def fail(**kwargs: Any) -> dict[str, Any]:
        raise _http_error(500, "Backend Error")

    fake = _messages(m1=message("m1", labels=TRASHED))
    fake.responses["users.messages.batchDelete"] = fail
    text = call(
        _server(tmp_path, fake),
        "delete_permanently",
        account="work",
        ids=["m1"],
        dry_run=False,
    )
    assert text.splitlines() == [
        "Nothing was deleted: the delete of 1 message failed with "
        "HTTP 500: Backend Error. The items were:",
        LINE_M1,
    ]


def test_unknown_id_fails_before_any_delete(tmp_path: Path) -> None:
    fake = _messages(m1=message("m1", labels=TRASHED))
    text = call(
        _server(tmp_path, fake),
        "delete_permanently",
        account="work",
        ids=["m1", "nope"],
        dry_run=False,
    )
    assert text == "Gmail API error: HTTP 404: Requested entity was not found."
    assert fake.calls_to("users.messages.batchDelete") == []


def _thread(thread_id: str, *labels: tuple[str, ...]) -> dict[str, Any]:
    return {
        "id": thread_id,
        "messages": [
            message(f"{thread_id}m{i}", thread_id, lbls)
            for i, lbls in enumerate(labels, 1)
        ],
    }


def test_delete_threads_with_audit_trail(tmp_path: Path) -> None:
    fake = _threads(t1=_thread("t1", TRASHED, ("TRASH",)), t2=_thread("t2", ("TRASH",)))
    mcp = _server(tmp_path, fake)
    text = call(
        mcp, "delete_permanently", account="work", ids=["t1", "t2"], kind="thread"
    )
    assert text.splitlines()[:3] == [
        "Dry run: 2 threads would be permanently deleted. Run again with "
        "dry_run=false to delete; there is no undo.",
        "[thread t1] 2 messages",
        "  [t1m1] Fri, 02 Oct 2026 10:00:00 +0000 | From: Sender <sender@example.com>"
        " | Subj: Test subject",
    ]
    assert fake.calls_to("users.threads.get")[0] == {**HEADERS, "id": "t1"}
    assert fake.calls_to("users.threads.delete") == []
    text = call(
        mcp,
        "delete_permanently",
        account="work",
        ids=["t1", "t2"],
        kind="thread",
        dry_run=False,
    )
    lines = text.splitlines()
    assert lines[0] == "Permanently deleted 2 threads:"
    assert lines[1] == "[thread t1] 2 messages"
    assert lines[4] == "[thread t2] 1 message"
    assert len(lines) == 6
    assert fake.calls_to("users.threads.delete") == [
        {"userId": "me", "id": "t1"},
        {"userId": "me", "id": "t2"},
    ]
    assert fake.calls_to("users.messages.batchDelete") == []


def test_partially_trashed_thread_is_refused(tmp_path: Path) -> None:
    fake = _threads(
        t1=_thread("t1", ("TRASH",), ("INBOX",)), t2=_thread("t2", ("TRASH",))
    )
    text = call(
        _server(tmp_path, fake),
        "delete_permanently",
        account="work",
        ids=["t1", "t2"],
        kind="thread",
        dry_run=False,
    )
    assert text == (
        "Error: 1 thread is not entirely in Trash: t1. Trash it first, or pass "
        "require_trashed=false to delete it anyway. Nothing was deleted."
    )
    assert fake.calls_to("users.threads.delete") == []


def test_thread_delete_failure_midway_reports_what_went(tmp_path: Path) -> None:
    def delete(**kwargs: Any) -> dict[str, Any]:
        if kwargs["id"] == "t2":
            raise _http_error(500, "Backend Error")
        return {}

    fake = _threads(
        t1=_thread("t1", ("TRASH",)),
        t2=_thread("t2", ("TRASH",)),
        t3=_thread("t3", ("TRASH",)),
    )
    fake.responses["users.threads.delete"] = delete
    text = call(
        _server(tmp_path, fake),
        "delete_permanently",
        account="work",
        ids=["t1", "t2", "t3"],
        kind="thread",
        dry_run=False,
    )
    lines = text.splitlines()
    assert lines[0] == (
        "Permanently deleted 1 of 3 threads before an error on thread t2: "
        "HTTP 500: Backend Error"
    )
    assert lines[1:] == [
        "[thread t1] 1 message",
        "  [t1m1] Fri, 02 Oct 2026 10:00:00 +0000 | From: Sender <sender@example.com>"
        " | Subj: Test subject",
    ]
    assert [kw["id"] for kw in fake.calls_to("users.threads.delete")] == ["t1", "t2"]
