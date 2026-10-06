"""Organize tools: modify_labels, mark_read, mark_unread, archive on id
lists; modify_thread_labels on threads; modify_by_query on a search."""

from __future__ import annotations

from collections.abc import Sequence

from mcp.server.mcpserver import MCPServer

from wx_gmail_mcp import bulk, gmail
from wx_gmail_mcp.errors import WxGmailError
from wx_gmail_mcp.gmail import Runtime
from wx_gmail_mcp.labels import DISAPPEARING_LABELS, LabelMap
from wx_gmail_mcp.safety import describe_error, register_tool, require_ids

# threads.modify has no batch form: one API call per thread.
MAX_THREAD_IDS = 100


def _plural(n: int, noun: str = "message") -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def resolve_changes(
    labels: LabelMap, add: Sequence[str], remove: Sequence[str], tool: str
) -> tuple[list[str], list[str]]:
    """Label refs to ids for a relabel; refuses an empty change and TRASH/SPAM."""
    if not add and not remove:
        raise WxGmailError("Give at least one label in `add` or `remove`.")
    add_ids = labels.resolve_all(list(add))
    remove_ids = labels.resolve_all(list(remove))
    blocked = sorted(DISAPPEARING_LABELS & set(add_ids))
    if blocked:
        raise WxGmailError(
            f"{tool} does not add {', '.join(blocked)}: that makes mail "
            "disappear. Use the trash tools, which register only with "
            "WX_GMAIL_ALLOW_DELETE=true."
        )
    return add_ids, remove_ids


def describe_changes(
    labels: LabelMap, add_ids: list[str], remove_ids: list[str]
) -> str:
    parts = []
    if add_ids:
        parts.append("added " + ", ".join(labels.names(add_ids)))
    if remove_ids:
        parts.append("removed " + ", ".join(labels.names(remove_ids)))
    return "; ".join(parts)


def register(mcp: MCPServer, rt: Runtime) -> None:
    def modify_labels(
        account: str,
        message_ids: Sequence[str],
        add: Sequence[str] = (),
        remove: Sequence[str] = (),
    ) -> str:
        """Add and/or remove labels (names or ids) on up to 1000 messages.
        Never adds TRASH or SPAM; that is the trash tools' job."""
        ids = require_ids(list(message_ids))
        svc = rt.service(account)
        labels = LabelMap.fetch(svc)
        add_ids, remove_ids = resolve_changes(labels, add, remove, "modify_labels")
        gmail.batch_modify(svc, ids, add_ids, remove_ids)
        change = describe_changes(labels, add_ids, remove_ids)
        return f"Updated {_plural(len(ids))}: {change}."

    def mark_read(account: str, message_ids: Sequence[str]) -> str:
        """Mark messages read (removes UNREAD). Up to 1000 ids per call."""
        ids = require_ids(list(message_ids))
        gmail.batch_modify(rt.service(account), ids, [], ["UNREAD"])
        return f"Marked {_plural(len(ids))} read."

    def mark_unread(account: str, message_ids: Sequence[str]) -> str:
        """Mark messages unread (adds UNREAD). Up to 1000 ids per call."""
        ids = require_ids(list(message_ids))
        gmail.batch_modify(rt.service(account), ids, ["UNREAD"], [])
        return f"Marked {_plural(len(ids))} unread."

    def archive(account: str, message_ids: Sequence[str]) -> str:
        """Archive messages (removes INBOX; nothing is deleted). Up to 1000
        ids per call."""
        ids = require_ids(list(message_ids))
        gmail.batch_modify(rt.service(account), ids, [], ["INBOX"])
        return f"Archived {_plural(len(ids))}."

    def modify_thread_labels(
        account: str,
        thread_ids: Sequence[str],
        add: Sequence[str] = (),
        remove: Sequence[str] = (),
    ) -> str:
        """Add and/or remove labels (names or ids) on whole threads, every
        message included. Up to 100 thread ids per call (one API call each).
        Never adds TRASH or SPAM."""
        ids = require_ids(list(thread_ids), "thread_ids", cap=MAX_THREAD_IDS)
        svc = rt.service(account)
        labels = LabelMap.fetch(svc)
        add_ids, remove_ids = resolve_changes(
            labels, add, remove, "modify_thread_labels"
        )
        change = describe_changes(labels, add_ids, remove_ids)
        done = 0
        try:
            for thread_id in ids:
                gmail.modify_thread(svc, thread_id, add_ids, remove_ids)
                done += 1
        except Exception as e:  # keep the count of threads already done
            return (
                f"Updated {done} of {_plural(len(ids), 'thread')} before an "
                f"error on thread {ids[done]}: {describe_error(e)}"
            )
        return f"Updated {_plural(len(ids), 'thread')}: {change}."

    def modify_by_query(
        account: str,
        query: str,
        add: Sequence[str] = (),
        remove: Sequence[str] = (),
        dry_run: bool = True,
        limit: int = bulk.DEFAULT_LIMIT,
    ) -> str:
        """Add and/or remove labels (names or ids) on every message matching
        a Gmail query (Spam and Trash only if the query names them).
        `dry_run=true` (default) counts the matches with a 5-message sample;
        fails above `limit` (default 5000). Never adds TRASH or SPAM."""
        svc = rt.service(account)
        labels = LabelMap.fetch(svc)
        add_ids, remove_ids = resolve_changes(labels, add, remove, "modify_by_query")
        report = bulk.relabel_by_query(
            svc, query, add_ids, remove_ids, limit=limit, dry_run=dry_run
        )
        return report.text(describe_changes(labels, add_ids, remove_ids))

    register_tool(mcp, modify_labels)
    register_tool(mcp, mark_read)
    register_tool(mcp, mark_unread)
    register_tool(mcp, archive)
    register_tool(mcp, modify_thread_labels)
    register_tool(mcp, modify_by_query)
