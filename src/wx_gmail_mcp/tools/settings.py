"""Mailbox settings tools, registered only with WX_GMAIL_ALLOW_SETTINGS=true.

Every tool checks that the account granted ``gmail.settings.basic``: the
settings endpoints accept no other scope, the full mail scope included.
Filters have their own module; nothing here touches forwarding, which
would need the sharing scope.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from wx_gmail_mcp import auth, gmail, vacation
from wx_gmail_mcp.config import SCOPE_SETTINGS_BASIC
from wx_gmail_mcp.errors import WxGmailError
from wx_gmail_mcp.gmail import GmailService, Runtime
from wx_gmail_mcp.safety import register_tool


def vacation_body(
    enabled: bool,
    subject: str,
    body: str,
    html: str,
    start_date: str,
    end_date: str,
    contacts_only: bool,
    domain_only: bool,
    timezone: str,
) -> dict[str, Any]:
    """The complete resource ``updateVacation`` replaces the current one with."""
    if enabled and not body.strip() and not html.strip():
        raise WxGmailError("An enabled responder needs a message: body or html.")
    zone = vacation.resolve_zone(timezone)
    return {
        "enableAutoReply": enabled,
        "responseSubject": subject,
        "responseBodyPlainText": body,
        "responseBodyHtml": html,
        "restrictToContacts": contacts_only,
        "restrictToDomain": domain_only,
        **vacation.period(start_date, end_date, zone),
    }


def register(mcp: MCPServer, rt: Runtime) -> None:
    def service(account: str) -> GmailService:
        auth.require_scope(
            rt.settings, account, rt.credentials(account), SCOPE_SETTINGS_BASIC
        )
        return rt.service(account)

    def get_vacation(account: str, timezone: str = "") -> str:
        """Show the vacation (out of office) responder: on or off, subject,
        message, first and last day, and who gets replies. Days are shown
        in the machine's time zone unless an IANA `timezone` is given."""
        zone = vacation.resolve_zone(timezone)
        current = gmail.get_vacation(service(account))
        return vacation.text(current, zone, timezone)

    def set_vacation(
        account: str,
        enabled: bool,
        subject: str = "",
        body: str = "",
        html: str = "",
        start_date: str = "",
        end_date: str = "",
        contacts_only: bool = False,
        domain_only: bool = False,
        timezone: str = "",
    ) -> str:
        """Replace the vacation responder. Gmail has no partial update: every
        field left out is cleared, so get_vacation first and pass what must
        stay. `enabled` turns replies on or off; the message is `body`
        (plain) and/or `html`, required when enabled. `start_date` and
        `end_date` (YYYY-MM-DD) are the first and last day, inclusive, at
        midnight in the machine's zone or the IANA `timezone`; without them
        the responder runs until turned off. `contacts_only` and
        `domain_only` (Google Workspace) limit who gets a reply."""
        resource = vacation_body(
            enabled,
            subject,
            body,
            html,
            start_date,
            end_date,
            contacts_only,
            domain_only,
            timezone,
        )
        svc = service(account)
        updated = gmail.update_vacation(svc, resource)
        zone = vacation.resolve_zone(timezone)
        return "Updated the vacation responder.\n" + vacation.text(
            updated, zone, timezone
        )

    register_tool(mcp, get_vacation)
    register_tool(mcp, set_vacation)
