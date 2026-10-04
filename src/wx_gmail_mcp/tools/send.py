"""Send tools, registered only with WX_GMAIL_ALLOW_SENDING=true.

Phase 2 ports send_message; send_draft, reply and forward follow.
"""

from __future__ import annotations

from collections.abc import Sequence

from mcp.server.mcpserver import MCPServer

from wx_gmail_mcp import auth, gmail
from wx_gmail_mcp.config import SCOPE_SEND
from wx_gmail_mcp.gmail import Runtime
from wx_gmail_mcp.safety import register_tool
from wx_gmail_mcp.tools.compose import build_raw


def register(mcp: MCPServer, rt: Runtime) -> None:
    def send_message(
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
        """Send an email from `account` immediately; there is no confirmation
        step. `html` adds an HTML alternative to the plain `body`;
        `attachments` are file names inside the server's outbox directory."""
        auth.require_scope(rt.settings, account, rt.credentials(account), SCOPE_SEND)
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
        sent = gmail.send_raw(rt.service(account), raw)
        return (
            f"Sent. message id={sent.get('id', '')} "
            f"thread id={sent.get('threadId', '')}"
        )

    register_tool(mcp, send_message)
