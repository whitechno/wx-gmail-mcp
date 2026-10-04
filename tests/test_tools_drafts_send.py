from __future__ import annotations

import base64
from email import message_from_bytes, policy
from email.message import EmailMessage
from pathlib import Path
from typing import Any, cast

from wx_gmail_mcp.config import BASE_SCOPES, SCOPE_FULL, SCOPE_SEND, Settings
from wx_gmail_mcp.server import build_server

from .conftest import FakeRuntime, call, make_settings, tool_names, tool_server
from .fake_gmail import FakeGmail

ARGS: dict[str, Any] = {
    "account": "work",
    "to": "a@example.com",
    "subject": "Hello",
    "body": "Body",
}


def _raw(call_kwargs: dict[str, Any]) -> EmailMessage:
    body = call_kwargs["body"]
    raw = body["raw"] if "raw" in body else body["message"]["raw"]
    parsed = message_from_bytes(base64.urlsafe_b64decode(raw), policy=policy.default)
    return cast(EmailMessage, parsed)


def test_create_draft(settings: Settings) -> None:
    fake = FakeGmail({"users.drafts.create": {"id": "d1", "message": {"id": "m1"}}})
    text = call(tool_server(settings, fake), "create_draft", **ARGS, cc="c@example.com")
    assert text == "Draft created. draft id=d1 message id=m1"
    (create,) = fake.calls_to("users.drafts.create")
    msg = _raw(create)
    assert msg["To"] == "a@example.com"
    assert msg["Cc"] == "c@example.com"
    assert msg["Subject"] == "Hello"
    assert fake.calls_to("users.messages.send") == []


def test_create_draft_with_outbox_attachment(settings: Settings) -> None:
    settings.outbox_dir.mkdir(parents=True)
    (settings.outbox_dir / "a.txt").write_text("hi")
    fake = FakeGmail({"users.drafts.create": {"id": "d1", "message": {"id": "m1"}}})
    mcp = tool_server(settings, fake)
    call(mcp, "create_draft", **ARGS, attachments=["a.txt"], html="<p>Body</p>")
    msg = _raw(fake.calls_to("users.drafts.create")[0])
    assert msg.get_content_type() == "multipart/mixed"
    (att,) = msg.iter_attachments()
    assert att.get_filename() == "a.txt"
    # An attachment outside the outbox is refused before any API call.
    text = call(mcp, "create_draft", **ARGS, attachments=["../a.txt"])
    assert text.startswith("Error: attachment path:")
    assert len(fake.calls_to("users.drafts.create")) == 1


def test_create_draft_validation_is_text(settings: Settings) -> None:
    fake = FakeGmail()
    text = call(tool_server(settings, fake), "create_draft", **{**ARGS, "body": ""})
    assert text == "Error: Give a body, html, or both."
    assert fake.calls == []


def _send_server(tmp_path: Path, fake: FakeGmail, scopes: tuple[str, ...]):
    s = make_settings(tmp_path, sending=True)
    return build_server(FakeRuntime(s, {"work": fake}, {"work": scopes}))


def test_send_message_requires_gate_to_register(tmp_path: Path) -> None:
    assert "send_message" not in tool_names(
        tool_server(make_settings(tmp_path), FakeGmail())
    )
    assert "send_message" in tool_names(
        _send_server(tmp_path, FakeGmail(), (*BASE_SCOPES, SCOPE_SEND))
    )


def test_send_message(tmp_path: Path) -> None:
    fake = FakeGmail({"users.messages.send": {"id": "m9", "threadId": "t9"}})
    mcp = _send_server(tmp_path, fake, (*BASE_SCOPES, SCOPE_SEND))
    text = call(
        mcp, "send_message", **ARGS, bcc="b@example.com", reply_to="r@example.com"
    )
    assert text == "Sent. message id=m9 thread id=t9"
    (send,) = fake.calls_to("users.messages.send")
    assert send["userId"] == "me"
    msg = _raw(send)
    assert msg["Bcc"] == "b@example.com"
    assert msg["Reply-To"] == "r@example.com"
    assert msg.get_payload(decode=True) == b"Body\n"


def test_send_message_with_full_scope(tmp_path: Path) -> None:
    fake = FakeGmail({"users.messages.send": {"id": "m9", "threadId": "t9"}})
    mcp = _send_server(tmp_path, fake, (SCOPE_FULL,))
    assert call(mcp, "send_message", **ARGS).startswith("Sent.")


def test_send_message_without_send_scope_is_refused(tmp_path: Path) -> None:
    fake = FakeGmail({"users.messages.send": {"id": "m9"}})
    mcp = _send_server(tmp_path, fake, BASE_SCOPES)
    text = call(mcp, "send_message", **ARGS)
    assert text.startswith("Error: Account 'work' has not granted the send scope.")
    assert "WX_GMAIL_ALLOW_SENDING=true wx-gmail-mcp --auth work" in text
    assert fake.calls == []
