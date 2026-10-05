from __future__ import annotations

import json
import shlex
import tomllib
from pathlib import Path

import pytest

from wx_gmail_mcp import clients
from wx_gmail_mcp.config import HOME_ENV

from .conftest import make_settings

CMD = ["/opt/wx/bin/wx-gmail-mcp"]
ENV = {"WX_GMAIL_ALLOW_SENDING": "true", "WX_GMAIL_ALLOW_SETTINGS": "true"}


def test_server_env_lists_only_gates_that_are_on_and_home_override(
    tmp_path: Path,
) -> None:
    s = make_settings(tmp_path, settings=True, delete=True)
    assert clients.server_env(s, {}) == {
        "WX_GMAIL_ALLOW_SETTINGS": "true",
        "WX_GMAIL_ALLOW_DELETE": "true",
    }
    # Canonical spelling, whatever the shell had; the home override rides along,
    # absolute: the client starts the server from a directory of its own.
    env = clients.server_env(s, {HOME_ENV: "~/elsewhere"})
    assert env[HOME_ENV] == str(Path("~/elsewhere").expanduser())
    relative = clients.server_env(s, {HOME_ENV: "./mail"})[HOME_ENV]
    assert Path(relative).is_absolute()
    assert Path(relative) == Path("mail").absolute()
    assert clients.server_env(make_settings(tmp_path), {HOME_ENV: "  "}) == {}


def test_server_command_prefers_the_running_console_script(tmp_path: Path) -> None:
    script = tmp_path / "bin" / "wx-gmail-mcp"
    script.parent.mkdir()
    script.write_text("#!/bin/sh\n")
    assert clients.server_command(str(script), "/usr/bin/python3") == [str(script)]


def test_server_command_falls_back_to_the_interpreter(tmp_path: Path) -> None:
    # ``python -m wx_gmail_mcp``: argv[0] is __main__.py, not the script.
    main = tmp_path / "wx_gmail_mcp" / "__main__.py"
    main.parent.mkdir()
    main.write_text("")
    venv_python = tmp_path / ".venv" / "bin" / "python"
    assert clients.server_command(str(main), str(venv_python)) == [
        str(venv_python),
        "-m",
        "wx_gmail_mcp",
    ]
    # A script name that matches but does not exist is not trusted either.
    missing = tmp_path / "nowhere" / "wx-gmail-mcp"
    assert clients.server_command(str(missing), str(venv_python))[0] == str(venv_python)


def test_claude_code_is_one_shell_command_with_env_before_transport() -> None:
    words = shlex.split(clients.render_claude_code(CMD, ENV))
    assert words[:5] == ["claude", "mcp", "add", "--scope", "user"]
    env_flags = [words[i + 1] for i, w in enumerate(words) if w == "--env"]
    assert env_flags == ["WX_GMAIL_ALLOW_SENDING=true", "WX_GMAIL_ALLOW_SETTINGS=true"]
    # ``--transport stdio`` separates the last --env from the server name.
    tail = words[words.index("--transport") :]
    assert tail == ["--transport", "stdio", "wx-gmail-mcp", "--", *CMD]


def test_claude_code_quotes_paths_with_spaces() -> None:
    cmd = ["/opt/Some Dir/bin/wx-gmail-mcp"]
    text = clients.render_claude_code(cmd, {})
    assert "--env" not in text
    assert shlex.split(text)[-1] == cmd[0]


@pytest.mark.parametrize("name", ["claude-desktop", "gemini", "antigravity", "cursor"])
def test_json_clients_share_the_mcp_servers_shape(name: str) -> None:
    block = clients.harness(name).render([*CMD, "-m", "x"], ENV)
    entry = json.loads(block)["mcpServers"]["wx-gmail-mcp"]
    assert entry["command"] == CMD[0]
    assert entry["args"] == ["-m", "x"]
    assert entry["env"] == ENV
    assert (entry.get("type") == "stdio") == (name == "cursor")
    assert (
        "env"
        not in json.loads(clients.harness(name).render(CMD, {}))["mcpServers"][
            "wx-gmail-mcp"
        ]
    )


def test_codex_block_is_valid_toml() -> None:
    table = tomllib.loads(clients.render_codex(CMD, ENV))["mcp_servers"]
    # Non-ASCII is written as is: TOML rejects JSON's surrogate escapes.
    wide = tomllib.loads(clients.render_codex(["/opt/bin/\U0001f600"], {}))
    assert wide["mcp_servers"]["wx-gmail-mcp"]["command"] == "/opt/bin/\U0001f600"
    entry = table["wx-gmail-mcp"]
    assert entry["command"] == CMD[0]
    assert entry["args"] == []
    assert entry["startup_timeout_sec"] == clients.CODEX_STARTUP_TIMEOUT_SEC
    assert entry["env"] == ENV
    bare = tomllib.loads(clients.render_codex(CMD, {}))["mcp_servers"]["wx-gmail-mcp"]
    assert "env" not in bare


def test_print_config_warns_about_a_uv_cache_path(tmp_path: Path) -> None:
    s = make_settings(tmp_path)
    cached = str(tmp_path / "uv" / "archive-v0" / "abc" / "bin" / "wx-gmail-mcp")
    _, hint = clients.print_config("codex", s, {}, [cached])
    assert "uv cache" in hint
    _, hint = clients.print_config("codex", s, {}, CMD)
    assert "uv cache" not in hint


def test_print_config_names_the_gates_and_the_place(tmp_path: Path) -> None:
    s = make_settings(tmp_path, sending=True)
    block, hint = clients.print_config("codex", s, {}, CMD)
    assert block.startswith("[mcp_servers.wx-gmail-mcp]")
    assert hint.startswith("Codex CLI: append to ~/.codex/config.toml.")
    assert hint.endswith("Gates on: WX_GMAIL_ALLOW_SENDING.")
    _, hint = clients.print_config("cursor", make_settings(tmp_path), {}, CMD)
    assert "Gates on: none" in hint
    with pytest.raises(KeyError):
        clients.harness("vim")


def test_every_harness_renders_and_names_are_unique() -> None:
    names = [h.name for h in clients.HARNESSES]
    assert len(set(names)) == len(names) == len(clients.HARNESS_NAMES)
    for h in clients.HARNESSES:
        assert "wx-gmail-mcp" in h.render(CMD, ENV)
        assert h.where
