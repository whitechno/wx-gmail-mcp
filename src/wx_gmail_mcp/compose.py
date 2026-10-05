"""Compose outgoing mail for the draft and send tools.

Outbox attachments, and the planning behind ``reply`` and ``forward``:
who receives it, the subject prefix, the threading headers and the
quoted or forwarded text. ``mime.build_message`` does the encoding.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from email.utils import formataddr, getaddresses
from typing import Any

from wx_gmail_mcp import gmail, mime, safety
from wx_gmail_mcp.config import Settings
from wx_gmail_mcp.errors import WxGmailError
from wx_gmail_mcp.gmail import GmailService, header

RE_PREFIX = re.compile(r"^re\s*:", re.IGNORECASE)
FWD_PREFIX = re.compile(r"^fwd?\s*:", re.IGNORECASE)
FORWARD_RULE = "---------- Forwarded message ---------"
# Outgoing mail is not cut at the read cap; this guards against runaway
# originals only. The tools say so when it applies.
QUOTE_LIMIT = 200_000
TRUNCATED_NOTE = "[original text cut here]"


def build(
    settings: Settings,
    *,
    to: str,
    subject: str,
    body: str,
    cc: str,
    bcc: str,
    html: str,
    attachments: Sequence[str],
    reply_to: str,
    in_reply_to: str = "",
    references: str = "",
    blobs: Sequence[mime.Blob] = (),
) -> bytes:
    """Resolve outbox attachments, then build the RFC 822 message."""
    paths = [safety.outbox_path(settings, name) for name in attachments if name]
    return mime.build_message(
        to=to,
        subject=subject,
        body=body,
        cc=cc,
        bcc=bcc,
        html=html,
        attachments=paths,
        blobs=blobs,
        reply_to=reply_to,
        in_reply_to=in_reply_to,
        references=references,
    )


# --- reply and forward ------------------------------------------------------


@dataclass(frozen=True)
class Original:
    """What a reply or forward needs from the message it acts on."""

    id: str
    thread_id: str
    message_id_header: str
    references: str
    sender: str
    reply_to: str
    to: str
    cc: str
    subject: str
    date: str
    payload: dict[str, Any]

    @classmethod
    def from_message(cls, msg: dict[str, Any]) -> Original:
        p = msg.get("payload", {}) or {}
        return cls(
            id=str(msg.get("id", "") or ""),
            thread_id=str(msg.get("threadId", "") or ""),
            message_id_header=header(p, "Message-ID").strip(),
            references=header(p, "References").strip(),
            sender=header(p, "From").strip(),
            reply_to=header(p, "Reply-To").strip(),
            to=header(p, "To").strip(),
            cc=header(p, "Cc").strip(),
            subject=header(p, "Subject").strip(),
            date=header(p, "Date").strip(),
            payload=p,
        )


def load_original(svc: GmailService, message_id: str) -> Original:
    return Original.from_message(gmail.get_message(svc, message_id.strip(), "full"))


def threading_headers(orig: Original) -> tuple[str, str]:
    """``In-Reply-To`` and ``References`` that file a message in the
    original's conversation (RFC 5322 §3.6.4)."""
    mid = orig.message_id_header
    if not mid:
        return "", ""
    return mid, f"{orig.references} {mid}".strip()


def reply_subject(subject: str) -> str:
    s = subject.strip()
    return s if RE_PREFIX.match(s) else f"Re: {s}".rstrip()


def forward_subject(subject: str) -> str:
    s = subject.strip()
    return s if FWD_PREFIX.match(s) else f"Fwd: {s}".rstrip()


def _addresses(*fields: str) -> list[str]:
    return [addr for _, addr in getaddresses(list(fields)) if addr]


def reply_recipients(
    orig: Original, self_address: str, reply_all: bool
) -> tuple[str, str]:
    """``To`` and ``Cc`` for a reply.

    A reply goes to ``Reply-To``, else ``From``; when this account sent the
    original, to its ``To`` recipients instead (as the web UI does).
    ``reply_all`` copies the other ``To`` and ``Cc`` recipients, minus this
    account and anyone already in ``To``. "This account" is the profile's
    primary address; mail sent from a send-as alias counts as received.
    """
    me = self_address.strip().lower()
    sender = _addresses(orig.sender)
    from_me = bool(me) and bool(sender) and sender[0].lower() == me
    primary = orig.to if from_me else orig.reply_to
    to = primary or orig.sender
    if not reply_all:
        return to, ""
    covered = {a.lower() for a in _addresses(to)} | {me}
    cc: list[str] = []
    for name, addr in getaddresses([orig.to, orig.cc]):
        key = addr.lower()
        if not addr or key in covered:
            continue
        covered.add(key)
        cc.append(formataddr((name, addr)))
    return to, ", ".join(cc)


