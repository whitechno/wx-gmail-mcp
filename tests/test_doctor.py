from __future__ import annotations

import json
from pathlib import Path

import pytest

from wx_gmail_mcp import doctor, server
from wx_gmail_mcp.cli import main
from wx_gmail_mcp.config import SCOPE_SETTINGS_BASIC, Gates, Settings
from wx_gmail_mcp.doctor import FAIL, INFO, OK, WARN, Check, Locator

from .conftest import CLIENT_JSON, make_settings, write_client, write_token

SECRETS = ("placeholder-secret", "placeholder-refresh", "placeholder-access")


def nothing(name: str) -> str | None:
    return None


def tools(name: str) -> str | None:
    return f"/opt/bin/{name}"


def fake_run(outputs: dict[str, str]):
    def run(argv: list[str]) -> str:
        key = " ".join(Path(argv[0]).name.split() + argv[1:2])
        if key not in outputs:
            raise OSError(f"no output for {key}")
        return outputs[key]

    return run


def locator(tmp_path: Path, platform: str = "darwin", **env: str) -> Locator:
    user_home = tmp_path / "user"
    cwd = tmp_path / "cwd"
    user_home.mkdir(exist_ok=True)
    cwd.mkdir(exist_ok=True)
    return Locator(user_home, cwd, env, platform)


def ready(settings: Settings) -> None:
    """A complete, correctly-protected home with one healthy account."""
    write_client(settings)
    write_token(settings, "work")
    settings.home.chmod(0o700)
    settings.client_file.chmod(0o600)
    settings.accounts_file.chmod(0o600)
    settings.tokens_dir.chmod(0o700)
    for p in settings.tokens_dir.iterdir():
        p.chmod(0o600)


def by_name(checks: list[Check], name: str) -> list[Check]:
    return [c for c in checks if c.name == name]


# --- tools -------------------------------------------------------------------


def test_python_version_check() -> None:
    assert doctor.check_python((3, 14, 2)).status == OK
    old = doctor.check_python((3, 13, 9))
    assert old.status == FAIL
    assert "needs 3.14" in old.detail


def test_uv_missing_is_a_warning_and_present_shows_version() -> None:
    assert doctor.check_uv(nothing, fake_run({})).status == WARN
    ok = doctor.check_uv(tools, fake_run({"uv --version": "uv 0.9.1\n"}))
    assert ok.status == OK
    assert ok.detail == "uv 0.9.1 at /opt/bin/uv"
    broken = doctor.check_uv(tools, fake_run({}))
    assert broken.status == WARN
    assert "did not run" in broken.detail


def test_gcloud_states() -> None:
    [absent] = doctor.check_gcloud(nothing, fake_run({}))
    assert absent.status == INFO
    assert "optional" in absent.detail

    version = {"gcloud --version": "Google Cloud SDK 500.0.0\nbq 2.0\n"}
    [ok, login] = doctor.check_gcloud(tools, fake_run({**version, "gcloud auth": ""}))
    assert (ok.status, ok.detail) == (OK, "Google Cloud SDK 500.0.0 at /opt/bin/gcloud")
    assert login.status == WARN
    assert "gcloud auth login" in login.detail

    [_, login] = doctor.check_gcloud(
        tools, fake_run({**version, "gcloud auth": "you@example.com\n"})
    )
    assert (login.status, login.detail) == (OK, "active account you@example.com")

    [_, login] = doctor.check_gcloud(tools, fake_run(version))
    assert login.status == WARN
    assert "could not check" in login.detail


# --- home directory ----------------------------------------------------------


def test_home_missing_wrong_mode_and_ok(tmp_path: Path) -> None:
    s = make_settings(tmp_path / "home")
    missing = doctor.check_home(s, {})
    assert missing.status == FAIL
    assert f"mkdir -m 700 {s.home}" in missing.detail
    s.home.mkdir(mode=0o755)
    loose = doctor.check_home(s, {"WX_GMAIL_MCP_HOME": str(s.home)})
    assert loose.status == FAIL
    assert "mode 755, expected 700" in loose.detail
    assert "(WX_GMAIL_MCP_HOME)" in loose.detail
    s.home.chmod(0o700)
    assert doctor.check_home(s, {}).status == OK


