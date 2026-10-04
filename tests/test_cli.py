from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from wx_gmail_mcp import __version__, auth, server
from wx_gmail_mcp.cli import main
from wx_gmail_mcp.config import Settings
from wx_gmail_mcp.errors import WxGmailError


@pytest.fixture
def env_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    monkeypatch.setenv("WX_GMAIL_MCP_HOME", str(home))
    monkeypatch.delenv("WX_GMAIL_ALLOW_SENDING", raising=False)
    monkeypatch.delenv("WX_GMAIL_ALLOW_SETTINGS", raising=False)
    monkeypatch.delenv("WX_GMAIL_ALLOW_DELETE", raising=False)
    return home


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"wx-gmail-mcp {__version__}"


def test_auth_requires_email(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--auth", "work"])
    assert exc.value.code == 2
    assert "--email is required" in capsys.readouterr().err


def test_empty_alias_does_not_fall_through_to_serving(
    env_home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(server, "serve", lambda s: pytest.fail("served"))
    with pytest.raises(SystemExit) as exc:
        main(["--auth", ""])
    assert exc.value.code == 2
    assert main(["--auth", "", "--email", "you@example.com"]) == 1
    assert "Invalid alias" in capsys.readouterr().err


def test_email_without_auth_and_auth_with_list_are_usage_errors(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--email", "you@example.com"])
    assert exc.value.code == 2
    assert "--email only makes sense with --auth" in capsys.readouterr().err
    with pytest.raises(SystemExit) as exc:
        main(["--auth", "work", "--email", "you@example.com", "--list"])
    assert exc.value.code == 2
    assert "not allowed with" in capsys.readouterr().err


def test_auth_runs_oauth_with_env_settings(
    env_home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("WX_GMAIL_ALLOW_SENDING", "true")
    seen: dict[str, Any] = {}

    def fake_run_oauth(settings: Settings, alias: str, email: str) -> auth.AuthResult:
        seen.update(settings=settings, alias=alias, email=email)
        return auth.AuthResult(alias, email, email, frozenset())

    monkeypatch.setattr(auth, "run_oauth", fake_run_oauth)
    assert main(["--auth", "work", "--email", "you@example.com"]) == 0
    assert seen["alias"] == "work"
    assert seen["email"] == "you@example.com"
    assert seen["settings"].home == env_home
    assert seen["settings"].gates.sending is True
    assert "Authorized 'work' -> you@example.com" in capsys.readouterr().out


def test_auth_error_is_reported_on_stderr(
    env_home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def failing(settings: Settings, alias: str, email: str) -> auth.AuthResult:
        raise WxGmailError("Missing OAuth client")

    monkeypatch.setattr(auth, "run_oauth", failing)
    assert main(["--auth", "work", "--email", "you@example.com"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "wx-gmail-mcp: error: Missing OAuth client" in captured.err


def test_list_reports_library_errors_readably(
    env_home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def failing(settings: Settings) -> list[str]:
        raise OSError("disk on fire")

    monkeypatch.setattr(auth, "account_status_lines", failing)
    assert main(["--list"]) == 1
    assert "wx-gmail-mcp: error: OSError: disk on fire" in capsys.readouterr().err


def test_list_with_no_accounts(
    env_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--list"]) == 0
    assert capsys.readouterr().out.startswith("No accounts configured")


def test_no_command_serves(env_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    served: list[Settings] = []
    monkeypatch.setattr(server, "serve", served.append)
    assert main([]) == 0
    assert served[0].home == env_home
