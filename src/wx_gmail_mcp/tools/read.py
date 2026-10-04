"""Read tools: search, read_message, read_thread."""

from __future__ import annotations

import html
from typing import Any

from mcp.server.mcpserver import MCPServer

from wx_gmail_mcp import gmail, mime
from wx_gmail_mcp.gmail import Runtime, header
from wx_gmail_mcp.labels import LabelMap
from wx_gmail_mcp.safety import register_tool

MAX_SEARCH_RESULTS = 100


def _labels_line(labels: LabelMap, msg: dict[str, Any]) -> str:
    return ", ".join(labels.names(list(msg.get("labelIds", []) or []))) or "(none)"


def format_hit(labels: LabelMap, msg: dict[str, Any]) -> str:
    p = msg.get("payload", {}) or {}
    thread = msg.get("threadId", "")
    return (
        f"[{msg.get('id', '')}] {header(p, 'Date')} | thread {thread}\n"
        f"  From: {header(p, 'From')}\n"
        f"  Subj: {header(p, 'Subject')}\n"
        f"  Labels: {_labels_line(labels, msg)}\n"
        f"  {html.unescape(str(msg.get('snippet', '') or ''))}"
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


def register(mcp: MCPServer, rt: Runtime) -> None:
    def search(
        account: str,
        query: str,
        max_results: int = 10,
        page_token: str = "",
        include_spam_trash: bool = False,
    ) -> str:
        """Search one account with Gmail query syntax, e.g.
        'from:someone@example.com newer_than:30d is:unread'. Returns per hit:
        message id, date, thread id, from, subject, labels, snippet, and a
        next_page_token line when more pages exist (pass it as page_token)."""
        if not 1 <= max_results <= MAX_SEARCH_RESULTS:
            return f"Error: max_results must be between 1 and {MAX_SEARCH_RESULTS}."
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
                gmail.get_message(
                    svc, str(m["id"]), "metadata", ["From", "Subject", "Date"]
                ),
            )
            for m in hits
        ]
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

    register_tool(mcp, search)
    register_tool(mcp, read_message)
    register_tool(mcp, read_thread)
