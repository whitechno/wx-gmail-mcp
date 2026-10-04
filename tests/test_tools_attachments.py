from __future__ import annotations

import stat
from pathlib import Path
from typing import Any

import pytest

from wx_gmail_mcp import mime, safety
from wx_gmail_mcp.config import Settings
from wx_gmail_mcp.errors import WxGmailError

from .conftest import LABELS, b64, call, message, tool_server
from .fake_gmail import FakeGmail

PDF = {
    "mimeType": "application/pdf",
    "filename": "report.pdf",
    "body": {"attachmentId": "att-pdf", "size": 3},
}
PNG = {
    "mimeType": "image/png",
    "filename": "../../etc/evil.png",
    "body": {"attachmentId": "att-png", "size": 4},
}
TEXT = {"mimeType": "text/plain", "body": {"data": b64("hi")}}


def _fake(parts: list[dict[str, Any]], **responses: Any) -> FakeGmail:
    base: dict[str, Any] = {
        "users.labels.list": {"labels": LABELS},
        "users.messages.get": message("m1", parts=parts),
        "users.messages.attachments.get": lambda **kw: {
            "data": b64({"att-pdf": "%PDF", "att-png": "PNG!"}[kw["id"]]),
            "size": 4,
        },
    }
    base.update(responses)
    return FakeGmail(base)


# --- helpers ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("report.pdf", "report.pdf"),
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\x\\notes.txt", "notes.txt"),
        (".hidden", "hidden"),
        ("  spaced name.txt ", "spaced name.txt"),
        ('a:b*c?d"e<f>g|h.txt', "a_b_c_d_e_f_g_h.txt"),
        ("ctrl\x00char\x1f.bin", "ctrl_char_.bin"),
        ("", "fallback.bin"),
        ("...", "fallback.bin"),
        ("/", "fallback.bin"),
    ],
)
def test_safe_filename(raw: str, expected: str) -> None:
    assert mime.safe_filename(raw, "fallback.bin") == expected


def test_decode_attachment() -> None:
    assert mime.decode_attachment(b64("abc")) == b"abc"
    assert mime.decode_attachment("YWJj") == b"abc"  # unpadded
    with pytest.raises(WxGmailError, match="could not be decoded"):
        mime.decode_attachment("!!!not base64!!!")


def test_pick_attachment() -> None:
    from wx_gmail_mcp.tools.read import pick_attachment

    a = mime.Attachment("id-a", "a.pdf", "application/pdf", 1)
    b = mime.Attachment("id-b", "b.pdf", "application/pdf", 1)
    b2 = mime.Attachment("id-b2", "B.PDF", "application/pdf", 1)
    assert pick_attachment([a], "") is a
    assert pick_attachment([a, b], "id-b") is b
    assert pick_attachment([a, b], "A.PDF") is a
    with pytest.raises(WxGmailError, match="has no attachments"):
        pick_attachment([], "")
    with pytest.raises(WxGmailError, match="has 2 attachments; name one"):
        pick_attachment([a, b], "")
    with pytest.raises(WxGmailError, match=r"2 attachments are named 'b\.pdf'"):
        pick_attachment([a, b, b2], "b.pdf")
    with pytest.raises(WxGmailError, match=r"No attachment 'c\.pdf' on this message"):
        pick_attachment([a], "c.pdf")


def test_write_download_modes_and_overwrite(settings: Settings) -> None:
    path = safety.write_download(settings, "sub/dir/a.bin", b"one")
    assert path == (settings.downloads_dir / "sub/dir/a.bin").resolve()
    assert path.read_bytes() == b"one"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    for d in (settings.downloads_dir, path.parent.parent, path.parent):
        assert stat.S_IMODE(d.stat().st_mode) == 0o700, d
    with pytest.raises(WxGmailError, match=r"already exists .* overwrite=true"):
        safety.write_download(settings, "sub/dir/a.bin", b"two")
    assert path.read_bytes() == b"one"
    safety.write_download(settings, "sub/dir/a.bin", b"two", overwrite=True)
    assert path.read_bytes() == b"two"
    with pytest.raises(WxGmailError, match="is a directory"):
        safety.write_download(settings, "sub/dir", b"x", overwrite=True)
    with pytest.raises(WxGmailError, match="escapes"):
        safety.write_download(settings, "../x.bin", b"x")


# --- list_attachments / download_attachment ----------------------------------


