from __future__ import annotations

import json
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials

from wx_gmail_mcp import accounts, auth
from wx_gmail_mcp.config import (
    BASE_SCOPES,
    GATE_SETTINGS,
    SCOPE_FULL,
    SCOPE_SEND,
    SCOPE_SETTINGS_BASIC,
    Settings,
)
from wx_gmail_mcp.errors import WxGmailError

from .conftest import make_settings, write_client, write_token


def test_missing_token_names_known_accounts_and_command(settings: Settings) -> None:
    write_token(settings, "other")
    with pytest.raises(WxGmailError) as exc:
        auth.load_credentials(settings, "work")
    msg = str(exc.value)
    assert "No token for account 'work'" in msg
    assert "Known accounts: other" in msg
    assert "wx-gmail-mcp --auth work --email <address>" in msg


def test_valid_token_keeps_file_scopes(settings: Settings) -> None:
    write_token(settings, "work", (*BASE_SCOPES, SCOPE_SEND))
    creds = auth.load_credentials(settings, "work")
    assert creds.valid
    assert auth.granted_scopes(creds) == frozenset((*BASE_SCOPES, SCOPE_SEND))


def test_expired_token_is_refreshed_and_saved(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_token(settings, "work", expired=True)
    path.chmod(0o644)

    def fake_refresh(self: Credentials, request: Any) -> None:
        self.token = "placeholder-fresh"
        self.expiry = None

    monkeypatch.setattr(Credentials, "refresh", fake_refresh)
    creds = auth.load_credentials(settings, "work")
    assert creds.token == "placeholder-fresh"
    assert json.loads(path.read_text())["token"] == "placeholder-fresh"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_refresh_records_the_current_grant(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_token(settings, "work", (*BASE_SCOPES, SCOPE_SEND), expired=True)

    def fake_refresh(self: Credentials, request: Any) -> None:
        self.token = "placeholder-fresh"
        self.expiry = None
        self._granted_scopes = list(BASE_SCOPES)  # send was revoked meanwhile

    monkeypatch.setattr(Credentials, "refresh", fake_refresh)
    creds = auth.load_credentials(settings, "work")
    assert auth.granted_scopes(creds) == frozenset(BASE_SCOPES)
    assert json.loads(path.read_text())["scopes"] == list(BASE_SCOPES)


def test_refresh_failure_is_readable(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_token(settings, "work", expired=True)

    def failing_refresh(self: Credentials, request: Any) -> None:
        raise RefreshError("invalid_grant: Token has been expired or revoked.")

    monkeypatch.setattr(Credentials, "refresh", failing_refresh)
    with pytest.raises(WxGmailError, match="Token refresh failed for 'work'"):
        auth.load_credentials(settings, "work")


def test_expired_without_refresh_token(settings: Settings) -> None:
    write_token(settings, "work", expired=True, refresh_token="")
    with pytest.raises(WxGmailError, match="invalid or revoked"):
        auth.load_credentials(settings, "work")


def test_malformed_token_file_is_readable(settings: Settings) -> None:
    path = write_token(settings, "work")
    path.write_text(json.dumps({"token": "placeholder-access"}))
    with pytest.raises(WxGmailError, match="Token file for 'work' is unreadable"):
        auth.load_credentials(settings, "work")


def test_full_scope_covers_all_but_settings() -> None:
    full = frozenset({SCOPE_FULL})
    assert auth.scope_covered(full, SCOPE_SEND)
    assert auth.scope_covered(full, BASE_SCOPES[0])
    assert not auth.scope_covered(full, SCOPE_SETTINGS_BASIC)
    assert auth.scope_covered(frozenset({SCOPE_SEND}), SCOPE_SEND)
    assert not auth.scope_covered(frozenset(BASE_SCOPES), SCOPE_SEND)


def test_delete_grant_does_not_satisfy_settings_gate(tmp_path: Path) -> None:
    s = make_settings(tmp_path, settings=True, delete=True)
    assert auth.ungranted_gates(s, frozenset({SCOPE_FULL})) == [GATE_SETTINGS]


def test_ungranted_gates(tmp_path: Path) -> None:
    s = make_settings(tmp_path, sending=True, settings=True)
    granted = frozenset((*BASE_SCOPES, SCOPE_SEND))
    assert auth.ungranted_gates(s, granted) == [GATE_SETTINGS]
    assert auth.ungranted_gates(s, frozenset({SCOPE_FULL, SCOPE_SETTINGS_BASIC})) == []


def test_require_scope(tmp_path: Path) -> None:
    s = make_settings(tmp_path, sending=True)
    creds = Credentials(token="placeholder-access", scopes=list(BASE_SCOPES))
    auth.require_scope(s, "work", creds, BASE_SCOPES[0])
    with pytest.raises(WxGmailError) as exc:
        auth.require_scope(s, "work", creds, SCOPE_SEND)
    msg = str(exc.value)
    assert "has not granted the send scope" in msg
    assert "Set WX_GMAIL_ALLOW_SENDING=true" in msg
    assert "WX_GMAIL_ALLOW_SENDING=true wx-gmail-mcp --auth work" in msg


def test_reauth_command_lists_enabled_gates(tmp_path: Path) -> None:
    s = make_settings(tmp_path, sending=True, delete=True)
    assert auth.reauth_command(s, "work", "you@example.com") == (
        "WX_GMAIL_ALLOW_SENDING=true WX_GMAIL_ALLOW_DELETE=true "
        "wx-gmail-mcp --auth work --email you@example.com"
    )
    assert auth.reauth_command(make_settings(tmp_path), "w") == (
        "wx-gmail-mcp --auth w --email <address>"
    )


def test_account_status_lines(tmp_path: Path) -> None:
    s = make_settings(tmp_path, settings=True)
    assert auth.account_status_lines(s)[0].startswith("No accounts configured")
    write_token(s, "work", (*BASE_SCOPES, SCOPE_SETTINGS_BASIC))
    write_token(s, "home", expired=True, refresh_token="")
    write_token(s, "lax")
    lines = auth.account_status_lines(s)
    assert lines[0] == (
        "- work: you@example.com [healthy] scopes: modify, readonly, settings.basic"
    )
    assert lines[1].startswith("- home: you@example.com [needs re-auth: ")
    assert lines[2].startswith("- lax: you@example.com [healthy]")
    assert "warning: WX_GMAIL_ALLOW_SETTINGS is on" in lines[3]
    assert "WX_GMAIL_ALLOW_SETTINGS=true wx-gmail-mcp --auth lax" in lines[3]


def test_run_oauth_requires_client_file_and_makes_home_private(
    settings: Settings,
) -> None:
    settings.home.mkdir(parents=True)
    settings.home.chmod(0o755)
    with pytest.raises(WxGmailError, match="Missing OAuth client"):
        auth.run_oauth(settings, "work", "you@example.com")
    assert stat.S_IMODE(settings.home.stat().st_mode) == 0o700


def test_run_oauth_rejects_bad_alias(settings: Settings) -> None:
    write_client(settings)
    with pytest.raises(WxGmailError, match="Invalid alias"):
        auth.run_oauth(settings, "../x", "you@example.com")


def _fake_authorize(
    seen: dict[str, Any], granted: list[str] | None = None
) -> auth.Authorizer:
    def authorize(client: Path, scopes: list[str], email: str) -> Credentials:
        seen.update(client=client, scopes=scopes, email=email)
        return Credentials(
            token="placeholder-access",
            refresh_token="placeholder-refresh",
            token_uri="https://oauth2.googleapis.com/token",
            client_id="placeholder.apps.example",
            client_secret="placeholder-secret",
            scopes=scopes,
            granted_scopes=granted,
            # Not expired, so a later load does not try to refresh.
            expiry=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
        )

    return authorize


def test_run_oauth_saves_token_and_actual_email(tmp_path: Path) -> None:
    s = make_settings(tmp_path, sending=True)
    write_client(s)
    seen: dict[str, Any] = {}
    result = auth.run_oauth(
        s,
        "work",
        "you@example.com",
        authorize=_fake_authorize(seen),
        fetch_email=lambda creds: "actual@example.com",
    )
    assert seen == {
        "client": s.client_file,
        "scopes": [*BASE_SCOPES, SCOPE_SEND],
        "email": "you@example.com",
    }
    token = s.tokens_dir / "work.json"
    assert stat.S_IMODE(token.stat().st_mode) == 0o600
    assert stat.S_IMODE(s.home.stat().st_mode) == 0o700
    assert stat.S_IMODE(s.tokens_dir.stat().st_mode) == 0o700
    info = json.loads(token.read_text())
    assert info["refresh_token"] == "placeholder-refresh"
    assert info["scopes"] == [*BASE_SCOPES, SCOPE_SEND]
    assert json.loads(s.accounts_file.read_text()) == {"work": "actual@example.com"}
    text = result.text()
    assert text.startswith("Authorized 'work' -> actual@example.com. Token saved.")
    assert "modify, readonly, send" in text
    assert "Note: you signed in as actual@example.com, not you@example.com" in text
    assert "Warning" not in text


def test_run_oauth_records_partial_grant_and_warns(tmp_path: Path) -> None:
    s = make_settings(tmp_path, sending=True, settings=True)
    write_client(s)
    granted = [*BASE_SCOPES, SCOPE_SEND]  # user unchecked settings.basic
    result = auth.run_oauth(
        s,
        "work",
        "you@example.com",
        authorize=_fake_authorize({}, granted),
        fetch_email=lambda creds: "you@example.com",
    )
    info = json.loads((s.tokens_dir / "work.json").read_text())
    assert info["scopes"] == granted
    assert result.scopes == frozenset(granted)
    text = result.text()
    assert "Warning: WX_GMAIL_ALLOW_SETTINGS is on but the settings.basic" in text
    assert "WX_GMAIL_ALLOW_SENDING" not in text
    # What --list sees afterwards is the real grant, not the request.
    creds = auth.load_credentials(s, "work")
    assert auth.ungranted_gates(s, auth.granted_scopes(creds)) == [GATE_SETTINGS]


def test_run_oauth_records_superset_grant(tmp_path: Path) -> None:
    s = make_settings(tmp_path)
    write_client(s)
    granted = [*BASE_SCOPES, SCOPE_FULL]  # Google returned more than asked
    result = auth.run_oauth(
        s,
        "work",
        "you@example.com",
        authorize=_fake_authorize({}, granted),
        fetch_email=lambda creds: "you@example.com",
    )
    assert result.scopes == frozenset(granted)
    assert json.loads((s.tokens_dir / "work.json").read_text())["scopes"] == granted


def test_run_oauth_keeps_token_when_profile_lookup_fails(tmp_path: Path) -> None:
    s = make_settings(tmp_path)
    write_client(s)

    def failing(creds: Credentials) -> str:
        raise OSError("network down")

    result = auth.run_oauth(
        s, "work", "you@example.com", authorize=_fake_authorize({}), fetch_email=failing
    )
    assert (s.tokens_dir / "work.json").exists()
    assert json.loads(s.accounts_file.read_text()) == {"work": "you@example.com"}
    assert "Note: could not confirm the address with Gmail (network down)." in (
        result.text()
    )


def test_account_status_lines_condense_gate_warnings(tmp_path: Path) -> None:
    s = make_settings(tmp_path, sending=True, settings=True, delete=True)
    write_token(s, "base")
    write_token(s, "half", (*BASE_SCOPES, SCOPE_FULL))
    lines = auth.account_status_lines(s)
    assert len(lines) == 4, lines
    assert lines[1] == (
        "    warning: WX_GMAIL_ALLOW_SENDING, WX_GMAIL_ALLOW_SETTINGS and "
        "WX_GMAIL_ALLOW_DELETE are on but the send, settings.basic and full "
        "scopes are not granted; re-run: WX_GMAIL_ALLOW_SENDING=true "
        "WX_GMAIL_ALLOW_SETTINGS=true WX_GMAIL_ALLOW_DELETE=true wx-gmail-mcp "
        "--auth base --email you@example.com"
    )
    # The full scope covers sending; only the settings gate is unmet.
    assert lines[3].startswith(
        "    warning: WX_GMAIL_ALLOW_SETTINGS is on but the settings.basic scope "
        "is not granted; re-run: "
    )


def test_run_oauth_notes_a_replaced_alias(tmp_path: Path) -> None:
    s = make_settings(tmp_path)
    write_client(s)
    write_token(s, "work", email="old@example.com")
    result = auth.run_oauth(
        s,
        "work",
        "you@example.com",
        authorize=_fake_authorize({}, list(BASE_SCOPES)),
        fetch_email=lambda creds: "you@example.com",
    )
    assert "Note: replaced the token 'work' held for old@example.com." in result.text()
    assert accounts.load_accounts(s) == {"work": "you@example.com"}
    second = auth.run_oauth(
        s,
        "other",
        "you@example.com",
        authorize=_fake_authorize({}, list(BASE_SCOPES)),
        fetch_email=lambda creds: "you@example.com",
    )
    assert "replaced" not in second.text()
    third = auth.run_oauth(
        s,
        "work",
        "you@example.com",
        authorize=_fake_authorize({}, list(BASE_SCOPES)),
        fetch_email=lambda creds: "you@example.com",
    )
    assert "Note: refreshed the token 'work' for you@example.com." in third.text()
    assert "replaced" not in third.text()
