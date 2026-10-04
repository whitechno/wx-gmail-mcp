from __future__ import annotations

from wx_gmail_mcp import mime

from .conftest import b64, message


def test_body_prefers_plain_text_over_html() -> None:
    parts = [
        {"mimeType": "text/html", "body": {"data": b64("<b>hi</b>")}},
        {"mimeType": "text/plain", "body": {"data": b64("hi")}},
    ]
    assert mime.body_text(message(parts=parts)["payload"], 100) == "hi"


def test_body_falls_back_to_html_and_nested_parts() -> None:
    parts = [
        {
            "mimeType": "multipart/alternative",
            "body": {},
            "parts": [{"mimeType": "text/html", "body": {"data": b64("<p>x</p>")}}],
        }
    ]
    assert mime.body_text(message(parts=parts)["payload"], 100) == "<p>x</p>"
    assert mime.body_text({"mimeType": "text/plain", "body": {}}, 100) == ""


def test_body_truncates_with_marker() -> None:
    payload = message(body="a" * 50)["payload"]
    text = mime.body_text(payload, 10)
    assert text == "a" * 10 + mime.TRUNCATED_MARKER
    assert mime.body_text(payload, 50) == "a" * 50


def test_body_decodes_invalid_utf8_without_raising() -> None:
    import base64

    data = base64.urlsafe_b64encode(b"ok \xff\xfe").decode()
    payload = {"mimeType": "text/plain", "body": {"data": data}}
    assert mime.body_text(payload, 100).startswith("ok ")


def test_attachments_lists_parts_with_attachment_ids() -> None:
    parts = [
        {"mimeType": "text/plain", "body": {"data": b64("see attached")}},
        {
            "mimeType": "application/pdf",
            "filename": "a.pdf",
            "body": {"attachmentId": "att-1", "size": 1234},
        },
        {
            "mimeType": "image/png",
            "filename": "",
            "body": {"attachmentId": "att-2"},
        },
    ]
    atts = mime.attachments(message(parts=parts)["payload"])
    assert [a.attachment_id for a in atts] == ["att-1", "att-2"]
    assert atts[0].text() == "a.pdf (application/pdf, 1234 bytes) id=att-1"
    assert atts[1].filename == "(unnamed)"
    assert atts[1].size == 0
    assert mime.attachments(message()["payload"]) == []
