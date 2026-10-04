"""Draft tools (always on). Phase 2 ports create_draft; list/get/update/
delete follow in a later phase."""

from __future__ import annotations

from collections.abc import Sequence

from mcp.server.mcpserver import MCPServer

from wx_gmail_mcp import gmail
from wx_gmail_mcp.gmail import Runtime
from wx_gmail_mcp.safety import register_tool
from wx_gmail_mcp.tools.compose import build_raw


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
        raw = build_raw(
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
        draft = gmail.create_draft(rt.service(account), raw)
        message = draft.get("message", {}) or {}
        return (
            f"Draft created. draft id={draft.get('id', '')} "
            f"message id={message.get('id', '')}"
        )

    register_tool(mcp, create_draft)
