"""Read tools: search, search_threads, read_message, read_thread,
list_attachments, download_attachment."""

from __future__ import annotations

import html
from typing import Any

from googleapiclient.errors import HttpError
from mcp.server.mcpserver import MCPServer

from wx_gmail_mcp import gmail, mime, safety
from wx_gmail_mcp.errors import WxGmailError
from wx_gmail_mcp.gmail import Runtime, header
from wx_gmail_mcp.labels import LabelMap
from wx_gmail_mcp.safety import register_tool

MAX_SEARCH_RESULTS = 100
METADATA_HEADERS = ["From", "Subject", "Date"]


def _labels_line(labels: LabelMap, msg: dict[str, Any]) -> str:
    return ", ".join(labels.names(list(msg.get("labelIds", []) or []))) or "(none)"


def _snippet(resource: dict[str, Any]) -> str:
    return html.unescape(str(resource.get("snippet", "") or ""))


def format_hit(labels: LabelMap, msg: dict[str, Any]) -> str:
    p = msg.get("payload", {}) or {}
    thread = msg.get("threadId", "")
    return (
        f"[{msg.get('id', '')}] {header(p, 'Date')} | thread {thread}\n"
        f"  From: {header(p, 'From')}\n"
        f"  Subj: {header(p, 'Subject')}\n"
        f"  Labels: {_labels_line(labels, msg)}\n"
        f"  {_snippet(msg)}"
    )


def format_thread_hit(labels: LabelMap, thread: dict[str, Any]) -> str:
    """One thread from ``threads.get`` (metadata): last message's headers,
    the union of labels, the thread's own snippet."""
    messages = thread.get("messages", []) or []
    last = messages[-1] if messages else {}
    p = last.get("payload", {}) or {}
    label_ids: list[str] = []
    for m in messages:
        for label_id in m.get("labelIds", []) or []:
            if label_id not in label_ids:
                label_ids.append(str(label_id))
    n = len(messages)
    count = f"{n} message" if n == 1 else f"{n} messages"
    return (
        f"[thread {thread.get('id', '')}] {count} | last {header(p, 'Date')}\n"
        f"  From: {header(p, 'From')}\n"
        f"  Subj: {header(p, 'Subject')}\n"
        f"  Labels: {', '.join(labels.names(label_ids)) or '(none)'}\n"
        f"  {_snippet(thread) or _snippet(last)}"
    )


def format_message(labels: LabelMap, msg: dict[str, Any], max_body: int) -> str:
    p = msg.get("payload", {}) or {}
    lines = [
        f"Message id: {msg.get('id', '')}",
        f"Thread id: {msg.get('threadId', '')}",
        f"Date: {header(p, 'Date')}",
        f"From: {header(p, 'From')}",
        f"To: {header(p, 'To')}",
    ]
    if cc := header(p, "Cc"):
        lines.append(f"Cc: {cc}")
    lines.append(f"Subject: {header(p, 'Subject')}")
    lines.append(f"Labels: {_labels_line(labels, msg)}")
    atts = mime.attachments(p)
    if atts:
        lines.append("Attachments:")
        lines.extend(f"  - {a.text()}" for a in atts)
    lines.append("")
    lines.append(mime.body_text(p, max_body))
    return "\n".join(lines)


def format_thread_message(labels: LabelMap, msg: dict[str, Any], max_body: int) -> str:
    p = msg.get("payload", {}) or {}
    return (
        f"--- [{msg.get('id', '')}] {header(p, 'Date')} | {header(p, 'From')}\n"
        f"Subject: {header(p, 'Subject')}\n"
        f"Labels: {_labels_line(labels, msg)}\n"
        f"{mime.body_text(p, max_body)}"
    )


def pick_attachment(atts: list[mime.Attachment], ref: str) -> mime.Attachment | None:
    """The attachment ``ref`` names by part number, attachment id or file
    name; the only one if ``ref`` is empty.

    Returns None when ``ref`` matches nothing: Gmail attachment ids change
    between reads of a message, so the caller then tries ``ref`` as an id
    from an earlier read, which ``attachments.get`` still accepts.
    """
    if not atts:
        raise WxGmailError("The message has no attachments.")
    ref = ref.strip()
    if not ref:
        if len(atts) == 1:
            return atts[0]
        raise WxGmailError(
            f"The message has {len(atts)} attachments; pick one by part number "
            "or file name."
        )
    for a in atts:
        if ref in (a.part_id, a.attachment_id):
            return a
    by_name = [a for a in atts if a.filename.lower() == ref.lower()]
    if len(by_name) == 1:
        return by_name[0]
    if len(by_name) > 1:
        raise WxGmailError(
            f"{len(by_name)} attachments are named '{ref}'; use the part number."
        )
    return None


def no_such_attachment(atts: list[mime.Attachment], ref: str) -> WxGmailError:
    return WxGmailError(
        f"No attachment '{ref}' on this message. Attachments: "
        + "; ".join(a.text() for a in atts)
    )


def _match_by_size(atts: list[mime.Attachment], size: int) -> mime.Attachment | None:
    """The one attachment of this size, to name a file fetched by a stale id."""
    same = [a for a in atts if a.size == size]
    return same[0] if len(same) == 1 else None


