from __future__ import annotations

from typing import Any

import pytest

from wx_gmail_mcp import compose
from wx_gmail_mcp.compose import Original

from .conftest import b64, message

ME = "me@example.com"


def _orig(**headers: str) -> Original:
    base = {
        "From": "Alice <alice@example.com>",
        "To": "Me <me@example.com>, Bob <bob@example.com>",
        "Cc": "carol@example.com, ME@EXAMPLE.COM",
        "Subject": "Plans",
        "Message-ID": "<orig@mail.example.com>",
    }
    base.update(headers)
    return Original.from_message(
        message("m1", "t1", headers=base, body="line 1\nline 2")
    )


def test_from_message_reads_headers() -> None:
    o = _orig(References="<root@mail.example.com>")
    assert (o.id, o.thread_id) == ("m1", "t1")
    assert o.sender == "Alice <alice@example.com>"
    assert o.message_id_header == "<orig@mail.example.com>"
    assert o.references == "<root@mail.example.com>"
    assert o.subject == "Plans"
    assert o.reply_to == ""


def test_threading_headers() -> None:
    assert compose.threading_headers(_orig()) == (
        "<orig@mail.example.com>",
        "<orig@mail.example.com>",
    )
    assert compose.threading_headers(_orig(References="<a@x> <b@x>")) == (
        "<orig@mail.example.com>",
        "<a@x> <b@x> <orig@mail.example.com>",
    )
    # No Message-ID: nothing to reference; threadId alone still files it.
    o = Original.from_message(message("m1", "t1", headers={"Message-ID": ""}))
    assert compose.threading_headers(o) == ("", "")


def test_subject_prefixes() -> None:
    assert compose.reply_subject("Plans") == "Re: Plans"
    assert compose.reply_subject(" RE: Plans") == "RE: Plans"
    assert compose.reply_subject("re:Plans") == "re:Plans"
    assert compose.reply_subject("") == "Re:"
    assert compose.forward_subject("Plans") == "Fwd: Plans"
    assert compose.forward_subject("FW: Plans") == "FW: Plans"
    assert compose.forward_subject("Fwd: Plans") == "Fwd: Plans"
    assert compose.forward_subject("Re: Plans") == "Fwd: Re: Plans"


def test_reply_goes_to_reply_to_else_from() -> None:
    assert compose.reply_recipients(_orig(), ME, False) == (
        "Alice <alice@example.com>",
        "",
    )
    o = _orig(**{"Reply-To": "list@example.com"})
    assert compose.reply_recipients(o, ME, False) == ("list@example.com", "")


def test_reply_all_copies_others_minus_self_and_to() -> None:
    to, cc = compose.reply_recipients(_orig(), ME, True)
    assert to == "Alice <alice@example.com>"
    assert cc == "Bob <bob@example.com>, carol@example.com"
    # Reply-To already among the recipients is not copied twice.
    o = _orig(**{"Reply-To": "bob@example.com"})
    assert compose.reply_recipients(o, ME, True) == (
        "bob@example.com",
        "carol@example.com",
    )


def test_reply_to_own_message_goes_to_its_recipients() -> None:
    o = _orig(From="Me <me@example.com>", To="Bob <bob@example.com>")
    assert compose.reply_recipients(o, ME, False) == ("Bob <bob@example.com>", "")
    assert compose.reply_recipients(o, ME, True) == (
        "Bob <bob@example.com>",
        "carol@example.com",
    )
    # Sent to oneself: the reply goes back to oneself.
    o = _orig(From="me@example.com", To="me@example.com", Cc="")
    assert compose.reply_recipients(o, ME, True) == ("me@example.com", "")


