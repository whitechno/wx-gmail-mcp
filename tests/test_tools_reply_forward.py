from __future__ import annotations

import base64
from email import message_from_bytes, policy
from email.message import EmailMessage
from pathlib import Path
from typing import Any, cast

from wx_gmail_mcp import mime
from wx_gmail_mcp.config import BASE_SCOPES, SCOPE_SEND
from wx_gmail_mcp.server import build_server

from .conftest import (
    FakeRuntime,
    b64,
    call,
    make_settings,
    message,
    tool_names,
    tool_server,
)
from .fake_gmail import FakeGmail

SEND = (*BASE_SCOPES, SCOPE_SEND)
HEADERS = {
    "From": "Alice <alice@example.com>",
    "To": "you@example.com, Bob <bob@example.com>",
    "Cc": "carol@example.com",
    "Subject": "Plans",
    "Message-ID": "<orig@mail.example.com>",
    "References": "<root@mail.example.com>",
}
PROFILE = {"emailAddress": "you@example.com"}


def _server(tmp_path: Path, fake: FakeGmail, scopes: tuple[str, ...] = SEND):
    s = make_settings(tmp_path, sending=True)
    return build_server(FakeRuntime(s, {"work": fake}, {"work": scopes}))


def _sent(fake: FakeGmail) -> tuple[dict[str, Any], EmailMessage]:
    (send,) = fake.calls_to("users.messages.send")
    raw = base64.urlsafe_b64decode(send["body"]["raw"])
    return send, cast(EmailMessage, message_from_bytes(raw, policy=policy.default))


def _fake(original: dict[str, Any], **more: Any) -> FakeGmail:
    return FakeGmail(
        {
            "users.messages.get": original,
            "users.getProfile": PROFILE,
            "users.messages.send": {"id": "m9", "threadId": "t1"},
            **more,
        }
    )


def test_reply_and_forward_register_only_with_sending_gate(tmp_path: Path) -> None:
    assert not {"reply", "forward"} & tool_names(
        tool_server(make_settings(tmp_path), FakeGmail())
    )
    assert {"reply", "forward"} <= tool_names(_server(tmp_path, FakeGmail()))


def test_reply_and_forward_require_send_scope(tmp_path: Path) -> None:
    fake = FakeGmail()
    mcp = _server(tmp_path, fake, BASE_SCOPES)
    for args in (
        {"name": "reply", "message_id": "m1", "body": "x"},
        {"name": "forward", "message_id": "m1", "to": "a@example.com"},
    ):
        text = call(mcp, args.pop("name"), account="work", **args)
        assert text.startswith("Error: Account 'work' has not granted the send scope.")
    assert fake.calls == []


def test_reply(tmp_path: Path) -> None:
    fake = _fake(message("m1", "t1", headers=HEADERS, body="line 1\nline 2"))
    text = call(
        _server(tmp_path, fake),
        "reply",
        account="work",
        message_id=" m1 ",
        body="Thanks!",
    )
    assert text == (
        "Replied to m1 (To: Alice <alice@example.com> | Subj: Re: Plans). "
        "message id=m9 thread id=t1"
    )
    (got,) = fake.calls_to("users.messages.get")
    assert got == {"userId": "me", "id": "m1", "format": "full"}
    send, msg = _sent(fake)
    assert send["body"]["threadId"] == "t1"
    assert msg["To"] == "Alice <alice@example.com>"
    assert msg["Cc"] is None and msg["Bcc"] is None
    assert msg["Subject"] == "Re: Plans"
    assert msg["In-Reply-To"] == "<orig@mail.example.com>"
    assert msg["References"] == "<root@mail.example.com> <orig@mail.example.com>"
    assert msg.get_content_type() == "text/plain"
    assert msg.get_content() == (
        "Thanks!\n\nOn Fri, 02 Oct 2026 10:00:00 +0000, Alice <alice@example.com> "
        "wrote:\n> line 1\n> line 2\n"
    )


def test_reply_all_without_quote_with_extras(tmp_path: Path) -> None:
    settings_dir = tmp_path / "home" / "outbox"
    settings_dir.mkdir(parents=True)
    (settings_dir / "a.txt").write_text("hi")
    fake = _fake(message("m1", "t1", headers=HEADERS))
    s = make_settings(tmp_path / "home", sending=True)
    mcp = build_server(FakeRuntime(s, {"work": fake}, {"work": SEND}))
    text = call(
        mcp,
        "reply",
        account="work",
        message_id="m1",
        body="All\n",
        reply_all=True,
        quote=False,
        cc="dave@example.com",
        bcc="eve@example.com",
        attachments=["a.txt"],
    )
    assert text.startswith(
        "Replied to m1 (To: Alice <alice@example.com> | Subj: Re: Plans)."
    )
    _, msg = _sent(fake)
    assert msg["Cc"] == "Bob <bob@example.com>, carol@example.com, dave@example.com"
    assert msg["Bcc"] == "eve@example.com"
    assert msg.get_content_type() == "multipart/mixed"
    assert msg.get_body().get_content() == "All\n"  # type: ignore[union-attr]
    (att,) = msg.iter_attachments()
    assert att.get_filename() == "a.txt"


def test_reply_to_own_sent_message_goes_to_its_recipients(tmp_path: Path) -> None:
    own = {**HEADERS, "From": "you@example.com", "To": "Bob <bob@example.com>"}
    fake = _fake(message("m1", "t1", headers=own, labels=("SENT",)))
    call(_server(tmp_path, fake), "reply", account="work", message_id="m1", body="x")
    _, msg = _sent(fake)
    assert msg["To"] == "Bob <bob@example.com>"


