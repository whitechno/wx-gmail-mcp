from __future__ import annotations

import json
from email import message_from_bytes, policy
from email.message import EmailMessage
from pathlib import Path
from typing import Any, cast

import httplib2
from googleapiclient.errors import HttpError

from wx_gmail_mcp.config import BASE_SCOPES, SCOPE_SEND, Settings
from wx_gmail_mcp.server import build_server

from .conftest import (
    FakeRuntime,
    b64,
    call,
    make_settings,
    message,
    tool_server,
    uploaded,
)
from .fake_gmail import FakeGmail

FIELDS: dict[str, Any] = {
    "account": "work",
    "to": "a@example.com",
    "subject": "Hello",
    "body": "Body",
}


def _raw(call_kwargs: dict[str, Any]) -> EmailMessage:
    parsed = message_from_bytes(uploaded(call_kwargs), policy=policy.default)
    return cast(EmailMessage, parsed)


def _http_error(status: int, msg: str) -> HttpError:
    return HttpError(
        httplib2.Response({"status": status}),
        json.dumps({"error": {"message": msg}}).encode(),
    )


def _draft(draft_id: str, msg: dict[str, Any]) -> dict[str, Any]:
    return {"id": draft_id, "message": msg}


# --- list_drafts ------------------------------------------------------------


def test_list_drafts(settings: Settings) -> None:
    fake = FakeGmail(
        {
            "users.drafts.list": {
                "drafts": [
                    {"id": "d1", "message": {"id": "m1", "threadId": "t1"}},
                    {"id": "d2", "message": {"id": "m2", "threadId": "t2"}},
                ],
                "nextPageToken": "tok",
            },
            "users.messages.get": lambda **kw: message(
                kw["id"], f"t{kw['id'][1:]}", headers={"Subject": f"S {kw['id']}"}
            ),
        }
    )
    text = call(tool_server(settings, fake), "list_drafts", account="work")
    assert text == (
        "[draft d1] message m1 | thread t1 | Fri, 02 Oct 2026 10:00:00 +0000\n"
        "  To: you@example.com\n"
        "  Subj: S m1\n\n"
        "[draft d2] message m2 | thread t2 | Fri, 02 Oct 2026 10:00:00 +0000\n"
        "  To: you@example.com\n"
        "  Subj: S m2\n\n"
        "next_page_token: tok"
    )
    (listed,) = fake.calls_to("users.drafts.list")
    assert listed == {"userId": "me", "maxResults": 20}
    gets = fake.calls_to("users.messages.get")
    assert [g["id"] for g in gets] == ["m1", "m2"]
    assert gets[0]["format"] == "metadata"
    assert gets[0]["metadataHeaders"] == ["To", "Subject", "Date"]


def test_list_drafts_query_paging_and_empty(settings: Settings) -> None:
    fake = FakeGmail({"users.drafts.list": {}})
    mcp = tool_server(settings, fake)
    text = call(
        mcp,
        "list_drafts",
        account="work",
        query=" to:x ",
        max_results=5,
        page_token="p",
    )
    assert text == "No drafts."
    (listed,) = fake.calls_to("users.drafts.list")
    assert listed == {"userId": "me", "maxResults": 5, "q": "to:x", "pageToken": "p"}
    assert call(mcp, "list_drafts", account="work", max_results=0).startswith(
        "Error: max_results must be between 1 and 100."
    )
    assert len(fake.calls) == 1


def test_list_drafts_skips_a_draft_deleted_meanwhile(settings: Settings) -> None:
    def get(**kw: Any) -> dict[str, Any]:
        if kw["id"] == "m2":
            raise _http_error(404, "Requested entity was not found.")
        return message(kw["id"], "t1")

    fake = FakeGmail(
        {
            "users.drafts.list": {
                "drafts": [
                    {"id": "d1", "message": {"id": "m1"}},
                    {"id": "d2", "message": {"id": "m2"}},
                    {"id": "d3", "message": {"id": "m3"}},
                ]
            },
            "users.messages.get": get,
        }
    )
    text = call(tool_server(settings, fake), "list_drafts", account="work")
    assert "[draft d1] message m1 |" in text
    assert "[draft d2] message m2 | (gone)" in text
    assert "[draft d3] message m3 |" in text
    # Other failures still surface.
    fake = FakeGmail(
        {
            "users.drafts.list": {"drafts": [{"id": "d1", "message": {"id": "m1"}}]},
            "users.messages.get": lambda **kw: _raise(_http_error(500, "boom")),
        }
    )
    text = call(tool_server(settings, fake), "list_drafts", account="work")
    assert text == "Gmail API error: HTTP 500: boom"


# --- get_draft --------------------------------------------------------------