def _check_max_results(max_results: int) -> None:
    if not 1 <= max_results <= MAX_SEARCH_RESULTS:
        raise WxGmailError(f"max_results must be between 1 and {MAX_SEARCH_RESULTS}.")


def register(mcp: MCPServer, rt: Runtime) -> None:
    def search(
        account: str,
        query: str,
        max_results: int = 10,
        page_token: str = "",
        include_spam_trash: bool = False,
    ) -> str:
        """Search one account with Gmail query syntax. Per hit: message id,
        date, thread id, from, subject, labels, snippet; a next_page_token line
        when more pages exist (pass it as page_token)."""
        _check_max_results(max_results)
        svc = rt.service(account)
        page = gmail.list_messages(
            svc, query, max_results, page_token, include_spam_trash
        )
        hits = page.get("messages", []) or []
        if not hits:
            return "No messages matched."
        labels = LabelMap.fetch(svc)
        out = [
            format_hit(
                labels,
                gmail.get_message(svc, str(m["id"]), "metadata", METADATA_HEADERS),
            )
            for m in hits
        ]
        if token := page.get("nextPageToken"):
            out.append(f"next_page_token: {token}")
        return "\n\n".join(out)

    def search_threads(
        account: str,
        query: str,
        max_results: int = 10,
        page_token: str = "",
        include_spam_trash: bool = False,
    ) -> str:
        """Search conversations (same query syntax as search). Per thread:
        thread id, message count, the last message's date, from and subject,
        labels, snippet; a next_page_token line when more pages exist."""
        _check_max_results(max_results)
        svc = rt.service(account)
        page = gmail.list_threads(
            svc, query, max_results, page_token, include_spam_trash
        )
        hits = page.get("threads", []) or []
        if not hits:
            return "No threads matched."
        labels = LabelMap.fetch(svc)
        out = []
        for t in hits:
            thread = gmail.get_thread(svc, str(t["id"]), "metadata", METADATA_HEADERS)
            # threads.list documents the snippet; threads.get may omit it.
            thread["snippet"] = t.get("snippet") or thread.get("snippet", "")
            out.append(format_thread_hit(labels, thread))
        if token := page.get("nextPageToken"):
            out.append(f"next_page_token: {token}")
        return "\n\n".join(out)

    def read_message(account: str, message_id: str) -> str:
        """Read one message: ids, headers (incl. Cc), labels, attachment list
        and the decoded plain-text body (HTML if there is no text part)."""
        svc = rt.service(account)
        msg = gmail.get_message(svc, message_id, "full")
        return format_message(LabelMap.fetch(svc), msg, rt.settings.max_body)

    def read_thread(account: str, thread_id: str, max_body: int = 0) -> str:
        """Read every message in a thread, oldest first, each with its id,
        headers, labels and body. `max_body` caps each body in characters
        (0 = the server default)."""
        svc = rt.service(account)
        thread = gmail.get_thread(svc, thread_id, "full")
        messages = thread.get("messages", []) or []
        if not messages:
            return "Empty thread."
        labels = LabelMap.fetch(svc)
        cap = max_body if max_body > 0 else rt.settings.max_body
        return "\n\n".join(format_thread_message(labels, m, cap) for m in messages)

    def list_attachments(account: str, message_id: str) -> str:
        """List a message's attachments: part number, file name, MIME type,
        size, attachment id. Use the part number or file name with
        download_attachment (ids change between reads)."""
        msg = gmail.get_message(rt.service(account), message_id, "full")
        atts = mime.attachments(msg.get("payload", {}) or {})
        if not atts:
            return "No attachments."
        return "\n".join(a.text() for a in atts)

    def download_attachment(
        account: str,
        message_id: str,
        attachment: str = "",
        filename: str = "",
        overwrite: bool = False,
    ) -> str:
        """Save one attachment to the server's downloads directory and return
        the path. `attachment` is a part number, file name or attachment id
        (optional when there is exactly one); `filename` renames the saved
        file (relative, subfolders allowed)."""
        svc = rt.service(account)
        msg = gmail.get_message(svc, message_id, "full")
        atts = mime.attachments(msg.get("payload", {}) or {})
        ref = attachment.strip()
        att = pick_attachment(atts, ref)
        if att is not None:
            payload = gmail.get_attachment(svc, message_id, att.attachment_id)
        else:
            # Not a current id, part or name: maybe an id from an earlier read.
            try:
                payload = gmail.get_attachment(svc, message_id, ref)
            except HttpError as e:
                if e.resp.status in (400, 404):  # Gmail rejected the id itself
                    raise no_such_attachment(atts, ref) from None
                raise
            att = _match_by_size(atts, int(payload.get("size") or -1)) or (
                mime.Attachment(ref, "", "application/octet-stream", 0)
            )
        data = mime.decode_attachment(str(payload.get("data", "")))
        name = filename.strip() or mime.safe_filename(
            att.filename, f"{message_id}-attachment.bin"
        )
        path = safety.write_download(rt.settings, name, data, overwrite)
        return f"Saved {path} ({len(data)} bytes, {att.mime_type})."

    register_tool(mcp, search)
    register_tool(mcp, search_threads)
    register_tool(mcp, read_message)
    register_tool(mcp, read_thread)
    register_tool(mcp, list_attachments)
    register_tool(mcp, download_attachment)
