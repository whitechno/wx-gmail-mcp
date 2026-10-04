"""Parse message payloads: bodies, attachment lists, display helpers."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

TRUNCATED_MARKER = "\n...[truncated]"


def decode_body(data: str) -> str:
    return base64.urlsafe_b64decode(data.encode()).decode("utf-8", errors="replace")


def _walk(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """All MIME parts, depth first, the payload itself first."""
    parts = [payload]
    for part in payload.get("parts", []) or []:
        parts.extend(_walk(part))
    return parts


def _first_body(payload: dict[str, Any], mime_prefix: str) -> str | None:
    for part in _walk(payload):
        if str(part.get("mimeType", "")).startswith(mime_prefix):
            data = (part.get("body") or {}).get("data")
            if data:
                return decode_body(str(data))
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
            f"{self.filename} ({self.mime_type}, {self.size} bytes) "
            f"id={self.attachment_id}"
        )


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
                filename=str(part.get("filename") or "(unnamed)"),
                mime_type=str(part.get("mimeType") or "application/octet-stream"),
                size=int(body.get("size") or 0),
            )
        )
    return found