def test_quoted_and_forwarded_blocks() -> None:
    o = _orig()
    assert compose.quoted(o) == (
        "On Fri, 02 Oct 2026 10:00:00 +0000, Alice <alice@example.com> wrote:\n"
        "> line 1\n"
        "> line 2",
        False,
    )
    assert compose.reply_body("Thanks!\n", o, True) == (
        "Thanks!\n\n" + compose.quoted(o)[0],
        False,
    )
    assert compose.reply_body("Thanks!\n", o, False) == ("Thanks!", False)
    assert compose.forwarded(o) == (
        "---------- Forwarded message ---------\n"
        "From: Alice <alice@example.com>\n"
        "Date: Fri, 02 Oct 2026 10:00:00 +0000\n"
        "Subject: Plans\n"
        "To: Me <me@example.com>, Bob <bob@example.com>\n"
        "Cc: carol@example.com, ME@EXAMPLE.COM\n"
        "\n"
        "line 1\nline 2",
        False,
    )
    assert compose.forward_body("", o) == compose.forwarded(o)
    assert compose.forward_body("FYI", o)[0].startswith("FYI\n\n----------")
    # An empty original body still produces a quote marker line.
    empty = Original.from_message(message("m1", "t1", body=""))
    assert compose.quoted(empty)[0].endswith("wrote:\n>")


def test_html_only_original_is_quoted_as_text() -> None:
    html = (
        "<html><head><style>p{color:red}</style></head><body>"
        "<p>Hello <b>there</b>,</p><p>Prices &amp; terms:</p>"
        "<ul><li>one</li><li>two</li></ul><br>Bye<script>x()</script></body></html>"
    )
    parts: list[dict[str, Any]] = [
        {"partId": "0", "mimeType": "text/html", "body": {"data": b64(html)}}
    ]
    o = Original.from_message(message("m1", "t1", parts=parts))
    text, cut = compose.quoted(o)
    assert not cut
    assert text.endswith(
        "wrote:\n> Hello there,\n>\n> Prices & terms:\n>\n> - one\n> - two\n>\n> Bye"
    )
    assert "<" not in text.split("wrote:", 1)[1]


def test_runaway_original_is_cut_and_flagged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(compose, "QUOTE_LIMIT", 6)
    o = _orig()
    assert compose.quoted(o) == (
        "On Fri, 02 Oct 2026 10:00:00 +0000, Alice <alice@example.com> wrote:\n"
        "> line 1\n"
        "> [original text cut here]",
        True,
    )
    assert compose.forwarded(o)[1] is True
    assert compose.reply_body("x", o, False) == ("x", False)
    assert "longer than 6 characters" in compose.cut_note(True)
    assert compose.cut_note(False) == ""


def test_blob_type() -> None:
    assert compose._blob_type("image/png") == ("image", "png")
    assert compose._blob_type("message/rfc822") == ("message", "rfc822")
    assert compose._blob_type("message/delivery-status") == (
        "application",
        "octet-stream",
    )
    assert compose._blob_type("multipart/mixed") == ("application", "octet-stream")
    assert compose._blob_type("nonsense") == ("application", "octet-stream")


def test_original_attachments_fetches_each_part() -> None:
    from .fake_gmail import FakeGmail

    parts: list[dict[str, Any]] = [
        {"partId": "0", "mimeType": "text/plain", "body": {"data": b64("x")}},
        {
            "partId": "1",
            "mimeType": "image/png",
            "filename": "../pic.png",
            "body": {"attachmentId": "att1", "size": 2},
        },
        {
            "partId": "2",
            "mimeType": "application/pdf",
            "filename": "",
            "body": {"attachmentId": "att2", "size": 1},
        },
    ]
    fake = FakeGmail(
        {"users.messages.attachments.get": lambda **kw: {"data": b64(kw["id"])}}
    )
    o = Original.from_message(message("m1", "t1", parts=parts))
    blobs = compose.original_attachments(fake, o)
    assert [(b.filename, b.maintype, b.subtype, b.data) for b in blobs] == [
        ("pic.png", "image", "png", b"att1"),
        ("attachment-2", "application", "pdf", b"att2"),
    ]
    assert [c["id"] for c in fake.calls_to("users.messages.attachments.get")] == [
        "att1",
        "att2",
    ]
