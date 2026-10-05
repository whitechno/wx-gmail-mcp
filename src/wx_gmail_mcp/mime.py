"""Parse message payloads, and build outgoing messages."""

from __future__ import annotations

import base64
import binascii
import codecs
import mimetypes
import re
from collections.abc import Sequence
from dataclasses import dataclass
from email import message_from_bytes, policy
from email.message import EmailMessage
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from wx_gmail_mcp.errors import WxGmailError

TRUNCATED_MARKER = "\n...[truncated]"
# Gmail refuses messages whose attachments exceed 25 MB; base64 inflates
# that to about 34 MB of upload, under the API's 35 MB cap.
MAX_ATTACHMENT_BYTES = 25_000_000


_CHARSET_RE = re.compile(r"charset\s*=\s*\"?([\w.:+-]+)\"?", re.IGNORECASE)


def _text_codec(name: str) -> str | None:
    """Canonical name if ``name`` is a text encoding, else None.

    ``codecs.lookup`` also knows bytes-to-bytes codecs (base64, zlib, ...);
    encoding a str with one of those raises LookupError, which rules it out.
    """
    try:
        info = codecs.lookup(name)
        "a".encode(name)
        b"\xff".decode(name, errors="replace")  # idna rejects non-strict modes
    except LookupError, ValueError, UnicodeError:
        return None
    return info.name


def part_charset(part: dict[str, Any]) -> str:
    """The charset named in the part's Content-Type header, else UTF-8.

    The header comes from the sender, so anything unknown or not a text
    encoding falls back to UTF-8.
    """
    for h in part.get("headers", []) or []:
        if str(h.get("name", "")).lower() == "content-type":
            m = _CHARSET_RE.search(str(h.get("value", "")))
            if m and (codec := _text_codec(m.group(1))):
                return codec
            break
    return "utf-8"


def decode_body(data: str, charset: str = "utf-8") -> str:
    """Decode Gmail's base64url body data; never raises on sender input."""
    try:
        raw = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
    except binascii.Error, ValueError:
        return "[body data could not be decoded]"
    try:
        return raw.decode(charset, errors="replace")
    except LookupError, ValueError, UnicodeError:
        return raw.decode("utf-8", errors="replace")


