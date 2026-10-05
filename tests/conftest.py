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


# --- tool-level helpers -----------------------------------------------------

import asyncio  # noqa: E402
from typing import Any  # noqa: E402

from google.oauth2.credentials import Credentials  # noqa: E402
from mcp.server.mcpserver import MCPServer  # noqa: E402

from wx_gmail_mcp.errors import WxGmailError  # noqa: E402
from wx_gmail_mcp.gmail import Runtime  # noqa: E402
from wx_gmail_mcp.server import build_server  # noqa: E402

from .fake_gmail import FakeGmail  # noqa: E402


class FakeRuntime(Runtime):
    """A runtime whose services are fakes keyed by alias."""

    def __init__(
        self,
        settings: Settings,
        services: dict[str, FakeGmail],
        scopes: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        super().__init__(settings)
        self.services = services
        self.scopes = scopes or {}

    def credentials(self, alias: str) -> Credentials:
        if alias not in self.services:
            raise WxGmailError(f"No token for account '{alias}'.")
        return Credentials(
            token="placeholder-access",
            scopes=list(self.scopes.get(alias, BASE_SCOPES)),
        )

    def service(self, alias: str) -> FakeGmail:
        if alias not in self.services:
            raise WxGmailError(
                f"No token for account '{alias}'. Known accounts: "
                + ", ".join(self.services)
            )
        return self.services[alias]


def tool_server(settings: Settings, fake: FakeGmail, alias: str = "work") -> MCPServer:
    return build_server(FakeRuntime(settings, {alias: fake}))


def call(mcp: MCPServer, name: str, /, **args: Any) -> str:
    """Call a tool through the MCP server and return its text."""
    result = asyncio.run(mcp.call_tool(name, args))
    assert not isinstance(result, dict)
    content = result.model_dump()["content"]
    assert len(content) == 1 and content[0]["type"] == "text"
    return content[0]["text"]


def tool_names(mcp: MCPServer) -> set[str]:
    return {t.name for t in asyncio.run(mcp.list_tools())}


def b64(text: str) -> str:
    import base64

    return base64.urlsafe_b64encode(text.encode()).decode()


def uploaded(call_kwargs: dict[str, Any]) -> bytes:
    """The RFC 822 bytes a send or draft call uploaded as its media body."""
    media = call_kwargs["media_body"]
    assert media.mimetype() == "message/rfc822"
    return media.getbytes(0, media.size())


def message(
    msg_id: str = "m1",
    thread_id: str = "t1",
    labels: tuple[str, ...] = ("INBOX", "UNREAD"),
    headers: dict[str, str] | None = None,
    body: str = "hello",
    parts: list[dict[str, Any]] | None = None,
    snippet: str = "hello...",
) -> dict[str, Any]:
    """A Gmail message resource with a text/plain body or explicit parts."""
    hdrs = {
        "From": "Sender <sender@example.com>",
        "To": "you@example.com",
        "Subject": "Test subject",
        "Date": "Fri, 02 Oct 2026 10:00:00 +0000",
    }
    hdrs.update(headers or {})
    payload: dict[str, Any] = {
        "headers": [{"name": k, "value": v} for k, v in hdrs.items()],
    }
    if parts is None:
        payload["mimeType"] = "text/plain"
        payload["body"] = {"data": b64(body), "size": len(body)}
    else:
        payload["mimeType"] = "multipart/mixed"
        payload["body"] = {"size": 0}
        payload["parts"] = parts
    return {
        "id": msg_id,
        "threadId": thread_id,
        "labelIds": list(labels),
        "snippet": snippet,
        "payload": payload,
    }


LABELS = [
    {"id": "INBOX", "name": "INBOX", "type": "system"},
    {"id": "UNREAD", "name": "UNREAD", "type": "system"},
    {"id": "STARRED", "name": "STARRED", "type": "system"},
    {"id": "Label_1", "name": "wx-test", "type": "user"},
    {"id": "Label_2", "name": "wx-test/sub", "type": "user"},
]
