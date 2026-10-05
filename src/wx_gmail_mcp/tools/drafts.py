"""Draft tools, always on: create, list, get, update, delete.

Drafts need only the base scope. Sending one is ``send_draft`` in
``tools/send.py``, behind the SEND gate.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from googleapiclient.errors import HttpError
from mcp.server.mcpserver import MCPServer

from wx_gmail_mcp import compose, gmail, mime
from wx_gmail_mcp.errors import WxGmailError
from wx_gmail_mcp.gmail import GmailService, Runtime, header
from wx_gmail_mcp.safety import describe_error, register_tool, require_ids

MAX_LIST_RESULTS = 100
# drafts.delete has no batch form: one API call per id.
MAX_IDS = 100
LIST_HEADERS = ["To", "Subject", "Date"]
# Shown by get_draft when present, after To.
OPTIONAL_HEADERS = ("Cc", "Bcc", "Reply-To", "In-Reply-To")


def draft_line(draft_id: str, msg: dict[str, Any]) -> str:
    """One list entry: draft id, message and thread ids, date, To, subject."""
    p = msg.get("payload", {}) or {}
    return (
        f"[draft {draft_id}] message {msg.get('id', '')} | "
        f"thread {msg.get('threadId', '')} | {header(p, 'Date')}\n"
        f"  To: {header(p, 'To')}\n"
        f"  Subj: {header(p, 'Subject')}"
    )


def format_draft(draft: dict[str, Any], max_body: int) -> str:
    msg = draft.get("message", {}) or {}
    p = msg.get("payload", {}) or {}
    lines = [
        f"Draft id: {draft.get('id', '')}",
        f"Message id: {msg.get('id', '')}",
        f"Thread id: {msg.get('threadId', '')}",
        f"Date: {header(p, 'Date')}",
        f"To: {header(p, 'To')}",
    ]
    lines.extend(f"{name}: {v}" for name in OPTIONAL_HEADERS if (v := header(p, name)))
    lines.append(f"Subject: {header(p, 'Subject')}")
    atts = mime.attachments(p)
    if atts:
        lines.append("Attachments:")
        lines.extend(f"  - {a.text()}" for a in atts)
    lines.append("")
    lines.append(mime.body_text(p, max_body))
    return "\n".join(lines)


def thread_context(draft: dict[str, Any]) -> tuple[str, str, str]:
    """The thread id, In-Reply-To and References of an existing draft, so an
    update keeps a reply draft in its conversation."""
    msg = draft.get("message", {}) or {}
    p = msg.get("payload", {}) or {}
    return (
        str(msg.get("threadId", "") or ""),
        header(p, "In-Reply-To"),
        header(p, "References"),
    )


def delete_each(svc: GmailService, ids: list[str]) -> str:
    """One ``drafts.delete`` per id; a failure midway keeps the count done."""
    done = 0
    try:
        for draft_id in ids:
            gmail.delete_draft(svc, draft_id)
            done += 1
    except Exception as e:
        return (
            f"Deleted {done} of {plural(len(ids))} before an error on draft "
            f"{ids[done]}: {describe_error(e)}"
        )
    return f"Deleted {plural(done)}."


def plural(n: int) -> str:
    return "1 draft" if n == 1 else f"{n} drafts"


def register(mcp: MCPServer, rt: Runtime) -> None:
    def create_draft(
        account: str,
        to: str,
        subject: str,
        body: str,
        cc: str = "",
        bcc: str = "",
        html: str = "",
        attachments: Sequence[str] = (),
        reply_to: str = "",
    ) -> str:
        """Create a draft (nothing is sent). `html` adds an HTML alternative
        to the plain `body`; `attachments` are file names inside the server's
        outbox directory. Returns the draft id and message id."""
        data = compose.build(
            rt.settings,
            to=to,
            subject=subject,
            body=body,
            cc=cc,
            bcc=bcc,
            html=html,
            attachments=attachments,
            reply_to=reply_to,
        )
        draft = gmail.create_draft(rt.service(account), data)
        message = draft.get("message", {}) or {}
        return (
            f"Draft created. draft id={draft.get('id', '')} "
            f"message id={message.get('id', '')}"
        )

    def list_drafts(
        account: str, query: str = "", max_results: int = 20, page_token: str = ""
    ) -> str:
        """List drafts, newest first: draft id, message and thread ids, date,
        To and subject. `query` uses Gmail search syntax; a next_page_token
        line appears when more exist (pass it as page_token)."""
        if not 1 <= max_results <= MAX_LIST_RESULTS:
            raise WxGmailError(f"max_results must be between 1 and {MAX_LIST_RESULTS}.")
        svc = rt.service(account)
        page = gmail.list_drafts(svc, query.strip(), max_results, page_token.strip())
        drafts = page.get("drafts", []) or []
        if not drafts:
            return "No drafts."
        out = []
        for d in drafts:
            draft_id = str(d.get("id", ""))
            message_id = str((d.get("message", {}) or {}).get("id", ""))
            try:
                msg = gmail.get_message(svc, message_id, "metadata", LIST_HEADERS)
            except HttpError as e:
                if e.resp.status != 404:
                    raise
                # Deleted between the list call and this one.
                out.append(f"[draft {draft_id}] message {message_id} | (gone)")
                continue
            out.append(draft_line(draft_id, msg))
        if token := page.get("nextPageToken"):
            out.append(f"next_page_token: {token}")
        return "\n\n".join(out)

    def get_draft(account: str, draft_id: str, max_body: int = 0) -> str:
        """Read one draft: ids, headers, attachment list and the body.
        `max_body` caps the body in characters (0 = the server default)."""
        draft = gmail.get_draft(rt.service(account), draft_id.strip(), "full")
        cap = max_body if max_body > 0 else rt.settings.max_body
        return format_draft(draft, cap)

    def update_draft(
        account: str,
        draft_id: str,
        to: str,
        subject: str,
        body: str,
        cc: str = "",
        bcc: str = "",
        html: str = "",
        attachments: Sequence[str] = (),
        reply_to: str = "",
    ) -> str:
        """Replace a draft's content with these fields (same as create_draft;
        anything not given is dropped, attachments included). A reply draft
        keeps its thread and reply headers, so it stays in its conversation
        as long as the subject still matches. Nothing is sent."""
        svc = rt.service(account)
        draft_id = draft_id.strip()
        existing = gmail.get_draft(svc, draft_id, "metadata")
        thread_id, in_reply_to, references = thread_context(existing)
        data = compose.build(
            rt.settings,
            to=to,
            subject=subject,
            body=body,
            cc=cc,
            bcc=bcc,
            html=html,
            attachments=attachments,
            reply_to=reply_to,
            in_reply_to=in_reply_to,
            references=references,
        )
        draft = gmail.update_draft(svc, draft_id, data, thread_id)
        message = draft.get("message", {}) or {}
        return (
            f"Draft updated. draft id={draft.get('id', '')} "
            f"message id={message.get('id', '')}"
        )

    def delete_draft(account: str, draft_ids: Sequence[str]) -> str:
        """Delete unsent drafts by id, up to 100 per call, one API call each.
        Permanent: Gmail has no Trash for drafts. Sent and received mail is
        never affected."""
        ids = list(dict.fromkeys(require_ids(list(draft_ids), "draft_ids", MAX_IDS)))
        return delete_each(rt.service(account), ids)

    register_tool(mcp, create_draft)
    register_tool(mcp, list_drafts)
    register_tool(mcp, get_draft)
    register_tool(mcp, update_draft)
    register_tool(mcp, delete_draft)
