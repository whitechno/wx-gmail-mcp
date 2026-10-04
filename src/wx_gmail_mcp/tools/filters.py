"""Filter tools, registered only with WX_GMAIL_ALLOW_SETTINGS=true.

Every tool checks that the account granted ``gmail.settings.basic``: the
settings endpoints accept no other scope, the full mail scope included.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from wx_gmail_mcp import auth, filters, gmail
from wx_gmail_mcp.config import SCOPE_SETTINGS_BASIC
from wx_gmail_mcp.errors import WxGmailError
from wx_gmail_mcp.gmail import GmailService, Runtime
from wx_gmail_mcp.labels import LabelMap
from wx_gmail_mcp.safety import register_tool


def register(mcp: MCPServer, rt: Runtime) -> None:
    def service(account: str) -> GmailService:
        auth.require_scope(
            rt.settings, account, rt.credentials(account), SCOPE_SETTINGS_BASIC
        )
        return rt.service(account)

    def list_filters(account: str) -> str:
        """List the account's mail filters: id, what each matches (and the
        equivalent Gmail search), and what it does, with label names."""
        svc = service(account)
        found = gmail.list_filters(svc)
        if not found:
            return "No filters."
        labels = LabelMap.fetch(svc)
        head = f"{len(found)} filter{'' if len(found) == 1 else 's'}:"
        return "\n".join([head, *(filters.filter_text(f, labels) for f in found)])

    def get_filter(account: str, filter_id: str) -> str:
        """Show one filter by id: criteria, the equivalent Gmail search and
        the action, with label names."""
        filter_id = filter_id.strip()
        if not filter_id:
            raise WxGmailError("filter_id is required.")
        svc = service(account)
        flt = gmail.get_filter(svc, filter_id)
        return filters.filter_text(flt, LabelMap.fetch(svc))

    register_tool(mcp, list_filters)
    register_tool(mcp, get_filter)