def _walk(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """All MIME parts, depth first, the payload itself first."""
    parts = [payload]
    for part in payload.get("parts", []) or []:
        parts.extend(_walk(part))
    return parts


def _first_body(payload: dict[str, Any], mime_prefix: str) -> str | None:
    for part in _walk(payload):
        if part.get("filename"):
            continue  # an inlined text attachment is not the body
        if str(part.get("mimeType", "")).startswith(mime_prefix):
            data = (part.get("body") or {}).get("data")
            if data:
                return decode_body(str(data), part_charset(part))
    return None


def body_text(payload: dict[str, Any], max_body: int) -> str:
    """Plain text if present, else HTML as is, truncated to ``max_body``."""
    text = _first_body(payload, "text/plain") or _first_body(payload, "text/html")
    text = text or ""
    if len(text) > max_body:
        text = text[:max_body] + TRUNCATED_MARKER
    return text


_BLOCK_TAGS = frozenset(
    {
        "p",
        "div",
        "br",
        "li",
        "tr",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "blockquote",
        "pre",
        "table",
        "ul",
        "ol",
        "hr",
        "section",
        "article",
        "header",
        "footer",
    }
)
_SKIP_TAGS = frozenset({"script", "style", "head", "title"})


class _TextExtractor(HTMLParser):
    """Visible text of an HTML body: block tags become line breaks, script
    and style content is dropped, entities are decoded."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n- " if tag == "li" else "\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
        elif tag in _BLOCK_TAGS and tag not in ("br", "li"):
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    """A plain-text rendering of HTML, for quoting an HTML-only original."""
    extractor = _TextExtractor()
    extractor.feed(html)
    extractor.close()
    lines = [
        re.sub(r"[ \t\xa0]+", " ", line).strip()
        for line in "".join(extractor.parts).splitlines()
    ]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def plain_text(payload: dict[str, Any], max_chars: int) -> tuple[str, bool]:
    """The original's text for outgoing mail: the text/plain part, else the
    HTML part rendered as text. Returns the text and whether it was cut."""
    text = _first_body(payload, "text/plain")
    if text is None:
        html = _first_body(payload, "text/html")
        text = html_to_text(html) if html else ""
    if len(text) > max_chars:
        return text[:max_chars], True
    return text, False


@dataclass(frozen=True)
class Attachment:
    """One attachment part. ``part_id`` is stable for the message; Gmail's
    ``attachment_id`` can change between reads of the same message."""

    attachment_id: str
    filename: str
    mime_type: str
    size: int
    part_id: str = ""

    def text(self) -> str:
        return (
            f"part {self.part_id}: {self.filename or '(unnamed)'} "
            f"({self.mime_type}, {self.size} bytes) id={self.attachment_id}"
        )


def decode_attachment(data: str) -> bytes:
    """Decode base64url ``data`` from ``attachments.get`` or a ``raw``
    message."""
    try:
        return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
    except (binascii.Error, ValueError) as e:
        raise WxGmailError(f"Attachment data could not be decoded: {e}") from e


_UNSAFE_CHARS_RE = re.compile(r"[\x00-\x1f\x7f\\/:*?\"<>|]+")


def safe_filename(name: str, fallback: str) -> str:
    """A sender-supplied file name reduced to one plain path component.

    Directory parts, control and path characters go; leading dots and
    spaces go too, so the result is neither hidden nor a traversal.
    """
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    base = _UNSAFE_CHARS_RE.sub("_", base).strip(" .")
    return base or fallback


def attachments(payload: dict[str, Any]) -> list[Attachment]:
    """Parts that carry an attachment id (Gmail stores them separately)."""
    found: list[Attachment] = []
    for part in _walk(payload):
        body = part.get("body") or {}
        attachment_id = body.get("attachmentId")
        if not attachment_id:
            continue
        found.append(
            Attachment(
                attachment_id=str(attachment_id),
                filename=str(part.get("filename") or ""),
                mime_type=str(part.get("mimeType") or "application/octet-stream"),
                size=int(body.get("size") or 0),
                part_id=str(part.get("partId") or ""),
            )
        )
    return found


# --- building outgoing messages ---------------------------------------------


def _require(value: str, what: str) -> str:
    if not value or not value.strip():
        raise WxGmailError(f"{what} is required.")
    return value.strip()


def attachment_type(filename: str) -> tuple[str, str]:
    """MIME main and sub type for an attachment, from its name.

    Compressed files (``.gz``, ``.bz2``, ...) and ``message/*`` go as
    ``application/octet-stream``: ``guess_type`` reports the inner type of
    compressed files, and message parts must not be base64-encoded.
    """
    ctype, encoding = mimetypes.guess_type(filename)
    if ctype is None or encoding is not None or ctype.startswith("message/"):
        return "application", "octet-stream"
    maintype, subtype = ctype.split("/", 1)
    return maintype, subtype


@dataclass(frozen=True)
class Blob:
    """An attachment held in memory: a re-attached original attachment, or
    a whole message (``message/rfc822``) when forwarding as attachment."""

    filename: str
    maintype: str
    subtype: str
    data: bytes


def _attach_blob(msg: EmailMessage, blob: Blob) -> None:
    if (blob.maintype, blob.subtype) == ("message", "rfc822"):
        # A message part is nested, not base64-encoded (RFC 2046 §5.2.1).
        inner = message_from_bytes(blob.data, policy=policy.default)
        msg.add_attachment(inner, filename=blob.filename)
        return
    msg.add_attachment(
        blob.data,
        maintype=blob.maintype,
        subtype=blob.subtype,
        filename=blob.filename,
    )


def check_attachment_size(attachments: Sequence[Path], blobs: Sequence[Blob]) -> int:
    """Total attachment bytes, or an error above Gmail's 25 MB limit."""
    total = sum(p.stat().st_size for p in attachments) + sum(len(b.data) for b in blobs)
    if total > MAX_ATTACHMENT_BYTES:
        raise WxGmailError(
            f"Attachments total {total / 1_000_000:.1f} MB; Gmail accepts up to "
            f"{MAX_ATTACHMENT_BYTES // 1_000_000} MB per message."
        )
    return total


def build_message(
    *,
    to: str,
    subject: str,
    body: str,
    cc: str = "",
    bcc: str = "",
    html: str = "",
    attachments: Sequence[Path] = (),
    blobs: Sequence[Blob] = (),
    reply_to: str = "",
    in_reply_to: str = "",
    references: str = "",
) -> bytes:
    """Build an RFC 822 message as bytes, for a ``message/rfc822`` upload.

    Gmail sets ``From`` to the authenticated account. ``html`` adds a
    text/html alternative next to the plain ``body`` (or is the only part
    when ``body`` is empty). ``attachments`` are already-validated paths
    (see ``safety.outbox_path``); ``blobs`` are in-memory attachments added
    after them. Together they may not exceed ``MAX_ATTACHMENT_BYTES``.
    """
    to = _require(to, "to")
    if not body and not html:
        raise WxGmailError("Give a body, html, or both.")
    check_attachment_size(attachments, blobs)
    msg = EmailMessage()
    msg["To"] = to
    msg["Subject"] = subject
    if cc.strip():
        msg["Cc"] = cc.strip()
    if bcc.strip():
        msg["Bcc"] = bcc.strip()
    if reply_to.strip():
        msg["Reply-To"] = reply_to.strip()
    if in_reply_to.strip():
        msg["In-Reply-To"] = in_reply_to.strip()
    if references.strip():
        msg["References"] = references.strip()
    if body:
        msg.set_content(body)
        if html:
            msg.add_alternative(html, subtype="html")
    else:
        msg.set_content(html, subtype="html")
    for path in attachments:
        maintype, subtype = attachment_type(path.name)
        msg.add_attachment(
            path.read_bytes(), maintype=maintype, subtype=subtype, filename=path.name
        )
    for blob in blobs:
        _attach_blob(msg, blob)
    return msg.as_bytes()
