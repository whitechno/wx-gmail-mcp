"""Organize tools: modify_labels, mark_read, mark_unread, archive.

Each takes a list of message ids and runs one batchModify per 1000 ids.
"""

from __future__ import annotations

from collections.abc import Sequence

from mcp.server.mcpserver import MCPServer

from wx_gmail_mcp import gmail
from wx_gmail_mcp.errors import WxGmailError
from wx_gmail_mcp.gmail import Runtime
from wx_gmail_mcp.labels import LabelMap
from wx_gmail_mcp.safety import register_tool, require_ids

# Adding these makes mail disappear (Gmail purges Trash and Spam after 30
# days). That is a trash action, which lives behind WX_GMAIL_ALLOW_DELETE.
DISAPPEARING_LABELS = frozenset({"TRASH", "SPAM"})


def _plural(n: int) -> str:
    return f"{n} message" if n == 1 else f"{n} messages"


def register(mcp: MCPServer, rt: Runtime) -> None:
    def modify_labels(
        account: str,
        message_ids: Sequence[str],
        add: Sequence[str] = (),
        remove: Sequence[str] = (),
    ) -> str:
        """Add and/or remove labels (names or ids) on a list of messages, e.g.
        add=['STARRED'] or remove=['INBOX']. Up to 1000 ids per call. Never
        adds TRASH or SPAM; that is the trash tools' job."""
        ids = require_ids(list(message_ids))
        if not add and not remove:
            raise WxGmailError("Give at least one label to add or remove.")
        svc = rt.service(account)
        labels = LabelMap.fetch(svc)
        add_ids = labels.resolve_all(list(add))
        remove_ids = labels.resolve_all(list(remove))
        blocked = sorted(DISAPPEARING_LABELS & set(add_ids))
        if blocked:
            raise WxGmailError(
                f"modify_labels does not add {', '.join(blocked)}: that makes mail "
                "disappear. Use the trash tools, which register only with "
                "WX_GMAIL_ALLOW_DELETE=true."
            )
        gmail.batch_modify(svc, ids, add_ids, remove_ids)
        parts = []
        if add_ids:
            parts.append("added " + ", ".join(labels.names(add_ids)))
        if remove_ids:
            parts.append("removed " + ", ".join(labels.names(remove_ids)))
        return f"Updated {_plural(len(ids))}: {'; '.join(parts)}."

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

    register_tool(mcp, modify_labels)
    register_tool(mcp, mark_read)
    register_tool(mcp, mark_unread)
    register_tool(mcp, archive)
