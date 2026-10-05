from __future__ import annotations

import base64
from email import message_from_bytes, policy
from email.message import EmailMessage
from pathlib import Path
from typing import cast

import pytest

from wx_gmail_mcp import mime
from wx_gmail_mcp.errors import WxGmailError


def _parse(raw: str) -> EmailMessage:
    parsed = message_from_bytes(base64.urlsafe_b64decode(raw), policy=policy.default)
    return cast(EmailMessage, parsed)


def test_plain_message_headers_and_body() -> None:
    msg = _parse(mime.build_message(to="a@example.com", subject="Hi", body="Hello\n"))
    assert msg["To"] == "a@example.com"
    assert msg["Subject"] == "Hi"
    assert msg["From"] is None  # Gmail fills it in
    assert msg["Cc"] is None and msg["Bcc"] is None
    assert msg.get_content_type() == "text/plain"
    assert msg.get_payload(decode=True) == b"Hello\n"


def test_optional_headers() -> None:
    msg = _parse(
        mime.build_message(
            to="a@example.com",
            subject="s",
            body="b",
            cc=" c@example.com ",
            bcc="d@example.com",
            reply_to="r@example.com",
            in_reply_to="<id-1@example.com>",
            references="<id-0@example.com> <id-1@example.com>",
        )
    )
    assert msg["Cc"] == "c@example.com"
    assert msg["Bcc"] == "d@example.com"
    assert msg["Reply-To"] == "r@example.com"
    assert msg["In-Reply-To"] == "<id-1@example.com>"
    assert msg["References"] == "<id-0@example.com> <id-1@example.com>"


def test_html_adds_alternative() -> None:
    msg = _parse(
        mime.build_message(
            to="a@example.com", subject="s", body="plain", html="<b>x</b>"
        )
    )
    assert msg.get_content_type() == "multipart/alternative"
    parts = list(msg.iter_parts())
    assert [p.get_content_type() for p in parts] == ["text/plain", "text/html"]
    assert parts[1].get_payload(decode=True) == b"<b>x</b>\n"


def test_attachments_are_added_with_guessed_type(tmp_path: Path) -> None:
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    blob = tmp_path / "data.unknownext"
    blob.write_bytes(b"\x00\x01")
    msg = _parse(
        mime.build_message(
            to="a@example.com",
            subject="s",
            body="see attached",
            attachments=[pdf, blob],
        )
    )
    assert msg.get_content_type() == "multipart/mixed"
    atts = list(msg.iter_attachments())
    assert [a.get_filename() for a in atts] == ["report.pdf", "data.unknownext"]
    assert atts[0].get_content_type() == "application/pdf"
    assert atts[0].get_payload(decode=True) == b"%PDF-1.4 fake"
    assert atts[1].get_content_type() == "application/octet-stream"


def test_blobs_are_attached_after_files(tmp_path: Path) -> None:
    note = tmp_path / "note.txt"
    note.write_text("n")
    inner = base64.urlsafe_b64decode(
        mime.build_message(to="a@example.com", subject="inner", body="hello \u00e9")
    )
    msg = _parse(
        mime.build_message(
            to="a@example.com",
            subject="s",
            body="b",
            attachments=[note],
            blobs=[
                mime.Blob("pic.png", "image", "png", b"\x89PNG"),
                mime.Blob("inner.eml", "message", "rfc822", inner),
            ],
        )
    )
    atts = list(msg.iter_attachments())
    assert [a.get_filename() for a in atts] == ["note.txt", "pic.png", "inner.eml"]
    assert atts[1].get_content_type() == "image/png"
    assert atts[1].get_payload(decode=True) == b"\x89PNG"
    assert atts[2].get_content_type() == "message/rfc822"
    assert atts[2]["Content-Transfer-Encoding"] != "base64"
    nested = cast(EmailMessage, cast(list[EmailMessage], atts[2].get_payload())[0])
    assert nested["Subject"] == "inner"
    assert nested.get_content() == "hello \u00e9\n"


def test_validation() -> None:
    with pytest.raises(WxGmailError, match="to is required"):
        mime.build_message(to=" ", subject="s", body="b")
    with pytest.raises(WxGmailError, match="body, html, or both"):
        mime.build_message(to="a@example.com", subject="s", body="")
    # html alone is fine
    assert mime.build_message(to="a@example.com", subject="s", body="", html="<p>x</p>")


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("a.pdf", ("application", "pdf")),
        ("notes.txt", ("text", "plain")),
        ("logs.txt.gz", ("application", "octet-stream")),
        ("backup.tar.gz", ("application", "octet-stream")),
        ("mail.eml", ("application", "octet-stream")),
        ("data.unknownext", ("application", "octet-stream")),
    ],
)
def test_attachment_type(name: str, expected: tuple[str, str]) -> None:
    assert mime.attachment_type(name) == expected