def test_get_draft(settings: Settings) -> None:
    msg = message(
        "m1",
        "t1",
        labels=("DRAFT",),
        headers={
            "To": "a@example.com",
            "Cc": "c@example.com",
            "Bcc": "b@example.com",
            "In-Reply-To": "<orig@example.com>",
        },
        body="Draft body",
    )
    fake = FakeGmail({"users.drafts.get": _draft("d1", msg)})
    text = call(tool_server(settings, fake), "get_draft", account="work", draft_id="d1")
    assert text == (
        "Draft id: d1\n"
        "Message id: m1\n"
        "Thread id: t1\n"
        "Date: Fri, 02 Oct 2026 10:00:00 +0000\n"
        "To: a@example.com\n"
        "Cc: c@example.com\n"
        "Bcc: b@example.com\n"
        "In-Reply-To: <orig@example.com>\n"
        "Subject: Test subject\n"
        "\n"
        "Draft body"
    )
    (got,) = fake.calls_to("users.drafts.get")
    assert got == {"userId": "me", "id": "d1", "format": "full"}


def test_get_draft_attachments_and_max_body(settings: Settings) -> None:
    parts = [
        {
            "partId": "0",
            "mimeType": "text/plain",
            "body": {"data": b64("0123456789"), "size": 10},
        },
        {
            "partId": "1",
            "mimeType": "application/pdf",
            "filename": "r.pdf",
            "body": {"attachmentId": "att1", "size": 3},
        },
    ]
    msg = message("m1", "t1", labels=("DRAFT",), parts=parts)
    fake = FakeGmail({"users.drafts.get": _draft("d1", msg)})
    text = call(
        tool_server(settings, fake),
        "get_draft",
        account="work",
        draft_id="d1",
        max_body=4,
    )
    assert "Attachments:\n  - part 1: r.pdf (application/pdf, 3 bytes) id=att1" in text
    assert text.endswith("\n\n0123\n...[truncated]")


def test_get_draft_missing_is_text(settings: Settings) -> None:
    fake = FakeGmail({"users.drafts.get": lambda **kw: _raise(_http_error(404, "nf"))})
    text = call(tool_server(settings, fake), "get_draft", account="work", draft_id="x")
    assert text == "Gmail API error: HTTP 404: nf"


def _raise(e: Exception) -> dict[str, Any]:
    raise e


# --- update_draft -----------------------------------------------------------


def test_update_draft_replaces_content_and_keeps_thread(settings: Settings) -> None:
    existing = message(
        "m1",
        "t1",
        labels=("DRAFT",),
        headers={
            "In-Reply-To": "<orig@example.com>",
            "References": "<root@example.com> <orig@example.com>",
        },
    )
    fake = FakeGmail(
        {
            "users.drafts.get": _draft("d1", existing),
            "users.drafts.update": _draft("d1", {"id": "m2", "threadId": "t1"}),
        }
    )
    text = call(
        tool_server(settings, fake),
        "update_draft",
        **FIELDS,
        draft_id=" d1 ",
        cc="c@example.com",
    )
    assert text == "Draft updated. draft id=d1 message id=m2"
    (got,) = fake.calls_to("users.drafts.get")
    assert got == {"userId": "me", "id": "d1", "format": "metadata"}
    (upd,) = fake.calls_to("users.drafts.update")
    assert upd["id"] == "d1"
    assert upd["body"]["message"]["threadId"] == "t1"
    msg = _raw(upd)
    assert msg["To"] == "a@example.com"
    assert msg["Cc"] == "c@example.com"
    assert msg["Subject"] == "Hello"
    assert msg["In-Reply-To"] == "<orig@example.com>"
    assert msg["References"] == "<root@example.com> <orig@example.com>"
    assert msg.get_payload(decode=True) == b"Body\n"
    assert fake.calls_to("users.messages.send") == []
    assert fake.calls_to("users.drafts.send") == []


def test_update_draft_plain_draft_has_no_thread(settings: Settings) -> None:
    fake = FakeGmail(
        {
            "users.drafts.get": _draft("d1", message("m1", "", labels=("DRAFT",))),
            "users.drafts.update": _draft("d1", {"id": "m2"}),
        }
    )
    call(tool_server(settings, fake), "update_draft", **FIELDS, draft_id="d1")
    (upd,) = fake.calls_to("users.drafts.update")
    assert "body" not in upd  # no thread: the upload is the whole request
    msg = _raw(upd)
    assert msg["In-Reply-To"] is None and msg["References"] is None


