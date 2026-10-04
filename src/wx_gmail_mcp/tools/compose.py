"""Shared input handling for the draft and send tools."""

from __future__ import annotations

from collections.abc import Sequence

from wx_gmail_mcp import mime, safety
from wx_gmail_mcp.config import Settings


def build_raw(
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
) -> str:
    """Resolve outbox attachments, then build the raw message."""
    paths = [safety.outbox_path(settings, name) for name in attachments if name]
    return mime.build_message(
        to=to,
        subject=subject,
        body=body,
        cc=cc,
        bcc=bcc,
        html=html,
        attachments=paths,
        reply_to=reply_to,
    )
