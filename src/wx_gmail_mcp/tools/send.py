"""Send tools, registered only with WX_GMAIL_ALLOW_SENDING=true.

``send_message`` and ``send_draft``; ``reply`` and ``forward`` follow.
Every tool checks the account's send scope first (``require_scope``).
"""

from __future__ import annotations

from collections.abc import Sequence

from mcp.server.mcpserver import MCPServer

from wx_gmail_mcp import auth, gmail
from wx_gmail_mcp.compose import build_raw
from wx_gmail_mcp.config import SCOPE_SEND
from wx_gmail_mcp.gmail import GmailService, Runtime, header
from wx_gmail_mcp.safety import register_tool


def register(mcp: MCPServer, rt: Runtime) -> None:
    def service(account: str) -> GmailService:
        auth.require_scope(rt.settings, account, rt.credentials(account), SCOPE_SEND)
        return rt.service(account)

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
        svc = service(account)
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
        sent = gmail.send_raw(svc, raw)
        return (
            f"Sent. message id={sent.get('id', '')} "
            f"thread id={sent.get('threadId', '')}"
        )

    def send_draft(account: str, draft_id: str) -> str:
        """Send an existing draft as it is stored, immediately and with no
        confirmation step; the draft is removed on success. Returns the
        recipient and subject it had, plus the sent message's ids."""
        svc = service(account)
        draft_id = draft_id.strip()
        draft = gmail.get_draft(svc, draft_id, "metadata")
        p = (draft.get("message", {}) or {}).get("payload", {}) or {}
        to, subject = header(p, "To"), header(p, "Subject")
        sent = gmail.send_draft(svc, draft_id)
        return (
            f"Sent draft {draft_id} (To: {to} | Subj: {subject}). "
            f"message id={sent.get('id', '')} thread id={sent.get('threadId', '')}"
        )

    register_tool(mcp, send_message)
    register_tool(mcp, send_draft)
