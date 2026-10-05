"""``--doctor``: one line per check of an installation, nothing secret printed.

Checks the interpreter and ``uv``, whether ``gcloud`` is installed and
logged in, the home directory layout and modes, the OAuth client file's
shape, each account's token and granted scopes against the gates that
are on, and which MCP clients carry a registration (a read-only look at
the files ``--print-config`` targets). Every external call is injectable
so tests run without a shell or a network.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wx_gmail_mcp import __version__, accounts, auth, clients
from wx_gmail_mcp.config import HOME_ENV, Settings, scope_label
from wx_gmail_mcp.errors import WxGmailError

MIN_PYTHON = (3, 14)

OK = "ok"
INFO = "info"
WARN = "warn"
FAIL = "FAIL"

SECRET_KEYS = ("client_id", "client_secret", "auth_uri", "token_uri")


@dataclass(frozen=True)
class Check:
    status: str
    name: str
    detail: str

    def line(self) -> str:
        return f"{self.status:<4} {self.name}: {self.detail}"

    @property
    def failed(self) -> bool:
        return self.status == FAIL


Which = Callable[[str], str | None]
Runner = Callable[[list[str]], str]


def run_command(argv: list[str]) -> str:
    """Run a tool and return its stdout; raise ``OSError`` on failure."""
    try:
        done = subprocess.run(  # noqa: S603 - fixed argv, no shell
            argv, capture_output=True, text=True, timeout=60, check=False
        )
    except subprocess.TimeoutExpired as e:
        raise OSError(f"{argv[0]} timed out") from e
    if done.returncode != 0:
        err = done.stderr.strip().splitlines()
        raise OSError(err[-1] if err else f"{argv[0]} exited {done.returncode}")
    return done.stdout


def mode_of(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _mode_ok(path: Path, want: int) -> bool:
    # Modes mean nothing on Windows; there the check is "exists".
    return os.name != "posix" or mode_of(path) == want


# --- tools -------------------------------------------------------------------


def check_python(version: tuple[int, ...] = tuple(sys.version_info[:3])) -> Check:
    text = ".".join(str(v) for v in version[:3])
    if tuple(version[:2]) >= MIN_PYTHON:
        return Check(OK, "python", f"{text} at {sys.executable}")
    need = ".".join(str(v) for v in MIN_PYTHON)
    return Check(FAIL, "python", f"{text}; wx-gmail-mcp needs {need} or newer")


def check_uv(which: Which, run: Runner) -> Check:
    path = which("uv")
    if not path:
        return Check(
            WARN,
            "uv",
            "not found; it installs and upgrades wx-gmail-mcp "
            "(https://docs.astral.sh/uv/)",
        )
    try:
        version = run([path, "--version"]).strip() or "unknown version"
    except OSError as e:
        return Check(WARN, "uv", f"{path} did not run ({e})")
    return Check(OK, "uv", f"{version} at {path}")


def check_gcloud(which: Which, run: Runner) -> list[Check]:
    path = which("gcloud")
    if not path:
        return [
            Check(
                INFO,
                "gcloud",
                "not installed; optional (the console steps replace it)",
            )
        ]
    try:
        first = run([path, "--version"]).strip().splitlines()
        version = first[0] if first else "unknown version"
    except OSError as e:
        return [Check(WARN, "gcloud", f"{path} did not run ({e})")]
    checks = [Check(OK, "gcloud", f"{version} at {path}")]
    try:
        account = run(
            [path, "auth", "list", "--filter=status:ACTIVE", "--format=value(account)"]
        ).strip()
    except OSError as e:
        return [*checks, Check(WARN, "gcloud login", f"could not check ({e})")]
    if account:
        checks.append(Check(OK, "gcloud login", f"active account {account}"))
    else:
        checks.append(
            Check(WARN, "gcloud login", "no active account; run: gcloud auth login")
        )
    return checks


# --- home directory ----------------------------------------------------------


def check_home(settings: Settings, environ: Mapping[str, str]) -> Check:
    home = settings.home
    origin = f" ({HOME_ENV})" if environ.get(HOME_ENV, "").strip() else ""
    if not home.is_dir():
        return Check(
            FAIL, "home", f"{home}{origin} missing; create it: mkdir -m 700 {home}"
        )
    if not _mode_ok(home, 0o700):
        return Check(
            FAIL,
            "home",
            f"{home}{origin} has mode {mode_of(home):o}, expected 700; "
            f"fix: chmod 700 {home}",
        )
    return Check(OK, "home", f"{home}{origin}, mode 700")


def check_client_json(settings: Settings) -> Check:
    path = settings.client_file
    name = "oauth client"
    if not path.is_file():
        return Check(
            FAIL,
            name,
            f"{path} missing; download the Desktop app client JSON from the "
            "Google Cloud console and save it there (mode 600)",
        )
    try:
        data = json.loads(path.read_text())
    except (ValueError, OSError) as e:
        return Check(FAIL, name, f"{path} is not readable JSON ({e})")
    if not isinstance(data, dict):
        return Check(FAIL, name, f"{path} does not hold a JSON object")
    if "web" in data:
        return Check(
            FAIL,
            name,
            f"{path} is a Web application client; wx-gmail-mcp needs a "
            "Desktop app client (its JSON has an 'installed' key)",
        )
    installed = data.get("installed")
    if not isinstance(installed, dict):
        return Check(
            FAIL,
            name,
            f"{path} has no 'installed' key; download the Desktop app client JSON",
        )
    missing = [k for k in SECRET_KEYS if not installed.get(k)]
    if missing:
        return Check(FAIL, name, f"{path} lacks {', '.join(missing)}")
    if not _mode_ok(path, 0o600):
        return Check(
            FAIL,
            name,
            f"{path} has mode {mode_of(path):o}, expected 600; fix: chmod 600 {path}",
        )
    project = installed.get("project_id") or "unknown"
    return Check(OK, name, f"Desktop app client, project {project}, mode 600")


def check_private_files(settings: Settings) -> Check:
    """accounts.json 600, tokens/ 700, every token file 600."""
    wrong: list[str] = []
    seen: list[str] = []
    if settings.accounts_file.is_file():
        seen.append("accounts.json")
        if not _mode_ok(settings.accounts_file, 0o600):
            wrong.append(f"chmod 600 {settings.accounts_file}")
    if settings.tokens_dir.is_dir():
        seen.append("tokens/")
        if not _mode_ok(settings.tokens_dir, 0o700):
            wrong.append(f"chmod 700 {settings.tokens_dir}")
        tokens = sorted(p for p in settings.tokens_dir.iterdir() if p.is_file())
        seen.append(f"{len(tokens)} token file{'' if len(tokens) == 1 else 's'}")
        wrong.extend(f"chmod 600 {p}" for p in tokens if not _mode_ok(p, 0o600))
    if wrong:
        return Check(FAIL, "permissions", "fix: " + "; ".join(wrong))
    if not seen:
        return Check(INFO, "permissions", "no accounts.json or tokens/ yet")
    return Check(OK, "permissions", ", ".join(seen))


# --- gates and accounts ------------------------------------------------------


def check_gates(settings: Settings) -> Check:
    on = settings.gates.enabled()
    scopes = ", ".join(scope_label(s) for s in settings.scopes())
    if not on:
        return Check(
            INFO,
            "gates",
            f"none on (read, search, labels, organize, drafts); scopes: {scopes}",
        )
    names = ", ".join(f"{g.env} ({scope_label(g.scope)})" for g in on)
    return Check(INFO, "gates", f"{names}; scopes: {scopes}")


def check_accounts(settings: Settings) -> list[Check]:
    try:
        accts = accounts.load_accounts(settings)
    except WxGmailError as e:
        return [Check(FAIL, "accounts", str(e))]
    if not accts:
        return [
            Check(
                WARN,
                "accounts",
                "none; authorize one with: "
                + auth.reauth_command(settings, "<alias>", "you@example.com"),
            )
        ]
    checks: list[Check] = []
    for alias, email in accts.items():
        name = f"account {alias}"
        try:
            creds = auth.load_credentials(settings, alias)
        except WxGmailError as e:
            checks.append(Check(FAIL, name, f"{email}: {e}"))
            continue
        granted = auth.granted_scopes(creds)
        checks.append(Check(OK, name, f"{email}, scopes: {auth.scopes_text(granted)}"))
        for gate in auth.ungranted_gates(settings, granted):
            checks.append(
                Check(
                    WARN,
                    name,
                    f"{gate.env} is on but the {scope_label(gate.scope)} scope is "
                    f"not granted; its tools refuse this account. Re-run: "
                    f"{auth.reauth_command(settings, alias, email)}",
                )
            )
    return checks


# --- client registrations ----------------------------------------------------


@dataclass(frozen=True)
class Registration:
    scope: str
    path: Path
    command: list[str]
    env: dict[str, str]


@dataclass(frozen=True)
class Locator:
    """Where a machine keeps its client configuration files."""

    user_home: Path
    cwd: Path
    environ: Mapping[str, str]
    platform: str = sys.platform

    def claude_desktop_file(self) -> Path:
        if self.platform == "darwin":
            return (
                self.user_home
                / "Library/Application Support/Claude/claude_desktop_config.json"
            )
        if self.platform == "win32":
            appdata = self.environ.get("APPDATA", "").strip()
            base = Path(appdata) if appdata else self.user_home / "AppData/Roaming"
            return base / "Claude/claude_desktop_config.json"
        return self.user_home / ".config/Claude/claude_desktop_config.json"

    def codex_file(self) -> Path:
        codex_home = self.environ.get("CODEX_HOME", "").strip()
        base = self.user_home / ".codex"
        if codex_home:
            base = Path(codex_home).expanduser()
        return base / "config.toml"


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text())
    return data if isinstance(data, dict) else {}


def _entry(block: Mapping[str, Any]) -> Registration | None:
    """A ``mcpServers``-style entry for the server, if present."""
    servers = block.get("mcpServers")
    if not isinstance(servers, dict):
        return None
    entry = servers.get(clients.SERVER_NAME)
    if not isinstance(entry, dict):
        return None
    return _registration("", Path(), entry)


def _registration(scope: str, path: Path, entry: Mapping[str, Any]) -> Registration:
    command = [str(entry.get("command", ""))]
    args = entry.get("args")
    if isinstance(args, list):
        command += [str(a) for a in args]
    env = entry.get("env")
    env_map = {str(k): str(v) for k, v in env.items()} if isinstance(env, dict) else {}
    return Registration(scope, path, command, env_map)


def _with(reg: Registration | None, scope: str, path: Path) -> list[Registration]:
    return [Registration(scope, path, reg.command, reg.env)] if reg else []


def _json_file(path: Path, scope: str) -> list[Registration]:
    if not path.is_file():
        return []
    return _with(_entry(_load_json(path)), scope, path)


def _claude_code(loc: Locator) -> list[Registration]:
    found: list[Registration] = []
    user_file = loc.user_home / ".claude.json"
    if user_file.is_file():
        data = _load_json(user_file)
        found += _with(_entry(data), "user scope", user_file)
        projects = data.get("projects")
        if isinstance(projects, dict):
            project = projects.get(str(loc.cwd))
            if isinstance(project, dict):
                found += _with(_entry(project), "local scope", user_file)
    found += _json_file(loc.cwd / ".mcp.json", "project scope")
    return found


def _claude_desktop(loc: Locator) -> list[Registration]:
    return _json_file(loc.claude_desktop_file(), "app config")


def _codex(loc: Locator) -> list[Registration]:
    path = loc.codex_file()
    if not path.is_file():
        return []
    data = tomllib.loads(path.read_text())
    servers = data.get("mcp_servers")
    if not isinstance(servers, dict):
        return []
    entry = servers.get(clients.SERVER_NAME)
    if not isinstance(entry, dict):
        return []
    return [_registration("user config", path, entry)]


def _antigravity(loc: Locator) -> list[Registration]:
    return _json_file(
        loc.user_home / ".gemini/config/mcp_config.json", "global"
    ) + _json_file(loc.cwd / ".agents/mcp_config.json", "workspace")


def _cursor(loc: Locator) -> list[Registration]:
    return _json_file(loc.user_home / ".cursor/mcp.json", "global") + _json_file(
        loc.cwd / ".cursor/mcp.json", "project"
    )


READERS: dict[str, Callable[[Locator], list[Registration]]] = {
    "claude-code": _claude_code,
    "claude-desktop": _claude_desktop,
    "codex": _codex,
    "antigravity": _antigravity,
    "cursor": _cursor,
}


def describe_registration(reg: Registration, settings: Settings) -> Check:
    gates = [k for k in reg.env if k.startswith("WX_GMAIL_ALLOW_")]
    parts = [f"{reg.scope}, {reg.path}", f"command: {' '.join(reg.command)}"]
    parts.append("gates: " + (", ".join(gates) if gates else "none"))
    status = INFO
    home = reg.env.get(HOME_ENV, "").strip()
    if home:
        parts.append(f"home: {home}")
        if Path(home).expanduser() != settings.home:
            status = WARN
            parts.append("(not the home this doctor checked)")
    elif settings.home != Path.home() / ".wx-gmail-mcp":
        status = WARN
        parts.append(f"(no {HOME_ENV}; the client uses the default home)")
    exe = reg.command[0]
    if not exe:
        status = WARN
        parts.append("(no command)")
    elif Path(exe).is_absolute() and not Path(exe).exists():
        status = WARN
        parts.append("(command not found)")
    return Check(status, "", "; ".join(parts))


def check_registrations(settings: Settings, loc: Locator) -> list[Check]:
    checks: list[Check] = []
    for harness in clients.HARNESSES:
        name = f"client {harness.title}"
        try:
            regs = READERS[harness.name](loc)
        except (ValueError, OSError) as e:
            checks.append(Check(WARN, name, f"could not read its config ({e})"))
            continue
        if not regs:
            checks.append(Check(INFO, name, "not registered"))
            continue
        for reg in regs:
            described = describe_registration(reg, settings)
            checks.append(Check(described.status, name, described.detail))
    return checks


# --- all together -------------------------------------------------------------


def run_doctor(
    settings: Settings,
    environ: Mapping[str, str],
    loc: Locator,
    *,
    which: Which | None = None,
    run: Runner | None = None,
    python_version: tuple[int, ...] = tuple(sys.version_info[:3]),
) -> list[Check]:
    # Resolved at call time, so a test can patch the module's functions.
    which = shutil.which if which is None else which
    run = run_command if run is None else run
    checks = [
        Check(
            INFO,
            "wx-gmail-mcp",
            f"{__version__}, command: {' '.join(clients.server_command())}",
        ),
        check_python(python_version),
        check_uv(which, run),
        *check_gcloud(which, run),
        check_home(settings, environ),
        check_client_json(settings),
        check_private_files(settings),
        check_gates(settings),
        *check_accounts(settings),
        *check_registrations(settings, loc),
    ]
    failed = sum(1 for c in checks if c.failed)
    summary = (
        "all checks passed"
        if not failed
        else f"{failed} check{'' if failed == 1 else 's'} failed"
    )
    checks.append(Check(FAIL if failed else OK, "doctor", summary))
    return checks


def doctor_text(checks: list[Check]) -> str:
    return "\n".join(c.line() for c in checks)