def test_client_json_shapes(tmp_path: Path) -> None:
    s = make_settings(tmp_path / "home")
    s.home.mkdir()
    assert doctor.check_client_json(s).status == FAIL
    assert "missing" in doctor.check_client_json(s).detail

    s.client_file.write_text("{not json")
    assert "not readable JSON" in doctor.check_client_json(s).detail

    s.client_file.write_text(json.dumps({"web": CLIENT_JSON["installed"]}))
    web = doctor.check_client_json(s)
    assert web.status == FAIL
    assert "Web application client" in web.detail

    s.client_file.write_text(json.dumps({"other": {}}))
    assert "no 'installed' key" in doctor.check_client_json(s).detail

    partial = {"installed": {"client_id": "placeholder.apps.example"}}
    s.client_file.write_text(json.dumps(partial))
    lacking = doctor.check_client_json(s)
    assert "lacks client_secret, auth_uri, token_uri" in lacking.detail

    write_client(s)
    s.client_file.chmod(0o644)
    loose = doctor.check_client_json(s)
    assert loose.status == FAIL
    assert f"chmod 600 {s.client_file}" in loose.detail

    s.client_file.chmod(0o600)
    ok = doctor.check_client_json(s)
    assert ok.status == OK
    assert ok.detail == "Desktop app client, project unknown, mode 600"
    for secret in SECRETS:
        assert secret not in ok.detail
    assert "placeholder.apps.example" not in ok.detail


def test_private_files_modes(tmp_path: Path) -> None:
    s = make_settings(tmp_path / "home")
    s.home.mkdir()
    assert doctor.check_private_files(s).status == INFO
    write_token(s, "work")
    write_token(s, "home")
    loose = doctor.check_private_files(s)
    assert loose.status == FAIL
    # write_token uses default modes, so every path is listed with its fix.
    assert f"chmod 600 {s.accounts_file}" in loose.detail
    assert f"chmod 700 {s.tokens_dir}" in loose.detail
    assert f"chmod 600 {s.tokens_dir / 'home.json'}" in loose.detail
    ready(s)
    ok = doctor.check_private_files(s)
    assert (ok.status, ok.detail) == (OK, "accounts.json, tokens/, 2 token files")


# --- gates and accounts ------------------------------------------------------


def test_gates_line(tmp_path: Path) -> None:
    none = doctor.check_gates(make_settings(tmp_path))
    assert none.status == INFO
    assert none.detail.startswith("none on")
    assert "scopes: readonly, modify" in none.detail
    some = doctor.check_gates(make_settings(tmp_path, settings=True, delete=True))
    assert "WX_GMAIL_ALLOW_SETTINGS (settings.basic)" in some.detail
    assert "WX_GMAIL_ALLOW_DELETE (full)" in some.detail
    assert some.detail.endswith("scopes: readonly, modify, settings.basic, full")


def test_accounts_none_healthy_and_broken(tmp_path: Path) -> None:
    s = make_settings(tmp_path / "home", settings=True)
    s.home.mkdir()
    [none] = doctor.check_accounts(s)
    assert none.status == WARN
    assert "WX_GMAIL_ALLOW_SETTINGS=true wx-gmail-mcp --auth <alias>" in none.detail

    write_token(s, "work", refresh_token="placeholder-refresh")
    write_token(s, "full", scopes=(SCOPE_SETTINGS_BASIC,), email="full@example.com")
    (s.tokens_dir / "full.json").write_text("{broken")
    checks = doctor.check_accounts(s)
    assert [(c.status, c.name) for c in checks] == [
        (OK, "account work"),
        (WARN, "account work"),
        (FAIL, "account full"),
    ]
    assert checks[0].detail == "you@example.com, scopes: modify, readonly"
    assert "settings.basic scope is not granted" in checks[1].detail
    assert "--auth work --email you@example.com" in checks[1].detail
    assert "full@example.com: Token file for 'full' is unreadable" in checks[2].detail
    for secret in SECRETS:
        assert all(secret not in c.detail for c in checks)


def test_accounts_file_error_is_one_failure(tmp_path: Path) -> None:
    s = make_settings(tmp_path / "home")
    s.home.mkdir()
    s.accounts_file.write_text("[]")
    [bad] = doctor.check_accounts(s)
    assert bad.status == FAIL
    assert "JSON object" in bad.detail


# --- client registrations ----------------------------------------------------


def mcp_block(command: str, **env: str) -> str:
    entry: dict[str, object] = {"command": command, "args": []}
    if env:
        entry["env"] = env
    return json.dumps({"mcpServers": {"wx-gmail-mcp": entry}})


