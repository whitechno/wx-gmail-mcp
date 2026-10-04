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
            "partId": "1",
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
    assert atts[0].part_id == "1"
    assert atts[0].text() == "part 1: a.pdf (application/pdf, 1234 bytes) id=att-1"
    assert atts[1].filename == ""
    assert atts[1].part_id == ""
    assert atts[1].text().startswith("part : (unnamed) (")
    assert atts[1].size == 0
    assert mime.attachments(message()["payload"]) == []


def test_body_honours_part_charset() -> None:
    import base64

    latin1 = "caf\u00e9".encode("latin-1")
    part = {
        "mimeType": "text/plain",
        "headers": [
            {"name": "Content-Type", "value": 'text/plain; charset="ISO-8859-1"'}
        ],
        "body": {"data": base64.urlsafe_b64encode(latin1).decode()},
    }
    assert mime.body_text(part, 100) == "caf\u00e9"
    assert mime.part_charset(part) == "iso8859-1"
    assert (
        mime.part_charset(
            {"headers": [{"name": "Content-Type", "value": "text/plain"}]}
        )
        == "utf-8"
    )
    bogus = {
        "headers": [{"name": "Content-Type", "value": "text/plain; charset=no-such"}]
    }
    assert mime.part_charset(bogus) == "utf-8"


def test_sender_controlled_non_text_codec_falls_back_to_utf8() -> None:
    for name in ("base64", "rot13", "zlib", "hex", "uu", "quopri", "bz2"):
        part = {
            "headers": [
                {"name": "Content-Type", "value": f"text/plain; charset={name}"}
            ]
        }
        assert mime.part_charset(part) == "utf-8", name
    assert mime.decode_body(b64("ok"), "base64") == "ok"


def test_charsets_that_reject_replace_fall_back() -> None:
    part = {"headers": [{"name": "Content-Type", "value": "text/plain; charset=idna"}]}
    assert mime.part_charset(part) == "utf-8"
    assert mime.decode_body(b64("ok"), "idna") == "ok"
    assert mime.decode_body(b64("ok"), "no-such-codec") == "ok"


def test_malformed_base64_does_not_raise() -> None:
    assert mime.decode_body("aGk") == "hi"  # unpadded
    assert mime.decode_body("!!!not base64").startswith("[body data could not")


def test_body_skips_inlined_text_attachments() -> None:
    parts = [
        {
            "mimeType": "text/plain",
            "filename": "notes.txt",
            "body": {"data": b64("att")},
        },
        {"mimeType": "text/plain", "body": {"data": b64("real body")}},
    ]
    assert mime.body_text(message(parts=parts)["payload"], 100) == "real body"
