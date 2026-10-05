"""Trash tools, registered only with WX_GMAIL_ALLOW_DELETE=true.

``trash`` and ``untrash`` move messages or whole threads into and out of
Trash. ``delete_permanently`` removes them for good, behind guardrails:
explicit ids only (no query form), at most 100 per call, only mail already
in Trash unless told otherwise, an audit trail fetched before deleting,
and a dry run by default. There is no empty-trash tool.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from mcp.server.mcpserver import MCPServer

from wx_gmail_mcp import auth, gmail
from wx_gmail_mcp.config import SCOPE_FULL
from wx_gmail_mcp.errors import WxGmailError
from wx_gmail_mcp.gmail import GmailService, Runtime, header
from wx_gmail_mcp.safety import describe_error, register_tool, require_ids

# messages.trash and threads.trash have no batch form: one API call per id.
# The same cap bounds delete_permanently, which fetches an audit line per id.
MAX_IDS = 100
KINDS = ("message", "thread")
AUDIT_HEADERS = ["From", "Subject", "Date"]

Op = Callable[[GmailService, str], dict[str, Any]]
OPS: dict[tuple[str, str], Op] = {
    ("trash", "message"): gmail.trash_message,
    ("trash", "thread"): gmail.trash_thread,
    ("untrash", "message"): gmail.untrash_message,
    ("untrash", "thread"): gmail.untrash_thread,
}


def check_kind(kind: str) -> str:
    k = kind.strip().lower()
    if k not in KINDS:
        raise WxGmailError(f"kind must be 'message' or 'thread', not {kind!r}.")
    return k


def plural(n: int, kind: str) -> str:
    return f"{n} {kind}" if n == 1 else f"{n} {kind}s"


def prepare(ids: Sequence[str], kind: str) -> tuple[list[str], str]:
    """Validated, de-duplicated ids (cap 100) and the normalized kind."""
    k = check_kind(kind)
    cleaned = require_ids(list(ids), "ids", cap=MAX_IDS)
    return list(dict.fromkeys(cleaned)), k


def for_each(svc: GmailService, ids: list[str], kind: str, action: str) -> str:
    """Run one API call per id; a failure midway keeps the count done."""
    op = OPS[(action, kind)]
    verb = f"{action.capitalize()}ed"
    done = 0
    try:
        for item in ids:
            op(svc, item)
            done += 1
    except Exception as e:
        return (
            f"{verb} {done} of {plural(len(ids), kind)} before an error on "
            f"{kind} {ids[done]}: {describe_error(e)}"
        )
    return f"{verb} {plural(done, kind)}."


def audit_line(msg: dict[str, Any]) -> str:
    """One line per message: id, date, sender, subject."""
    p = msg.get("payload", {}) or {}
    return (
        f"[{msg.get('id', '')}] {header(p, 'Date')} | From: {header(p, 'From')}"
        f" | Subj: {header(p, 'Subject')}"
    )


def is_trashed(msg: dict[str, Any]) -> bool:
    return "TRASH" in (msg.get("labelIds", []) or [])


def audit_messages(svc: GmailService, ids: list[str]) -> tuple[list[str], list[str]]:
    """Audit lines for each message, and the ids that are not in Trash."""
    lines: list[str] = []
    not_trashed: list[str] = []
    for message_id in ids:
        msg = gmail.get_message(svc, message_id, "metadata", AUDIT_HEADERS)
        lines.append(audit_line(msg))
        if not is_trashed(msg):
            not_trashed.append(message_id)
    return lines, not_trashed


def audit_threads(
    svc: GmailService, ids: list[str]
) -> tuple[list[list[str]], list[str]]:
    """Audit lines per thread (header plus one line per message), and the
    ids of threads with any message outside Trash."""
    blocks: list[list[str]] = []
    not_trashed: list[str] = []
    for thread_id in ids:
        thread = gmail.get_thread(svc, thread_id, "metadata", AUDIT_HEADERS)
        messages = thread.get("messages", []) or []
        head = f"[thread {thread_id}] {plural(len(messages), 'message')}"
        blocks.append([head, *("  " + audit_line(m) for m in messages)])
        if not all(is_trashed(m) for m in messages):
            not_trashed.append(thread_id)
    return blocks, not_trashed


def refuse_untrashed(not_trashed: list[str], kind: str) -> None:
    if not not_trashed:
        return
    where = "in Trash" if kind == "message" else "entirely in Trash"
    one = len(not_trashed) == 1
    verb, them = ("is", "it") if one else ("are", "them")
    raise WxGmailError(
        f"{plural(len(not_trashed), kind)} {verb} not {where}: "
        f"{', '.join(not_trashed)}. Trash {them} first, or pass "
        f"require_trashed=false to delete {them} anyway. Nothing was deleted."
    )


def register(mcp: MCPServer, rt: Runtime) -> None:
    def service(account: str) -> GmailService:
        # Trash and untrash would work with the base modify scope; the full
        # scope is required on purpose, so that every "mail disappears" tool
        # is an explicit opt-in per account (plan: one DELETE switch).
        auth.require_scope(rt.settings, account, rt.credentials(account), SCOPE_FULL)
        return rt.service(account)

    def trash(account: str, ids: Sequence[str], kind: str = "message") -> str:
        """Move messages (default) or whole threads (`kind='thread'`) to Trash,
        where Gmail purges them after 30 days. Up to 100 ids per call, one
        API call each. Reversible with untrash."""
        items, k = prepare(ids, kind)
        return for_each(service(account), items, k, "trash")

    def untrash(account: str, ids: Sequence[str], kind: str = "message") -> str:
        """Move messages (default) or whole threads (`kind='thread'`) out of
        Trash, back to their other labels. Up to 100 ids per call, one API
        call each."""
        items, k = prepare(ids, kind)
        return for_each(service(account), items, k, "untrash")

    def delete_permanently(
        account: str,
        ids: Sequence[str],
        kind: str = "message",
        require_trashed: bool = True,
        dry_run: bool = True,
    ) -> str:
        """Permanently delete messages (default) or whole threads
        (`kind='thread'`) by explicit id, up to 100 per call. There is no
        undo and no query form. Only mail already in Trash is accepted unless
        `require_trashed=false`. Each item's date, sender and subject are
        fetched first and returned as the audit trail. `dry_run=true` (the
        default) shows that trail and deletes nothing; run again with
        `dry_run=false` to delete. A thread is deleted whole, including a
        reply that arrives after the audit fetch."""
        items, k = prepare(ids, kind)
        svc = service(account)
        blocks: list[list[str]] = []
        if k == "message":
            lines, not_trashed = audit_messages(svc, items)
        else:
            blocks, not_trashed = audit_threads(svc, items)
            lines = [line for block in blocks for line in block]
        if require_trashed:
            refuse_untrashed(not_trashed, k)
        what = plural(len(items), k)
        if dry_run:
            return "\n".join(
                [
                    f"Dry run: {what} would be permanently deleted. Run again "
                    "with dry_run=false to delete; there is no undo.",
                    *lines,
                ]
            )
        if k == "message":
            try:
                gmail.batch_delete(svc, items)
            except Exception as e:
                head = (
                    f"Nothing was deleted: the delete of {what} failed with "
                    f"{describe_error(e)}. The items were:"
                )
                return "\n".join([head, *lines])
            return "\n".join([f"Permanently deleted {what}:", *lines])
        done = 0
        try:
            for thread_id in items:
                gmail.delete_thread(svc, thread_id)
                done += 1
        except Exception as e:
            head = (
                f"Permanently deleted {done} of {what} before an error on "
                f"thread {items[done]}: {describe_error(e)}"
            )
            deleted = [line for block in blocks[:done] for line in block]
            return "\n".join([head, *deleted])
        return "\n".join([f"Permanently deleted {what}:", *lines])

    register_tool(mcp, trash)
    register_tool(mcp, untrash)
    register_tool(mcp, delete_permanently)
