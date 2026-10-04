"""OAuth flow, token load/refresh and scope bookkeeping.

``run_oauth`` writes the scopes Google actually granted into the token
file (google-auth-oauthlib keeps them in ``granted_scopes``, which
``to_json`` drops), and tokens are loaded *without* overriding scopes. So
``creds.scopes`` is the grant. The gates say what the server wants; the
token says what Google granted; the grant wins.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.errors import HttpError

from wx_gmail_mcp import accounts
from wx_gmail_mcp.config import (
    SCOPE_FULL,
    SCOPE_SETTINGS_BASIC,
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


def save_token(path: Path, creds: Credentials, scopes: list[str] | None = None) -> None:
    """Persist ``creds``; ``scopes`` overrides the recorded scope list."""
    info = json.loads(creds.to_json())
    if scopes is not None:
        info["scopes"] = scopes
    accounts.write_private(path, json.dumps(info))


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
        except GoogleAuthError as e:
            raise WxGmailError(
                f"Token refresh failed for '{alias}' ({e}). Re-authorize with: "
                f"{reauth_command(settings, alias)}"
            ) from e
        # A refresh reports the current grant; a user may have revoked part.
        granted = list(creds.granted_scopes) if creds.granted_scopes else None
        save_token(path, creds, granted)
        if granted:
            creds = Credentials.from_authorized_user_file(str(path))
        return creds
    raise WxGmailError(
        f"Credentials for '{alias}' are invalid or revoked. Re-authorize with: "
        f"{reauth_command(settings, alias)}"
    )


def granted_scopes(creds: Credentials) -> frozenset[str]:
    return frozenset(creds.scopes or ())


def scope_covered(granted: frozenset[str], scope: str) -> bool:
    """Is ``scope`` usable with this grant?

    The full mail scope covers reading, modifying, sending and deleting,
    but the settings endpoints accept only ``gmail.settings.basic``.
    """
    if scope in granted:
        return True
    return SCOPE_FULL in granted and scope != SCOPE_SETTINGS_BASIC


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


REVOKE_URL = "https://oauth2.googleapis.com/revoke"


def revoke_grant(settings: Settings, alias: str, request: Any = None) -> str:
    """Ask Google to revoke the stored grant for ``alias``.

    Posts the refresh token (or the access token) to the revoke endpoint.
    Raises if the token file is missing or Google answers with an error.
    """
    path = accounts.token_path(settings, alias)
    if not path.exists():
        raise WxGmailError(f"No token for account '{alias}'; nothing to revoke.")
    info = json.loads(path.read_text())
    token = info.get("refresh_token") or info.get("token")
    if not token:
        raise WxGmailError(f"Token file for '{alias}' holds no token to revoke.")
    http = request or Request()
    response = http(
        url=REVOKE_URL,
        method="POST",
        body=urlencode({"token": token}).encode(),
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    status = int(getattr(response, "status", 0))
    if status != 200:
        raise WxGmailError(
            f"Google refused to revoke the grant for '{alias}' (HTTP {status}). "
            "Remove it by hand at https://myaccount.google.com/permissions."
        )
    return f"Google grant for '{alias}' revoked."


Authorizer = Callable[[Path, list[str], str], Credentials]
EmailFetcher = Callable[[Credentials], str]


def browser_authorize(client_file: Path, scopes: list[str], email: str) -> Credentials:
    """Run the loopback browser flow; returns the granted credentials."""
    flow = InstalledAppFlow.from_client_secrets_file(str(client_file), scopes)
    # Google's consent screen lets the user grant a subset, and oauthlib
    # treats any difference from the request as an error unless relaxed.
    # Accept the grant as given; run_oauth records and reports it.
    os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")
    # offline + consent guarantees a refresh token; login_hint pre-selects
    # the account. No include_granted_scopes: each --auth requests exactly
    # the gates' scopes, so turning a gate off narrows the next grant.
    creds = flow.run_local_server(
        port=0,
        access_type="offline",
        prompt="consent",
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
    notes: tuple[str, ...] = ()

    def text(self) -> str:
        lines = [
            f"Authorized '{self.alias}' -> {self.actual}. Token saved. "
            f"Scopes: {scopes_text(self.scopes)}."
        ]
        if self.actual.lower() != self.requested.lower():
            lines.append(f"Note: you signed in as {self.actual}, not {self.requested}.")
        lines.extend(self.notes)
        return "\n".join(lines)


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
    accounts.ensure_private_dir(settings.home)
    if not settings.client_file.exists():
        raise WxGmailError(
            f"Missing OAuth client at {settings.client_file}. Download a Google "
            "'Desktop app' OAuth client JSON and save it there (mode 600)."
        )
    creds = authorize(settings.client_file, settings.scopes(), email)
    # The real grant; a user may have unchecked scopes on the consent screen.
    granted = list(creds.granted_scopes or creds.scopes or [])
    # Save first: a failed profile lookup must not throw away the consent.
    save_token(accounts.token_path(settings, alias), creds, granted)
    notes: list[str] = []
    try:
        actual = fetch_email(creds) or email
    except (HttpError, GoogleAuthError, OSError) as e:
        actual = email
        notes.append(f"Note: could not confirm the address with Gmail ({e}).")
    accounts.set_account(settings, alias, actual)
    granted_set = frozenset(granted)
    for gate in ungranted_gates(settings, granted_set):
        notes.append(
            f"Warning: {gate.env} is on but the {scope_label(gate.scope)} "
            "scope was not granted; its tools will fail until you re-run "
            "--auth and allow it."
        )
    return AuthResult(alias, email, actual, granted_set, tuple(notes))
