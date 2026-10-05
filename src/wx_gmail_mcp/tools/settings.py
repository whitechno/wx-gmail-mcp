"""Mailbox settings tools, registered only with WX_GMAIL_ALLOW_SETTINGS=true.

Every tool checks that the account granted ``gmail.settings.basic``. The
write endpoints accept no other scope, the full mail scope included;
``sendAs.list`` would also take the base scopes, but one check for the
whole gate is deliberate. Filters have their own module; nothing here
touches forwarding, which would need the sharing scope.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from wx_gmail_mcp import auth, gmail, sendas, vacation
from wx_gmail_mcp.config import SCOPE_SETTINGS_BASIC
from wx_gmail_mcp.gmail import GmailService, Runtime
from wx_gmail_mcp.safety import register_tool


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
        """Replace the whole vacation responder (Gmail has no partial update:
        fields left out are cleared, so get_vacation first). An enabled
        responder needs `body` or `html` (Gmail keeps only `html` if both).
        `start_date`/`end_date` (YYYY-MM-DD) are the first and last day in
        the machine's zone or `timezone`; none means until turned off.
        `contacts_only`/`domain_only` limit who gets a reply."""
        resource = vacation.body(
            enabled,
            subject,
            plain=body,
            html=html,
            start_date=start_date,
            end_date=end_date,
            contacts_only=contacts_only,
            domain_only=domain_only,
            timezone=timezone,
        )
        svc = service(account)
        updated = gmail.update_vacation(svc, resource)
        zone = vacation.resolve_zone(timezone)
        return "Updated the vacation responder.\n" + vacation.text(
            updated, zone, timezone
        )

    def list_send_as(account: str) -> str:
        """List the account's send-as identities (the primary address and its
        aliases): display name, reply-to, primary/default flags, verification
        status and the signature as stored (HTML)."""
        identities = gmail.list_send_as(service(account))
        if not identities:
            return "No send-as identities."
        n = len(identities)
        head = f"{n} send-as identit{'y' if n == 1 else 'ies'}:"
        return "\n".join([head, *(sendas.text(i) for i in identities)])

    def set_signature(account: str, signature: str, send_as_email: str = "") -> str:
        """Set one send-as identity's signature (HTML; empty removes it): the
        primary unless `send_as_email` names an alias from list_send_as
        (Gmail refuses alias changes on personal accounts). Nothing else
        changes."""
        svc = service(account)
        identity = sendas.find(gmail.list_send_as(svc), send_as_email)
        target = sendas.address(identity)
        # Whitespace alone clears the signature rather than storing blanks.
        signature = signature if signature.strip() else ""
        updated = gmail.patch_send_as(svc, target, {"signature": signature})
        verb = "Set" if signature else "Cleared"
        return f"{verb} the signature of {target}.\n" + sendas.text(updated)

    register_tool(mcp, get_vacation)
    register_tool(mcp, set_vacation)
    register_tool(mcp, list_send_as)
    register_tool(mcp, set_signature)
