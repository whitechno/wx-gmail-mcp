"""Runtime configuration: home directory, env gates and gate -> scopes.

Nothing here reads the environment at import time. ``Settings.from_env``
builds a frozen snapshot that the server and CLI pass down, so tests can
construct any gate combination against a temporary home directory.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

HOME_ENV = "WX_GMAIL_MCP_HOME"
HOME_DIRNAME = ".wx-gmail-mcp"

SCOPE_READONLY = "https://www.googleapis.com/auth/gmail.readonly"
SCOPE_MODIFY = "https://www.googleapis.com/auth/gmail.modify"
SCOPE_SEND = "https://www.googleapis.com/auth/gmail.send"
SCOPE_SETTINGS_BASIC = "https://www.googleapis.com/auth/gmail.settings.basic"
SCOPE_FULL = "https://mail.google.com/"

# Always requested. ``modify`` covers reading, but ``readonly`` stays listed
# so the consent screen is explicit about what the base level does.
BASE_SCOPES: tuple[str, ...] = (SCOPE_READONLY, SCOPE_MODIFY)

# Longer bodies are truncated with a marker: tool results land verbatim in
# the model's context window.
DEFAULT_MAX_BODY = 20_000


@dataclass(frozen=True)
class Gate:
    """One opt-in level: its env var and the single scope it adds."""

    name: str
    env: str
    scope: str


GATE_SENDING = Gate("sending", "WX_GMAIL_ALLOW_SENDING", SCOPE_SEND)
GATE_SETTINGS = Gate("settings", "WX_GMAIL_ALLOW_SETTINGS", SCOPE_SETTINGS_BASIC)
GATE_DELETE = Gate("delete", "WX_GMAIL_ALLOW_DELETE", SCOPE_FULL)
ALL_GATES: tuple[Gate, ...] = (GATE_SENDING, GATE_SETTINGS, GATE_DELETE)


def env_flag(environ: Mapping[str, str], name: str) -> bool:
    """Only the exact string ``true`` (any case) turns a gate on.

    ``1``, ``yes`` and the like stay off: a security gate fails closed.
    """
    return environ.get(name, "").strip().lower() == "true"


@dataclass(frozen=True)
class Gates:
    sending: bool = False
    settings: bool = False
    delete: bool = False

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Gates:
        env = os.environ if environ is None else environ
        return cls(
            sending=env_flag(env, GATE_SENDING.env),
            settings=env_flag(env, GATE_SETTINGS.env),
            delete=env_flag(env, GATE_DELETE.env),
        )

    def is_on(self, gate: Gate) -> bool:
        return bool(getattr(self, gate.name))

    def enabled(self) -> tuple[Gate, ...]:
        return tuple(g for g in ALL_GATES if self.is_on(g))

    def scopes(self) -> list[str]:
        """Base scopes plus one per enabled gate, in a stable order."""
        return [*BASE_SCOPES, *(g.scope for g in self.enabled())]


@dataclass(frozen=True)
class Settings:
    home: Path
    gates: Gates
    max_body: int = DEFAULT_MAX_BODY

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if environ is None else environ
        home_override = env.get(HOME_ENV, "").strip()
        home = (
            Path(home_override).expanduser()
            if home_override
            else Path.home() / HOME_DIRNAME
        )
        return cls(home=home, gates=Gates.from_env(env))

    @property
    def client_file(self) -> Path:
        return self.home / "oauth_client.json"

    @property
    def accounts_file(self) -> Path:
        return self.home / "accounts.json"

    @property
    def tokens_dir(self) -> Path:
        return self.home / "tokens"

    @property
    def downloads_dir(self) -> Path:
        return self.home / "downloads"

    @property
    def outbox_dir(self) -> Path:
        return self.home / "outbox"

    def scopes(self) -> list[str]:
        return self.gates.scopes()


def gate_for_scope(scope: str) -> Gate | None:
    """The gate that requests ``scope``, or None for a base scope."""
    for gate in ALL_GATES:
        if gate.scope == scope:
            return gate
    return None


def scope_label(scope: str) -> str:
    """Short name for display: ``gmail.readonly`` -> ``readonly``."""
    if scope == SCOPE_FULL:
        return "full"
    prefix = "https://www.googleapis.com/auth/gmail."
    return scope.removeprefix(prefix) if scope.startswith(prefix) else scope