def test_registrations_not_found(tmp_path: Path) -> None:
    s = make_settings(tmp_path / "home")
    checks = doctor.check_registrations(s, locator(tmp_path))
    assert [c.name for c in checks] == [
        "client Claude Code",
        "client Claude Desktop",
        "client Codex CLI",
        "client Antigravity",
        "client Cursor",
    ]
    assert all(c.status == INFO and c.detail == "not registered" for c in checks)


def test_registrations_found_in_every_client(tmp_path: Path) -> None:
    loc = locator(tmp_path)
    s = Settings(home=loc.user_home / ".wx-gmail-mcp", gates=Gates())
    exe = tmp_path / "bin" / "wx-gmail-mcp"
    exe.parent.mkdir()
    exe.write_text("")
    claude = {
        "mcpServers": {"wx-gmail-mcp": {"command": str(exe), "args": []}},
        "projects": {
            str(loc.cwd): json.loads(
                mcp_block(
                    "uv", WX_GMAIL_ALLOW_SETTINGS="true", WX_GMAIL_ALLOW_DELETE="1"
                )
            )
        },
    }
    (loc.user_home / ".claude.json").write_text(json.dumps(claude))
    (loc.cwd / ".mcp.json").write_text(mcp_block(str(exe)))
    desktop = loc.claude_desktop_file()
    desktop.parent.mkdir(parents=True)
    desktop.write_text(mcp_block(str(exe), WX_GMAIL_ALLOW_SENDING="true"))
    codex = loc.codex_file()
    codex.parent.mkdir()
    codex.write_text(
        "[mcp_servers.wx-gmail-mcp]\n"
        f'command = "{exe}"\n'
        'args = ["--flag"]\n'
        "startup_timeout_sec = 30\n\n"
        "[mcp_servers.wx-gmail-mcp.env]\n"
        'WX_GMAIL_ALLOW_DELETE = "true"\n'
    )
    agy = loc.user_home / ".gemini/config/mcp_config.json"
    agy.parent.mkdir(parents=True)
    agy.write_text(mcp_block(str(exe)))
    (loc.cwd / ".agents").mkdir()
    (loc.cwd / ".agents/mcp_config.json").write_text(mcp_block(str(exe)))
    (loc.cwd / ".cursor").mkdir()
    (loc.cwd / ".cursor/mcp.json").write_text(mcp_block(str(exe)))

    checks = doctor.check_registrations(s, loc)
    details = [(c.name, c.status, c.detail) for c in checks]
    assert [d[0] for d in details] == [
        "client Claude Code",
        "client Claude Code",
        "client Claude Code",
        "client Claude Desktop",
        "client Codex CLI",
        "client Antigravity",
        "client Antigravity",
        "client Cursor",
    ]
    assert all(status == INFO for _, status, _ in details)
    user, local, project = (d[2] for d in details[:3])
    assert user.startswith(f"user scope, {loc.user_home / '.claude.json'}")
    assert f"command: {exe}; gates: none" in user
    assert local.startswith("local scope")
    # Only the exact value ``true`` counts as on; "1" is off, as in the server.
    assert "command: uv; gates: WX_GMAIL_ALLOW_SETTINGS" in local
    assert "WX_GMAIL_ALLOW_DELETE" not in local
    assert project.startswith(f"project scope, {loc.cwd / '.mcp.json'}")
    assert "gates: WX_GMAIL_ALLOW_SENDING" in details[3][2]
    assert f"command: {exe} --flag; gates: WX_GMAIL_ALLOW_DELETE" in details[4][2]
    assert details[5][2].startswith("global")
    assert details[6][2].startswith("workspace")
    assert details[7][2].startswith("project")