def join_recipients(*fields: str) -> str:
    """One header value from several, each address kept once."""
    out: list[str] = []
    seen: set[str] = set()
    for name, addr in getaddresses([f for f in fields if f.strip()]):
        if not addr or addr.lower() in seen:
            continue
        seen.add(addr.lower())
        out.append(formataddr((name, addr)))
    return ", ".join(out)


def original_text(orig: Original) -> tuple[str, bool]:
    """The original's text (HTML rendered as text), and whether it was cut."""
    text, cut = mime.plain_text(orig.payload, QUOTE_LIMIT)
    return (f"{text}\n{TRUNCATED_NOTE}" if cut else text), cut


def quoted(orig: Original) -> tuple[str, bool]:
    """The original as the web UI quotes it under a reply."""
    text, cut = original_text(orig)
    lines = text.splitlines() or [""]
    quote = "\n".join(f"> {line}" if line else ">" for line in lines)
    return f"On {orig.date}, {orig.sender} wrote:\n{quote}", cut


def forwarded(orig: Original) -> tuple[str, bool]:
    """The original under the web UI's forwarded-message header."""
    head = [
        FORWARD_RULE,
        f"From: {orig.sender}",
        f"Date: {orig.date}",
        f"Subject: {orig.subject}",
        f"To: {orig.to}",
    ]
    if orig.cc:
        head.append(f"Cc: {orig.cc}")
    text, cut = original_text(orig)
    return "\n".join(head) + "\n\n" + text, cut


def reply_body(body: str, orig: Original, quote: bool) -> tuple[str, bool]:
    text = body.rstrip()
    if not quote:
        return text, False
    block, cut = quoted(orig)
    return f"{text}\n\n{block}", cut


def forward_body(body: str, orig: Original) -> tuple[str, bool]:
    text = body.rstrip()
    block, cut = forwarded(orig)
    return (f"{text}\n\n{block}" if text else block), cut


def cut_note(cut: bool) -> str:
    if not cut:
        return ""
    return (
        f" The original text was longer than {QUOTE_LIMIT} characters and was "
        "cut; forward with as_attachment=true to pass on the whole message."
    )


def _blob_type(mime_type: str) -> tuple[str, str]:
    """Main and sub type for a re-attached part; ``message/*`` other than
    rfc822 and ``multipart/*`` cannot be attached as data."""
    if "/" not in mime_type:
        return "application", "octet-stream"
    maintype, subtype = mime_type.lower().split("/", 1)
    if maintype == "multipart" or (maintype == "message" and subtype != "rfc822"):
        return "application", "octet-stream"
    return maintype, subtype


def original_attachments(svc: GmailService, orig: Original) -> list[mime.Blob]:
    """The original's attachments, fetched for re-attaching to a forward.
    Their declared sizes are checked against the limit before any fetch."""
    # A large text body is stored out of line too (attachmentId, no name);
    # that is the body, not a file to re-attach.
    atts = [
        a
        for a in mime.attachments(orig.payload)
        if a.filename or not a.mime_type.lower().startswith("text/")
    ]
    declared = sum(a.size for a in atts)
    if declared > mime.MAX_ATTACHMENT_BYTES:
        raise WxGmailError(
            f"The original's attachments total {declared / 1_000_000:.1f} MB; "
            f"Gmail accepts up to {mime.MAX_ATTACHMENT_BYTES // 1_000_000} MB per "
            "message. Forward with include_attachments=false or as_attachment=true."
        )
    blobs: list[mime.Blob] = []
    for a in atts:
        payload = gmail.get_attachment(svc, orig.id, a.attachment_id)
        data = mime.decode_attachment(str(payload.get("data", "") or ""))
        maintype, subtype = _blob_type(a.mime_type)
        name = mime.safe_filename(a.filename, f"attachment-{a.part_id or 'x'}")
        blobs.append(mime.Blob(name, maintype, subtype, data))
    return blobs


def original_as_attachment(svc: GmailService, orig: Original) -> mime.Blob:
    """The complete original (``format=raw``) as a ``message/rfc822`` part,
    named after its subject like the web UI does."""
    msg = gmail.get_message(svc, orig.id, "raw")
    data = mime.decode_attachment(str(msg.get("raw", "") or ""))
    name = mime.safe_filename(orig.subject, "message") + ".eml"
    return mime.Blob(name, "message", "rfc822", data)
