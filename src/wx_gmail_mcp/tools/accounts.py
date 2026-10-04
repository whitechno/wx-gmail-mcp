"""Account tools: list, add (browser OAuth), remove, and get_profile."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from wx_gmail_mcp import accounts, auth, gmail
from wx_gmail_mcp.gmail import Runtime
from wx_gmail_mcp.safety import register_tool


def register(mcp: MCPServer, rt: Runtime) -> None:
    def list_accounts() -> str:
        """List configured Gmail accounts: alias, address, token health,
        granted scopes, and gates that are on but not granted."""
        return "\n".join(auth.account_status_lines(rt.settings))

    def add_account(alias: str, email: str) -> str:
        """Authorize a Gmail account in a browser on the server's machine and
        store its token under `alias`. If the client blocks the browser flow,
        the user runs `wx-gmail-mcp --auth <alias> --email <address>` in a
        terminal instead."""
        return auth.run_oauth(rt.settings, alias, email).text()

    def remove_account(alias: str, revoke: bool = False) -> str:
        """Forget an account: delete its local token and alias. With
        `revoke=true`, also revoke the grant at Google (this cuts off every
        alias that points at the same address); otherwise the grant stays
        until the user removes it at myaccount.google.com/permissions."""
        accounts.check_alias(alias)
        if alias not in accounts.load_accounts(rt.settings):
            return (
                f"No such account '{alias}'. Known accounts: "
                f"{accounts.known_aliases(rt.settings)}."
            )
        note = ""
        if revoke:
            note = " " + auth.revoke_grant(rt.settings, alias)
        accounts.delete_account(rt.settings, alias)
        return f"Removed account '{alias}' (local token deleted).{note}"

    def get_profile(account: str) -> str:
        """The account's Gmail profile: address, total messages and threads,
        and the current history id."""
        profile = gmail.get_profile(rt.service(account))
        return (
            f"Email: {profile.get('emailAddress', '')}\n"
            f"Messages: {profile.get('messagesTotal', 0)}\n"
            f"Threads: {profile.get('threadsTotal', 0)}\n"
            f"History id: {profile.get('historyId', '')}"
        )

    register_tool(mcp, list_accounts)
    register_tool(mcp, get_profile)
    register_tool(mcp, add_account)
    register_tool(mcp, remove_account)