def test_update_draft_validates_before_writing(settings: Settings) -> None:
    fake = FakeGmail({"users.drafts.get": _draft("d1", message("m1", "t1"))})
    mcp = tool_server(settings, fake)
    text = call(mcp, "update_draft", **{**FIELDS, "body": ""}, draft_id="d1")
    assert text == "Error: Give a body, html, or both."
    text = call(mcp, "update_draft", **FIELDS, draft_id="d1", attachments=["../x"])
    assert text.startswith("Error: attachment path:")
    assert fake.calls_to("users.drafts.update") == []
    # A missing draft is reported before anything is built.
    fake = FakeGmail({"users.drafts.get": lambda **kw: _raise(_http_error(404, "nf"))})
    text = call(tool_server(settings, fake), "update_draft", **FIELDS, draft_id="d9")
    assert text == "Gmail API error: HTTP 404: nf"
    assert fake.calls_to("users.drafts.update") == []


# --- delete_draft -----------------------------------------------------------


def test_delete_draft_one_call_each_deduped(settings: Settings) -> None:
    fake = FakeGmail()
    text = call(
        tool_server(settings, fake),
        "delete_draft",
        account="work",
        draft_ids=["d1", " d2 ", "d1"],
    )
    assert text == "Deleted 2 drafts."
    assert fake.calls_to("users.drafts.delete") == [
        {"userId": "me", "id": "d1"},
        {"userId": "me", "id": "d2"},
    ]


def test_delete_draft_validation_and_partial_failure(settings: Settings) -> None:
    fake = FakeGmail()
    mcp = tool_server(settings, fake)
    text = call(mcp, "delete_draft", account="work", draft_ids=[" "])
    assert text == "Error: draft_ids must contain at least one id."
    text = call(
        mcp, "delete_draft", account="work", draft_ids=[str(i) for i in range(101)]
    )
    assert text == "Error: draft_ids holds 101 ids; the cap is 100."
    assert fake.calls == []

    def flaky(**kw: Any) -> dict[str, Any]:
        if kw["id"] == "d2":
            raise _http_error(404, "Requested entity was not found.")
        return {}

    fake = FakeGmail({"users.drafts.delete": flaky})
    text = call(
        tool_server(settings, fake),
        "delete_draft",
        account="work",
        draft_ids=["d1", "d2", "d3"],
    )
    assert text == (
        "Deleted 1 of 3 drafts before an error on draft d2: "
        "HTTP 404: Requested entity was not found."
    )
    assert [c["id"] for c in fake.calls_to("users.drafts.delete")] == ["d1", "d2"]


def test_delete_draft_singular(settings: Settings) -> None:
    text = call(
        tool_server(settings, FakeGmail()),
        "delete_draft",
        account="work",
        draft_ids=["d1"],
    )
    assert text == "Deleted 1 draft."


# --- send_draft (SEND gate) -------------------------------------------------


def _send_server(tmp_path: Path, fake: FakeGmail, scopes: tuple[str, ...]):
    s = make_settings(tmp_path, sending=True)
    return build_server(FakeRuntime(s, {"work": fake}, {"work": scopes}))


def test_send_draft(tmp_path: Path) -> None:
    stored = message("m1", "t1", labels=("DRAFT",), headers={"To": "a@example.com"})
    fake = FakeGmail(
        {
            "users.drafts.get": _draft("d1", stored),
            "users.drafts.send": {"id": "m1", "threadId": "t1", "labelIds": ["SENT"]},
        }
    )
    mcp = _send_server(tmp_path, fake, (*BASE_SCOPES, SCOPE_SEND))
    text = call(mcp, "send_draft", account="work", draft_id=" d1 ")
    assert text == (
        "Sent draft d1 (To: a@example.com | Subj: Test subject). "
        "message id=m1 thread id=t1"
    )
    (got,) = fake.calls_to("users.drafts.get")
    assert got == {"userId": "me", "id": "d1", "format": "metadata"}
    (sent,) = fake.calls_to("users.drafts.send")
    assert sent == {"userId": "me", "body": {"id": "d1"}}


def test_send_draft_without_send_scope_is_refused(tmp_path: Path) -> None:
    fake = FakeGmail({"users.drafts.send": {"id": "m1"}})
    mcp = _send_server(tmp_path, fake, BASE_SCOPES)
    text = call(mcp, "send_draft", account="work", draft_id="d1")
    assert text.startswith("Error: Account 'work' has not granted the send scope.")
    assert "WX_GMAIL_ALLOW_SENDING=true wx-gmail-mcp --auth work" in text
    assert fake.calls == []


def test_send_draft_missing_draft_sends_nothing(tmp_path: Path) -> None:
    fake = FakeGmail({"users.drafts.get": lambda **kw: _raise(_http_error(404, "nf"))})
    mcp = _send_server(tmp_path, fake, (*BASE_SCOPES, SCOPE_SEND))
    text = call(mcp, "send_draft", account="work", draft_id="d9")
    assert text == "Gmail API error: HTTP 404: nf"
    assert fake.calls_to("users.drafts.send") == []