def test_list_attachments(settings: Settings) -> None:
    fake = _fake([TEXT, PDF, PNG])
    text = call(
        tool_server(settings, fake), "list_attachments", account="work", message_id="m1"
    )
    assert text == (
        "report.pdf (application/pdf, 3 bytes) id=att-pdf\n"
        "../../etc/evil.png (image/png, 4 bytes) id=att-png"
    )
    assert fake.calls_to("users.messages.get") == [
        {"userId": "me", "id": "m1", "format": "full"}
    ]
    fake = _fake([TEXT])
    assert (
        call(
            tool_server(settings, fake),
            "list_attachments",
            account="work",
            message_id="m1",
        )
        == "No attachments."
    )


def test_download_attachment_by_id_and_by_name(settings: Settings) -> None:
    fake = _fake([TEXT, PDF, PNG])
    mcp = tool_server(settings, fake)
    text = call(
        mcp,
        "download_attachment",
        account="work",
        message_id="m1",
        attachment="att-pdf",
    )
    saved = settings.downloads_dir.resolve() / "report.pdf"
    assert text == f"Saved {saved} (4 bytes, application/pdf)."
    assert saved.read_bytes() == b"%PDF"
    assert fake.calls_to("users.messages.attachments.get") == [
        {"userId": "me", "messageId": "m1", "id": "att-pdf"}
    ]
    # By file name; the sender's path is reduced to a plain name.
    text = call(
        mcp,
        "download_attachment",
        account="work",
        message_id="m1",
        attachment="../../etc/evil.png",
    )
    saved = settings.downloads_dir.resolve() / "evil.png"
    assert text == f"Saved {saved} (4 bytes, image/png)."
    assert saved.read_bytes() == b"PNG!"
    assert not (Path(settings.home) / "etc").exists()


def test_download_attachment_single_default_and_rename(settings: Settings) -> None:
    fake = _fake([TEXT, PDF])
    mcp = tool_server(settings, fake)
    text = call(mcp, "download_attachment", account="work", message_id="m1")
    assert text.startswith(f"Saved {settings.downloads_dir.resolve() / 'report.pdf'} ")
    text = call(
        mcp,
        "download_attachment",
        account="work",
        message_id="m1",
        filename="2026/q3/renamed.pdf",
    )
    saved = settings.downloads_dir.resolve() / "2026/q3/renamed.pdf"
    assert text == f"Saved {saved} (4 bytes, application/pdf)."
    assert saved.exists()


def test_download_attachment_refuses_overwrite_unless_asked(
    settings: Settings,
) -> None:
    fake = _fake([TEXT, PDF])
    mcp = tool_server(settings, fake)
    call(mcp, "download_attachment", account="work", message_id="m1")
    text = call(mcp, "download_attachment", account="work", message_id="m1")
    assert text.startswith("Error: 'report.pdf' already exists in")
    assert "overwrite=true" in text
    text = call(
        mcp, "download_attachment", account="work", message_id="m1", overwrite=True
    )
    assert text.startswith("Saved ")


def test_download_attachment_errors(settings: Settings) -> None:
    mcp = tool_server(settings, _fake([TEXT, PDF, PNG]))
    assert call(mcp, "download_attachment", account="work", message_id="m1") == (
        "Error: The message has 2 attachments; name one by id or file name."
    )
    assert call(
        mcp, "download_attachment", account="work", message_id="m1", attachment="nope"
    ).startswith("Error: No attachment 'nope' on this message. Attachments: report.pdf")
    assert call(
        mcp,
        "download_attachment",
        account="work",
        message_id="m1",
        attachment="att-pdf",
        filename="../escape.pdf",
    ).startswith("Error: download path: '../escape.pdf' escapes")
    mcp = tool_server(settings, _fake([TEXT]))
    assert call(mcp, "download_attachment", account="work", message_id="m1") == (
        "Error: The message has no attachments."
    )
    assert not settings.downloads_dir.exists()


def test_download_attachment_unnamed_falls_back(settings: Settings) -> None:
    part = {"mimeType": "application/octet-stream", "body": {"attachmentId": "att-pdf"}}
    fake = _fake([TEXT, part])
    text = call(
        tool_server(settings, fake),
        "download_attachment",
        account="work",
        message_id="m1",
    )
    assert text.startswith(
        f"Saved {settings.downloads_dir.resolve() / 'm1-attachment.bin'} "
    )
