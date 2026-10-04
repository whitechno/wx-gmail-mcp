from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from wx_gmail_mcp.config import (
    ALL_GATES,
    BASE_SCOPES,
    SCOPE_FULL,
    SCOPE_READONLY,
    SCOPE_SEND,
    SCOPE_SETTINGS_BASIC,
    Gates,
    Settings,
    env_flag,
    gate_for_scope,
    scope_label,
)


def test_default_home_is_dotdir_under_user_home() -> None:
    s = Settings.from_env({})
    assert s.home == Path.home() / ".wx-gmail-mcp"
    assert s.gates == Gates()


def test_home_override(tmp_path: Path) -> None:
    s = Settings.from_env({"WX_GMAIL_MCP_HOME": str(tmp_path)})
    assert s.home == tmp_path
    assert s.client_file == tmp_path / "oauth_client.json"
    assert s.accounts_file == tmp_path / "accounts.json"
    assert s.tokens_dir == tmp_path / "tokens"
    assert s.downloads_dir == tmp_path / "downloads"
    assert s.outbox_dir == tmp_path / "outbox"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("true", True),
        ("TRUE", True),
        (" True ", True),
        ("1", False),
        ("yes", False),
        ("false", False),
        ("", False),
    ],
)
def test_env_flag_accepts_only_true(value: str, expected: bool) -> None:
    assert env_flag({"X": value}, "X") is expected


def test_gates_from_env_reads_each_var() -> None:
    env = {"WX_GMAIL_ALLOW_SENDING": "true", "WX_GMAIL_ALLOW_DELETE": "true"}
    assert Gates.from_env(env) == Gates(sending=True, settings=False, delete=True)


@pytest.mark.parametrize(
    ("sending", "settings", "delete"), list(itertools.product([False, True], repeat=3))
)
def test_scopes_per_gate_combination(
    sending: bool, settings: bool, delete: bool
) -> None:
    gates = Gates(sending=sending, settings=settings, delete=delete)
    scopes = gates.scopes()
    assert scopes[:2] == list(BASE_SCOPES)
    assert (SCOPE_SEND in scopes) is sending
    assert (SCOPE_SETTINGS_BASIC in scopes) is settings
    assert (SCOPE_FULL in scopes) is delete
    assert len(scopes) == 2 + sending + settings + delete
    assert len(set(scopes)) == len(scopes)


def test_each_gate_adds_exactly_one_scope() -> None:
    for gate in ALL_GATES:
        gates = Gates(**{gate.name: True})
        assert gates.scopes() == [*BASE_SCOPES, gate.scope]
        assert gate_for_scope(gate.scope) is gate
    assert gate_for_scope(SCOPE_READONLY) is None


def test_scope_label() -> None:
    assert scope_label(SCOPE_READONLY) == "readonly"
    assert scope_label(SCOPE_SETTINGS_BASIC) == "settings.basic"
    assert scope_label(SCOPE_FULL) == "full"
    assert scope_label("https://example.com/other") == "https://example.com/other"