def test_registration_warnings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    s = make_settings(tmp_path / "home")  # not the default home
    loc = locator(tmp_path)
    missing = tmp_path / "gone" / "wx-gmail-mcp"
    (loc.user_home / ".cursor").mkdir()
    (loc.user_home / ".cursor/mcp.json").write_text(mcp_block(str(missing)))
    agy = loc.user_home / ".gemini/config/mcp_config.json"
    agy.parent.mkdir(parents=True)
    # A relative home in the registration matches once made absolute.
    monkeypatch.chdir(tmp_path)
    agy.write_text(mcp_block("uv", WX_GMAIL_MCP_HOME="home"))
    (loc.cwd / ".mcp.json").write_text(mcp_block("uv", WX_GMAIL_MCP_HOME="/elsewhere"))
    checks = {c.name: c for c in doctor.check_registrations(s, loc)}
    cursor = checks["client Cursor"]
    assert cursor.status == WARN
    assert "(command not found)" in cursor.detail
    assert "the client uses the default home" in cursor.detail
    assert checks["client Antigravity"].status == INFO
    assert checks["client Antigravity"].detail.endswith("home: home")
    code = checks["client Claude Code"]
    assert code.status == WARN
    assert "home: /elsewhere; (not the home this doctor checked)" in code.detail


def test_unreadable_client_config_is_a_warning(tmp_path: Path) -> None:
    s = make_settings(tmp_path / "home")
    loc = locator(tmp_path)
    codex = loc.codex_file()
    codex.parent.mkdir()
    codex.write_text("this = is = not toml")
    [bad] = by_name(doctor.check_registrations(s, loc), "client Codex CLI")
    assert bad.status == WARN
    assert "could not read its config" in bad.detail


def test_locator_paths_per_platform(tmp_path: Path) -> None:
    mac = locator(tmp_path, "darwin")
    assert mac.claude_desktop_file() == (
        mac.user_home / "Library/Application Support/Claude/claude_desktop_config.json"
    )
    win = locator(tmp_path, "win32", APPDATA=str(tmp_path / "Roaming"))
    assert win.claude_desktop_file() == (
        tmp_path / "Roaming/Claude/claude_desktop_config.json"
    )
    linux = locator(tmp_path, "linux")
    assert linux.claude_desktop_file() == (
        linux.user_home / ".config/Claude/claude_desktop_config.json"
    )
    assert linux.codex_file() == linux.user_home / ".codex/config.toml"
    custom = locator(tmp_path, "linux", CODEX_HOME=str(tmp_path / "cx"))
    assert custom.codex_file() == tmp_path / "cx/config.toml"


# --- all together ------------------------------------------------------------


def test_run_doctor_passes_on_a_ready_home(tmp_path: Path) -> None:
    s = make_settings(tmp_path / "home")
    ready(s)
    checks = doctor.run_doctor(
        s,
        {"WX_GMAIL_MCP_HOME": str(s.home)},
        locator(tmp_path),
        which=nothing,
        run=fake_run({}),
        python_version=(3, 14, 0),
    )
    assert checks[0].name == "wx-gmail-mcp"
    assert checks[-1] == Check(OK, "doctor", "all checks passed")
    assert not any(c.failed for c in checks)
    text = doctor.doctor_text(checks)
    assert "\nok   home: " in text
    assert "\nwarn uv: not found" in text
    for secret in SECRETS:
        assert secret not in text


def test_run_doctor_counts_failures(tmp_path: Path) -> None:
    s = make_settings(tmp_path / "home")
    checks = doctor.run_doctor(
        s,
        {},
        locator(tmp_path),
        which=nothing,
        run=fake_run({}),
        python_version=(3, 13),
    )
    failed = [c for c in checks if c.failed]
    assert [c.name for c in failed] == ["python", "home", "oauth client", "doctor"]
    assert checks[-1].detail == "3 checks failed"


def test_cli_doctor_exit_codes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("WX_GMAIL_MCP_HOME", str(home))
    for var in ("WX_GMAIL_ALLOW_SENDING", "WX_GMAIL_ALLOW_SETTINGS"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("WX_GMAIL_ALLOW_DELETE", "true")
    monkeypatch.setattr(server, "serve", lambda s: pytest.fail("served"))
    monkeypatch.setattr(doctor, "run_command", lambda argv: "")
    monkeypatch.setattr(doctor, "Locator", lambda *a: locator(tmp_path))
    assert main(["--doctor"]) == 1
    out = capsys.readouterr().out
    assert "FAIL home: " in out
    assert "FAIL doctor: " in out

    ready(make_settings(home))
    assert main(["--doctor"]) == 0
    out = capsys.readouterr().out
    assert "ok   home: " in out
    assert "WX_GMAIL_ALLOW_DELETE (full)" in out
    assert "warn account work: WX_GMAIL_ALLOW_DELETE is on" in out
    assert out.rstrip().endswith("ok   doctor: all checks passed")
    for secret in SECRETS:
        assert secret not in out
