"""Parse message payloads, and build outgoing messages."""

from __future__ import annotations

import base64
import binascii
import codecs
import mimetypes
import re
from collections.abc import Sequence
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from wx_gmail_mcp.errors import WxGmailError

TRUNCATED_MARKER = "\n...[truncated]"


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


@dataclass(frozen=True)
class Attachment:
    attachment_id: str
    filename: str
    mime_type: str
    size: int

    def text(self) -> str:
        return (
            f"{self.filename or '(unnamed)'} ({self.mime_type}, {self.size} bytes) "
            f"id={self.attachment_id}"
        )


def decode_attachment(data: str) -> bytes:
    """Decode the base64url ``data`` of ``attachments.get``."""
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


def build_message(
    *,
    to: str,
    subject: str,
    body: str,
    cc: str = "",
    bcc: str = "",
    html: str = "",
    attachments: Sequence[Path] = (),
    reply_to: str = "",
    in_reply_to: str = "",
    references: str = "",
) -> str:
    """Build an RFC 822 message and return it base64url-encoded for Gmail.

    Gmail sets ``From`` to the authenticated account. ``html`` adds a
    text/html alternative next to the plain ``body``. ``attachments`` are
    already-validated paths (see ``safety.outbox_path``).
    """
    to = _require(to, "to")
    if not body and not html:
        raise WxGmailError("Give a body, html, or both.")
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
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")
    for path in attachments:
        maintype, subtype = attachment_type(path.name)
        msg.add_attachment(
            path.read_bytes(), maintype=maintype, subtype=subtype, filename=path.name
        )
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()