def test_reply_validates_before_any_call(tmp_path: Path) -> None:
    fake = _fake(message("m1", "t1", headers=HEADERS))
    mcp = _server(tmp_path, fake)
    assert call(mcp, "reply", account="work", message_id="m1", body=" ") == (
        "Error: body is required."
    )
    assert fake.calls == []
    text = call(
        mcp, "reply", account="work", message_id="m1", body="x", attachments=["../x"]
    )
    assert text.startswith("Error: attachment path:")
    assert fake.calls_to("users.messages.send") == []


def test_reply_without_message_id_header_uses_thread_only(tmp_path: Path) -> None:
    headers = {
        k: v for k, v in HEADERS.items() if k not in ("Message-ID", "References")
    }
    fake = _fake(message("m1", "t1", headers=headers))
    call(_server(tmp_path, fake), "reply", account="work", message_id="m1", body="x")
    send, msg = _sent(fake)
    assert send["body"]["threadId"] == "t1"
    assert msg["In-Reply-To"] is None and msg["References"] is None


def test_forward_quotes_and_reattaches(tmp_path: Path) -> None:
    parts: list[dict[str, Any]] = [
        {"partId": "0", "mimeType": "text/plain", "body": {"data": b64("the text")}},
        {
            "partId": "1",
            "mimeType": "application/pdf",
            "filename": "r.pdf",
            "body": {"attachmentId": "att1", "size": 4},
        },
    ]
    fake = _fake(
        message("m1", "t1", headers=HEADERS, parts=parts),
        **{"users.messages.attachments.get": {"data": b64("%PDF")}},
    )
    text = call(
        _server(tmp_path, fake),
        "forward",
        account="work",
        message_id="m1",
        to=" dan@example.com ",
        body="FYI",
        cc="erin@example.com",
    )
    assert text == (
        "Forwarded m1 (To: dan@example.com | Subj: Fwd: Plans). "
        "message id=m9 thread id=t1"
    )
    (att_get,) = fake.calls_to("users.messages.attachments.get")
    assert att_get == {"userId": "me", "messageId": "m1", "id": "att1"}
    send, msg = _sent(fake)
    assert send["body"]["threadId"] == "t1"
    assert msg["To"] == "dan@example.com"
    assert msg["Cc"] == "erin@example.com"
    assert msg["Subject"] == "Fwd: Plans"
    assert msg["In-Reply-To"] == "<orig@mail.example.com>"
    assert msg["References"] == "<root@mail.example.com> <orig@mail.example.com>"
    body = msg.get_body()
    assert body is not None
    assert body.get_content() == (
        "FYI\n\n---------- Forwarded message ---------\n"
        "From: Alice <alice@example.com>\n"
        "Date: Fri, 02 Oct 2026 10:00:00 +0000\n"
        "Subject: Plans\n"
        "To: you@example.com, Bob <bob@example.com>\n"
        "Cc: carol@example.com\n"
        "\n"
        "the text\n"
    )
    (att,) = msg.iter_attachments()
    assert att.get_filename() == "r.pdf"
    assert att.get_content_type() == "application/pdf"
    assert att.get_payload(decode=True) == b"%PDF"
    assert fake.calls_to("users.getProfile") == []


def test_forward_without_original_attachments(tmp_path: Path) -> None:
    parts: list[dict[str, Any]] = [
        {"partId": "0", "mimeType": "text/plain", "body": {"data": b64("t")}},
        {
            "partId": "1",
            "mimeType": "application/pdf",
            "filename": "r.pdf",
            "body": {"attachmentId": "att1", "size": 4},
        },
    ]
    fake = _fake(message("m1", "t1", headers=HEADERS, parts=parts))
    call(
        _server(tmp_path, fake),
        "forward",
        account="work",
        message_id="m1",
        to="dan@example.com",
        include_attachments=False,
    )
    assert fake.calls_to("users.messages.attachments.get") == []
    _, msg = _sent(fake)
    assert msg.get_content_type() == "text/plain"
    assert msg.get_content().startswith("---------- Forwarded message ---------\n")


def test_forward_as_attachment(tmp_path: Path) -> None:
    original_raw = base64.urlsafe_b64decode(
        mime.build_message(
            to="you@example.com", subject="Plans: Q4/2026?", body="inner"
        )
    )

    def get(**kw: Any) -> dict[str, Any]:
        if kw["format"] == "raw":
            return {"id": "m1", "threadId": "t1", "raw": b64(original_raw.decode())}
        return message("m1", "t1", headers=HEADERS)

    fake = FakeGmail(
        {
            "users.messages.get": get,
            "users.messages.send": {"id": "m9", "threadId": "t1"},
        }
    )
    text = call(
        _server(tmp_path, fake),
        "forward",
        account="work",
        message_id="m1",
        to="dan@example.com",
        as_attachment=True,
    )
    assert text.startswith("Forwarded m1 (To: dan@example.com | Subj: Fwd: Plans).")
    assert [g["format"] for g in fake.calls_to("users.messages.get")] == ["full", "raw"]
    _, msg = _sent(fake)
    assert msg.get_content_type() == "multipart/mixed"
    body = msg.get_body()
    assert body is not None
    assert body.get_content() == "Forwarded message: Plans\n"
    (att,) = msg.iter_attachments()
    assert att.get_content_type() == "message/rfc822"
    assert att.get_filename() == "Plans.eml"
    inner = cast(EmailMessage, cast(list[EmailMessage], att.get_payload())[0])
    assert inner["Subject"] == "Plans: Q4/2026?"
    assert inner.get_content() == "inner\n"


def test_forward_requires_to(tmp_path: Path) -> None:
    fake = _fake(message("m1", "t1", headers=HEADERS))
    text = call(
        _server(tmp_path, fake), "forward", account="work", message_id="m1", to=" "
    )
    assert text == "Error: to is required."
    assert fake.calls_to("users.messages.send") == []
