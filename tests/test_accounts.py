from __future__ import annotations

import json
import stat

import pytest

from wx_gmail_mcp import accounts
from wx_gmail_mcp.config import Settings
from wx_gmail_mcp.errors import WxGmailError


@pytest.mark.parametrize("alias", ["work", "team-mail", "a_b", "A1", "x"])
def test_valid_aliases(alias: str) -> None:
    assert accounts.check_alias(alias) == alias


@pytest.mark.parametrize("alias", ["", "a.b", "../x", "a/b", "a b", "a\\b", "ä"])
def test_invalid_aliases(alias: str) -> None:
    with pytest.raises(WxGmailError, match="Invalid alias"):
        accounts.check_alias(alias)


def test_load_missing_is_empty(settings: Settings) -> None:
    assert accounts.load_accounts(settings) == {}
    assert accounts.known_aliases(settings) == "(none)"


def test_save_and_load_roundtrip_with_private_modes(settings: Settings) -> None:
    accounts.save_accounts(settings, {"work": "you@example.com"})
    assert accounts.load_accounts(settings) == {"work": "you@example.com"}
    assert stat.S_IMODE(settings.accounts_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(settings.home.stat().st_mode) == 0o700
    assert not settings.tokens_dir.exists()
    assert accounts.known_aliases(settings) == "work"


def test_write_private_fixes_mode_of_existing_file(settings: Settings) -> None:
    settings.home.mkdir(parents=True)
    settings.accounts_file.write_text("{}")
    settings.accounts_file.chmod(0o644)
    accounts.save_accounts(settings, {"work": "you@example.com"})
    assert stat.S_IMODE(settings.accounts_file.stat().st_mode) == 0o600


def test_load_rejects_malformed_json(settings: Settings) -> None:
    settings.home.mkdir(parents=True)
    settings.accounts_file.write_text("{not json")
    with pytest.raises(WxGmailError, match="not valid JSON"):
        accounts.load_accounts(settings)


def test_load_rejects_non_object(settings: Settings) -> None:
    settings.home.mkdir(parents=True)
    settings.accounts_file.write_text(json.dumps(["x"]))
    with pytest.raises(WxGmailError, match="alias -> email"):
        accounts.load_accounts(settings)


def test_token_path_validates_alias(settings: Settings) -> None:
    assert accounts.token_path(settings, "work") == settings.tokens_dir / "work.json"
    with pytest.raises(WxGmailError):
        accounts.token_path(settings, "../etc/passwd")


def test_set_and_delete_account(settings: Settings) -> None:
    accounts.set_account(settings, "work", "you@example.com")
    accounts.write_private(accounts.token_path(settings, "work"), "{}")
    assert accounts.delete_account(settings, "nope") is False
    assert accounts.delete_account(settings, "work") is True
    assert accounts.load_accounts(settings) == {}
    assert not accounts.token_path(settings, "work").exists()
