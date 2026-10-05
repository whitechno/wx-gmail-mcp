"""Trash tools, registered only with WX_GMAIL_ALLOW_DELETE=true.

``trash`` and ``untrash`` move messages or whole threads into and out of
Trash. Permanent deletion follows in its own module slice.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from mcp.server.mcpserver import MCPServer

from wx_gmail_mcp import auth, gmail
from wx_gmail_mcp.config import SCOPE_FULL
from wx_gmail_mcp.errors import WxGmailError
from wx_gmail_mcp.gmail import GmailService, Runtime
from wx_gmail_mcp.safety import describe_error, register_tool, require_ids

# messages.trash and threads.trash have no batch form: one API call per id.
MAX_IDS = 100
KINDS = ("message", "thread")

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


def register(mcp: MCPServer, rt: Runtime) -> None:
    def service(account: str) -> GmailService:
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

    register_tool(mcp, trash)
    register_tool(mcp, untrash)
