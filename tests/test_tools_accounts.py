from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from wx_gmail_mcp import auth
from wx_gmail_mcp.config import SCOPE_SEND, Settings
from wx_gmail_mcp.errors import WxGmailError
from wx_gmail_mcp.server import build_server

from .conftest import FakeRuntime, call, make_settings, write_client, write_token
from .fake_gmail import FakeGmail


def _server(settings: Settings):
    return build_server(FakeRuntime(settings, {}))


def test_list_accounts_matches_cli_report(tmp_path: Path) -> None:
    s = make_settings(tmp_path, sending=True)
    write_token(s, "work", email="you@example.com")
    text = call(_server(s), "list_accounts")
    assert text == "\n".join(auth.account_status_lines(s))
    assert "- work: you@example.com [healthy]" in text
    assert "warning: WX_GMAIL_ALLOW_SENDING is on" in text


def test_list_accounts_empty(settings: Settings) -> None:
    assert call(_server(settings), "list_accounts").startswith("No accounts")


def test_add_account_runs_oauth(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    def fake_run_oauth(s: Settings, alias: str, email: str) -> auth.AuthResult:
        seen.update(alias=alias, email=email)
        return auth.AuthResult(alias, email, email, frozenset({SCOPE_SEND}))

    monkeypatch.setattr(auth, "run_oauth", fake_run_oauth)
    text = call(_server(settings), "add_account", alias="work", email="you@example.com")
    assert seen == {"alias": "work", "email": "you@example.com"}
    assert text.startswith("Authorized 'work' -> you@example.com")


def test_add_account_errors_are_text(settings: Settings) -> None:
    text = call(_server(settings), "add_account", alias="work", email="you@example.com")
    assert text.startswith("Error: Missing OAuth client")
    write_client(settings)
    text = call(_server(settings), "add_account", alias="a/b", email="you@example.com")
    assert text.startswith("Error: Invalid alias")


def test_remove_account_local_only(settings: Settings) -> None:
    path = write_token(settings, "work")
    text = call(_server(settings), "remove_account", alias="work")
    assert text == "Removed account 'work' (local token deleted)."
    assert not path.exists()
    assert json.loads(settings.accounts_file.read_text()) == {}


def test_remove_account_unknown(settings: Settings) -> None:
    write_token(settings, "other")
    text = call(_server(settings), "remove_account", alias="work")
    assert text == "No such account 'work'. Known accounts: other."
    assert call(_server(settings), "remove_account", alias="../x").startswith(
        "Error: Invalid alias"
    )


def test_remove_account_with_revoke(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_token(settings, "work")
    revoked: list[str] = []

    def fake_revoke(s: Settings, alias: str, request: Any = None) -> str:
        revoked.append(alias)
        return f"Google grant for '{alias}' revoked."

    monkeypatch.setattr(auth, "revoke_grant", fake_revoke)
    text = call(_server(settings), "remove_account", alias="work", revoke=True)
    assert revoked == ["work"]
    assert text == (
        "Removed account 'work' (local token deleted). Google grant for 'work' revoked."
    )
    assert not path.exists()


def test_remove_account_keeps_token_when_revoke_fails(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_token(settings, "work")

    def failing(s: Settings, alias: str, request: Any = None) -> str:
        raise WxGmailError("Google refused to revoke the grant for 'work' (HTTP 400).")

    monkeypatch.setattr(auth, "revoke_grant", failing)
    text = call(_server(settings), "remove_account", alias="work", revoke=True)
    assert text.startswith("Error: Google refused to revoke")
    assert path.exists()


class _Response:
    def __init__(self, status: int) -> None:
        self.status = status


def test_revoke_grant_posts_refresh_token(settings: Settings) -> None:
    write_token(settings, "work")
    seen: dict[str, Any] = {}

    def fake_request(**kwargs: Any) -> _Response:
        seen.update(kwargs)
        return _Response(200)

    assert auth.revoke_grant(settings, "work", fake_request) == (
        "Google grant for 'work' revoked."
    )
    assert seen["url"] == auth.REVOKE_URL
    assert seen["method"] == "POST"
    assert seen["body"] == b"token=placeholder-refresh"


def test_revoke_grant_errors(settings: Settings) -> None:
    with pytest.raises(WxGmailError, match="nothing to revoke"):
        auth.revoke_grant(settings, "work", lambda **kw: _Response(200))
    write_token(settings, "work")
    with pytest.raises(WxGmailError, match="HTTP 400"):
        auth.revoke_grant(settings, "work", lambda **kw: _Response(400))
    FakeGmail()  # keep the import meaningful for readers of this module
