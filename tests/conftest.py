from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from wx_gmail_mcp.config import BASE_SCOPES, Gates, Settings

CLIENT_JSON = {
    "installed": {
        "client_id": "placeholder.apps.example",
        "client_secret": "placeholder-secret",
        "redirect_uris": ["http://localhost"],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
}


def make_settings(home: Path, **gates: bool) -> Settings:
    return Settings(home=home, gates=Gates(**gates))


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path / "home")


@pytest.fixture
def home(settings: Settings) -> Path:
    return settings.home


def write_client(settings: Settings) -> None:
    settings.home.mkdir(parents=True, exist_ok=True)
    settings.client_file.write_text(json.dumps(CLIENT_JSON))


def write_token(
    settings: Settings,
    alias: str,
    scopes: tuple[str, ...] = BASE_SCOPES,
    *,
    expired: bool = False,
    refresh_token: str = "placeholder-refresh",
    email: str = "you@example.com",
) -> Path:
    """Write a token file the way google-auth would, plus the accounts entry."""
    delta = timedelta(hours=-1) if expired else timedelta(hours=1)
    expiry = (datetime.now(UTC) + delta).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    info = {
        "token": "placeholder-access",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "placeholder.apps.example",
        "client_secret": "placeholder-secret",
        "scopes": list(scopes),
        "expiry": expiry,
        "refresh_token": refresh_token,
    }
    settings.tokens_dir.mkdir(parents=True, exist_ok=True)
    path = settings.tokens_dir / f"{alias}.json"
    path.write_text(json.dumps(info))
    accounts = {}
    if settings.accounts_file.exists():
        accounts = json.loads(settings.accounts_file.read_text())
    accounts[alias] = email
    settings.accounts_file.write_text(json.dumps(accounts))
    return path
