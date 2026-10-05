"""Ready-to-paste registration blocks for MCP clients (``--print-config``).

The server itself has no client-specific code: every harness talks plain
MCP over stdio. What differs is how each one is told to start the server,
and that is all this module knows. A block carries the absolute path of
the running executable, the gates that are on in the current environment
and the home override, if any. It never reads a token or the OAuth client
file, so nothing printed is secret.

Syntax checked against each client's documentation; see docs/CLIENTS.md.
"""

from __future__ import annotations

import json
import shlex
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from wx_gmail_mcp.config import HOME_ENV, Settings

SERVER_NAME = "wx-gmail-mcp"
PACKAGE = "wx_gmail_mcp"

# Server startup (Python plus the Google client libraries) takes a few
# seconds; Codex's default allowance is 10 s.
CODEX_STARTUP_TIMEOUT_SEC = 30


@dataclass(frozen=True)
class Harness:
    name: str
    title: str
    where: str
    render: Callable[[list[str], dict[str, str]], str]


def server_env(settings: Settings, environ: Mapping[str, str]) -> dict[str, str]:
    """The environment the client must pass: gates that are on, home override.

    Values are canonical (``true``), whatever spelling turned the gate on.
    """
    env = {gate.env: "true" for gate in settings.gates.enabled()}
    home = environ.get(HOME_ENV, "").strip()
    if home:
        # Absolute: the client starts the server from a directory of its own.
        env[HOME_ENV] = str(Path(home).expanduser().absolute())
    return env


def server_command(
    argv0: str | None = None, executable: str | None = None
) -> list[str]:
    """How a client should start this very installation, as absolute paths.

    The console script that is running is the best answer: it carries the
    interpreter and environment it was installed into. Started any other
    way (``python -m wx_gmail_mcp``, a test), fall back to the interpreter
    plus ``-m``.
    """
    script = Path(argv0 if argv0 is not None else sys.argv[0])
    if script.name == SERVER_NAME and script.is_file():
        return [str(script.absolute())]
    python = executable if executable is not None else sys.executable
    # Not resolved: in a virtual environment the interpreter is a symlink,
    # and following it would lose the environment that holds the package.
    return [str(Path(python).absolute()), "-m", PACKAGE]


def _toml_string(value: str) -> str:
    # JSON string syntax is valid TOML, as long as nothing is escaped into
    # surrogate pairs, which TOML rejects.
    return json.dumps(value, ensure_ascii=False)


def _json_block(command: list[str], env: dict[str, str], **extra: str) -> str:
    entry: dict[str, object] = {**extra, "command": command[0], "args": command[1:]}
    if env:
        entry["env"] = env
    return json.dumps({"mcpServers": {SERVER_NAME: entry}}, indent=2) + "\n"


def render_claude_code(command: list[str], env: dict[str, str]) -> str:
    # ``--transport stdio`` sits between the last ``--env`` and the name, as
    # Claude Code's docs ask; everything after ``--`` is the server command.
    words = ["claude", "mcp", "add", "--scope", "user"]
    for key, value in env.items():
        words += ["--env", f"{key}={value}"]
    words += ["--transport", "stdio", SERVER_NAME, "--", *command]
    return " ".join(shlex.quote(w) for w in words) + "\n"


def render_claude_desktop(command: list[str], env: dict[str, str]) -> str:
    return _json_block(command, env)


def render_codex(command: list[str], env: dict[str, str]) -> str:
    lines = [
        f"[mcp_servers.{SERVER_NAME}]",
        f"command = {_toml_string(command[0])}",
        "args = [" + ", ".join(_toml_string(a) for a in command[1:]) + "]",
        f"startup_timeout_sec = {CODEX_STARTUP_TIMEOUT_SEC}",
    ]
    if env:
        lines += ["", f"[mcp_servers.{SERVER_NAME}.env]"]
        lines += [f"{key} = {_toml_string(value)}" for key, value in env.items()]
    return "\n".join(lines) + "\n"


def render_gemini(command: list[str], env: dict[str, str]) -> str:
    return _json_block(command, env)


def render_antigravity(command: list[str], env: dict[str, str]) -> str:
    return _json_block(command, env)


def render_cursor(command: list[str], env: dict[str, str]) -> str:
    return _json_block(command, env, type="stdio")


HARNESSES: tuple[Harness, ...] = (
    Harness(
        "claude-code",
        "Claude Code",
        "run this command in a terminal (user scope: every project)",
        render_claude_code,
    ),
    Harness(
        "claude-desktop",
        "Claude Desktop",
        "merge into ~/Library/Application Support/Claude/claude_desktop_config.json"
        " (macOS) or %APPDATA%\\Claude\\claude_desktop_config.json (Windows),"
        " then restart Claude Desktop",
        render_claude_desktop,
    ),
    Harness(
        "codex",
        "Codex CLI",
        "append to ~/.codex/config.toml",
        render_codex,
    ),
    Harness(
        "gemini",
        "Gemini CLI",
        "merge into ~/.gemini/settings.json (user scope)",
        render_gemini,
    ),
    Harness(
        "antigravity",
        "Antigravity",
        "merge into ~/.gemini/config/mcp_config.json (global, shared by the"
        " agy CLI and the IDE) or .agents/mcp_config.json (workspace)",
        render_antigravity,
    ),
    Harness(
        "cursor",
        "Cursor",
        "merge into ~/.cursor/mcp.json (global) or .cursor/mcp.json (project)",
        render_cursor,
    ),
)
HARNESS_NAMES: tuple[str, ...] = tuple(h.name for h in HARNESSES)


def harness(name: str) -> Harness:
    for h in HARNESSES:
        if h.name == name:
            return h
    raise KeyError(name)


def print_config(
    name: str,
    settings: Settings,
    environ: Mapping[str, str],
    command: list[str] | None = None,
) -> tuple[str, str]:
    """``(block, hint)``: the block to paste, and one line saying where."""
    h = harness(name)
    command = command or server_command()
    block = h.render(command, server_env(settings, environ))
    on = [g.env for g in settings.gates.enabled()]
    gates = ", ".join(on) if on else "none (read, search, labels, drafts only)"
    hint = f"{h.title}: {h.where}. Gates on: {gates}."
    if in_uv_cache(command[0]):
        hint += (
            f" Note: {command[0]} is in the uv cache, which a prune can remove;"
            " `uv tool install` gives a stable path."
        )
    return block, hint


def in_uv_cache(executable: str) -> bool:
    """True when the executable lives in a ``uvx`` environment under uv's cache."""
    return any(part.startswith("archive-v") for part in Path(executable).parts)
