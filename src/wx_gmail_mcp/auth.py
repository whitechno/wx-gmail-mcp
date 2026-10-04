"""OAuth flow, token load/refresh and scope bookkeeping.

Tokens are loaded *without* overriding scopes, so ``creds.scopes`` is the
grant recorded in the token file. The gates say what the server wants; the
token says what Google granted; the grant wins.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from wx_gmail_mcp import accounts
from wx_gmail_mcp.config import (
    SCOPE_FULL,
    Gate,
    Settings,
    gate_for_scope,
    scope_label,
)
from wx_gmail_mcp.errors import WxGmailError

PROG = "wx-gmail-mcp"


def reauth_command(settings: Settings, alias: str, email: str = "") -> str:
    """The exact terminal command that (re)authorizes ``alias``."""
    env = " ".join(f"{g.env}=true" for g in settings.gates.enabled())
    email_part = f" --email {email}" if email else " --email <address>"
    cmd = f"{PROG} --auth {alias}{email_part}"
    return f"{env} {cmd}" if env else cmd


def save_token(path: Path, creds: Credentials) -> None:
    accounts.write_private(path, creds.to_json())


def load_credentials(settings: Settings, alias: str) -> Credentials:
    """Load, refresh if needed, and return credentials for an alias."""
    path = accounts.token_path(settings, alias)
    if not path.exists():
        raise WxGmailError(
            f"No token for account '{alias}'. Known accounts: "
            f"{accounts.known_aliases(settings)}. Authorize it with: "
            f"{reauth_command(settings, alias)}"
        )
    try:
        creds = Credentials.from_authorized_user_file(str(path))
    except ValueError as e:
        raise WxGmailError(
            f"Token file for '{alias}' is unreadable ({e}). Re-authorize with: "
            f"{reauth_command(settings, alias)}"
        ) from e
    if creds.valid:
        return creds
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError as e:
            raise WxGmailError(
                f"Token refresh failed for '{alias}' ({e}). Re-authorize with: "
                f"{reauth_command(settings, alias)}"
            ) from e
        save_token(path, creds)
        return creds
    raise WxGmailError(
        f"Credentials for '{alias}' are invalid or revoked. Re-authorize with: "
        f"{reauth_command(settings, alias)}"
    )


def granted_scopes(creds: Credentials) -> frozenset[str]:
    return frozenset(creds.scopes or ())


def scope_covered(granted: frozenset[str], scope: str) -> bool:
    """The full scope covers every Gmail scope."""
    return scope in granted or SCOPE_FULL in granted


def ungranted_gates(settings: Settings, granted: frozenset[str]) -> list[Gate]:
    """Gates that are on but whose scope the token does not carry."""
    return [g for g in settings.gates.enabled() if not scope_covered(granted, g.scope)]


def require_scope(
    settings: Settings, alias: str, creds: Credentials, scope: str
) -> None:
    """Raise a readable error if the token lacks ``scope``."""
    if scope_covered(granted_scopes(creds), scope):
        return
    gate = gate_for_scope(scope)
    hint = f"Set {gate.env}=true and re-authorize" if gate else "Re-authorize"
    raise WxGmailError(
        f"Account '{alias}' has not granted the {scope_label(scope)} scope. "
        f"{hint} with: {reauth_command(settings, alias)}"
    )


def scopes_text(granted: frozenset[str]) -> str:
    return ", ".join(sorted(scope_label(s) for s in granted)) or "(none)"


def account_status_lines(settings: Settings) -> list[str]:
    """One line per account: alias, email, health, scopes, gate warnings.

    Shared by ``--list`` and the ``list_accounts`` tool.
    """
    accts = accounts.load_accounts(settings)
    if not accts:
        return [
            "No accounts configured. Authorize one with: "
            + reauth_command(settings, "<alias>")
        ]
    lines: list[str] = []
    for alias, email in accts.items():
        try:
            creds = load_credentials(settings, alias)
        except WxGmailError as e:
            lines.append(f"- {alias}: {email} [needs re-auth: {e}]")
            continue
        granted = granted_scopes(creds)
        lines.append(f"- {alias}: {email} [healthy] scopes: {scopes_text(granted)}")
        for gate in ungranted_gates(settings, granted):
            lines.append(
                f"    warning: {gate.env} is on but the "
                f"{scope_label(gate.scope)} scope is not granted; re-run: "
                f"{reauth_command(settings, alias, email)}"
            )
    return lines


Authorizer = Callable[[Path, list[str], str], Credentials]
EmailFetcher = Callable[[Credentials], str]


def browser_authorize(client_file: Path, scopes: list[str], email: str) -> Credentials:
    """Run the loopback browser flow; returns the granted credentials."""
    flow = InstalledAppFlow.from_client_secrets_file(str(client_file), scopes)
    # offline + consent guarantees a refresh token; login_hint pre-selects
    # the account; include_granted_scopes keeps earlier grants.
    creds = flow.run_local_server(
        port=0,
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
        login_hint=email,
    )
    if not isinstance(creds, Credentials):  # pragma: no cover - installed-app flow
        raise WxGmailError("The OAuth flow did not return user credentials.")
    return creds


def profile_email(creds: Credentials) -> str:
    from wx_gmail_mcp import gmail

    return gmail.get_profile(gmail.build_service(creds)).get("emailAddress", "")


@dataclass(frozen=True)
class AuthResult:
    alias: str
    requested: str
    actual: str
    scopes: frozenset[str]

    def text(self) -> str:
        note = (
            ""
            if self.actual.lower() == self.requested.lower()
            else f" (note: you signed in as {self.actual}, not {self.requested})"
        )
        return (
            f"Authorized '{self.alias}' -> {self.actual}. Token saved. "
            f"Scopes: {scopes_text(self.scopes)}.{note}"
        )


def run_oauth(
    settings: Settings,
    alias: str,
    email: str,
    *,
    authorize: Authorizer = browser_authorize,
    fetch_email: EmailFetcher = profile_email,
) -> AuthResult:
    """Authorize one account and store its token under ``alias``."""
    accounts.check_alias(alias)
    if not settings.client_file.exists():
        raise WxGmailError(
            f"Missing OAuth client at {settings.client_file}. Download a Google "
            "'Desktop app' OAuth client JSON and save it there (mode 600)."
        )
    creds = authorize(settings.client_file, settings.scopes(), email)
    actual = fetch_email(creds) or email
    save_token(accounts.token_path(settings, alias), creds)
    accounts.set_account(settings, alias, actual)
    return AuthResult(alias, email, actual, granted_scopes(creds))
