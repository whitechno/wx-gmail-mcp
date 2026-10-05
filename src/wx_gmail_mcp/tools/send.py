"""Send tools, registered only with WX_GMAIL_ALLOW_SENDING=true.

``send_message``, ``send_draft``, ``reply`` and ``forward``. Every tool
checks the account's send scope first (``require_scope``). Replies and
forwards stay in the original's conversation: Gmail's ``threadId`` plus
``In-Reply-To``/``References`` (plan §5.7).
"""

from __future__ import annotations

from collections.abc import Sequence

from mcp.server.mcpserver import MCPServer

from wx_gmail_mcp import auth, compose, gmail
from wx_gmail_mcp.config import SCOPE_SEND
from wx_gmail_mcp.errors import WxGmailError
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
        sent = gmail.send_message(svc, data)
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

    def reply(
        account: str,
        message_id: str,
        body: str,
        reply_all: bool = False,
        quote: bool = True,
        cc: str = "",
        bcc: str = "",
        attachments: Sequence[str] = (),
    ) -> str:
        """Reply to a message in its conversation, immediately and with no
        confirmation step. Goes to Reply-To or From (to the original
        recipients when `account` sent it); `reply_all` also copies the other
        recipients. Subject gets `Re:`; `quote` appends the original text
        (HTML rendered as text) as a quoted block; `attachments` are outbox
        file names."""
        svc = service(account)
        if not body.strip():
            raise WxGmailError("body is required.")
        orig = compose.load_original(svc, message_id)
        me = str(gmail.get_profile(svc).get("emailAddress", "") or "")
        to, cc_all = compose.reply_recipients(orig, me, reply_all)
        in_reply_to, references = compose.threading_headers(orig)
        subject = compose.reply_subject(orig.subject)
        text, cut = compose.reply_body(body, orig, quote)
        data = compose.build(
            rt.settings,
            to=to,
            subject=subject,
            body=text,
            cc=compose.join_recipients(cc_all, cc),
            bcc=bcc,
            html="",
            attachments=attachments,
            reply_to="",
            in_reply_to=in_reply_to,
            references=references,
        )
        sent = gmail.send_message(svc, data, orig.thread_id)
        return (
            f"Replied to {orig.id} (To: {to} | Subj: {subject}). "
            f"message id={sent.get('id', '')} thread id={sent.get('threadId', '')}."
            + compose.cut_note(cut)
        )

    def forward(
        account: str,
        message_id: str,
        to: str,
        body: str = "",
        cc: str = "",
        bcc: str = "",
        as_attachment: bool = False,
        include_attachments: bool = True,
        attachments: Sequence[str] = (),
    ) -> str:
        """Forward a message, immediately and with no confirmation step.
        Subject gets `Fwd:`. By default the original text follows `body`
        under a forwarded-message header and its attachments are re-attached
        (`include_attachments`); `as_attachment` sends the complete original
        as a message/rfc822 file instead. `attachments` are outbox names."""
        svc = service(account)
        orig = compose.load_original(svc, message_id)
        cut = False
        if as_attachment:
            text = body.rstrip() or f"Forwarded message: {orig.subject}"
            blobs = [compose.original_as_attachment(svc, orig)]
        else:
            text, cut = compose.forward_body(body, orig)
            blobs = (
                compose.original_attachments(svc, orig) if include_attachments else []
            )
        in_reply_to, references = compose.threading_headers(orig)
        subject = compose.forward_subject(orig.subject)
        data = compose.build(
            rt.settings,
            to=to,
            subject=subject,
            body=text,
            cc=cc,
            bcc=bcc,
            html="",
            attachments=attachments,
            reply_to="",
            in_reply_to=in_reply_to,
            references=references,
            blobs=blobs,
        )
        sent = gmail.send_message(svc, data, orig.thread_id)
        return (
            f"Forwarded {orig.id} (To: {to.strip()} | Subj: {subject}). "
            f"message id={sent.get('id', '')} thread id={sent.get('threadId', '')}."
            + compose.cut_note(cut)
        )

    register_tool(mcp, send_message)
    register_tool(mcp, send_draft)
    register_tool(mcp, reply)
    register_tool(mcp, forward)
