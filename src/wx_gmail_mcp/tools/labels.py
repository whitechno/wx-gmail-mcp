"""Label tools. Phase 2 ports list_labels; create/update/delete follow."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from wx_gmail_mcp import gmail
from wx_gmail_mcp.gmail import Runtime
from wx_gmail_mcp.safety import register_tool


def format_label(label: dict[str, Any], counts: bool) -> str:
    line = f"{label.get('id', '')}: {label.get('name', '')} [{label.get('type', '')}]"
    if counts:
        line += (
            f" messages={label.get('messagesTotal', 0)}"
            f" unread={label.get('messagesUnread', 0)}"
            f" threads={label.get('threadsTotal', 0)}"
        )
    return line


def register(mcp: MCPServer, rt: Runtime) -> None:
    def list_labels(account: str, include_counts: bool = False) -> str:
        """List an account's labels as 'id: name [type]'. Tools accept either
        the name or the id. `include_counts=true` adds message and thread
        counts (one extra API call per label, so it is slow)."""
        svc = rt.service(account)
        labels = gmail.list_labels(svc)
        if not labels:
            return "No labels."
        labels = sorted(
            labels, key=lambda x: (x.get("type", ""), str(x.get("name", "")))
        )
        if include_counts:
            labels = [gmail.get_label(svc, str(x["id"])) for x in labels]
        return "\n".join(format_label(x, include_counts) for x in labels)

    register_tool(mcp, list_labels)
