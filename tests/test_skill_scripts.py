"""The setup skill's scripts and SKILL.md, exercised without a shell or network."""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from .conftest import CLIENT_JSON

SKILL = Path(__file__).resolve().parents[1] / ".agents/skills/setting-up-wx-gmail-mcp"
SCRIPTS = SKILL / "scripts"
SECRETS = ("placeholder-secret", "placeholder.apps.example")


def load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def which_none(name: str) -> str | None:
    return None


def which_all(name: str) -> str | None:
    return f"/opt/bin/{name}"


# --- SKILL.md ----------------------------------------------------------------


def test_skill_frontmatter_and_layout() -> None:
    text = (SKILL / "SKILL.md").read_text()
    match = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert match, "SKILL.md must start with YAML frontmatter"
    front = dict(
        line.split(": ", 1) for line in match.group(1).splitlines() if ": " in line
    )
    assert front["name"] == SKILL.name
    assert re.fullmatch(r"[a-z0-9-]{1,64}", front["name"])
    assert 20 < len(front["description"]) <= 1024
    assert len(text.splitlines()) < 200, "SKILL.md loads into context; keep it short"
    for ref in ("gcloud.md", "clients.md", "troubleshooting.md"):
        assert (SKILL / "references" / ref).is_file()
        assert f"references/{ref}" in text
    for script in ("prereqs.py", "gcloud_project.py", "install_client_json.py"):
        assert (SCRIPTS / script).is_file()
        assert f"scripts/{script}" in text
    # Harness-neutral: no assistant's name in the skill or its references.
    for path in [SKILL / "SKILL.md", *(SKILL / "references").iterdir()]:
        body = re.sub(r"\s+", " ", path.read_text())
        # Product names and Claude Desktop's own file paths are fine.
        for allowed in ("Claude Code", "Claude Desktop", "/Claude/", "\\Claude\\"):
            body = body.replace(allowed, "")
        assert "Claude" not in body, path


def test_claude_skills_symlink_reaches_the_skill() -> None:
    link = SKILL.parents[2] / ".claude/skills"
    assert link.is_symlink()
    assert (link / SKILL.name / "SKILL.md").is_file()


# --- prereqs.py --------------------------------------------------------------


def test_prereqs_without_uv_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    mod = load("prereqs")
    monkeypatch.setattr(mod.shutil, "which", which_none)
    monkeypatch.setattr(mod, "run", lambda argv: "")
    monkeypatch.delenv("WX_GMAIL_MCP_HOME", raising=False)
    assert mod.main() == 1
    out = capsys.readouterr().out
    assert "FAIL uv: not found" in out
    assert "info gcloud: not installed" in out
    assert "info wx-gmail-mcp: not installed yet" in out
    assert out.rstrip().endswith("info home: ~/.wx-gmail-mcp")


def test_prereqs_with_everything(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    mod = load("prereqs")
    outputs = {
        "uv --version": "uv 0.9.0",
        "uv python": "/opt/py/bin/python3.14",
        "gcloud --version": "Google Cloud SDK 1.0\nbq 2",
        "gcloud auth": "you@example.com",
    }
    monkeypatch.setattr(mod.shutil, "which", which_all)
    monkeypatch.setattr(
        mod,
        "run",
        lambda argv: outputs.get(" ".join([Path(argv[0]).name, argv[1]]), ""),
    )
    monkeypatch.setenv("WX_GMAIL_MCP_HOME", "/opt/home")
    assert mod.main() == 0
    out = capsys.readouterr().out
    assert "ok   uv: uv 0.9.0 at /opt/bin/uv" in out
    assert "ok   python: 3.14+ at /opt/py/bin/python3.14" in out
    assert "ok   gcloud: Google Cloud SDK 1.0 at /opt/bin/gcloud" in out
    assert "ok   gcloud login: active account you@example.com" in out
    assert "ok   wx-gmail-mcp: installed at /opt/bin/wx-gmail-mcp" in out
    assert "info home: /opt/home (WX_GMAIL_MCP_HOME)" in out


# --- gcloud_project.py -------------------------------------------------------


class fake_gcloud:  # lower-case: it stands in for the module function
    """Answers ``gcloud(path, *args)`` from a table keyed by the first two words."""

    def __init__(self, responses: dict[str, tuple[int, str, str]]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def __call__(self, path: str, *args: str) -> tuple[int, str, str]:
        key = " ".join(args[:2])
        self.calls.append(" ".join(args))
        return self.responses.get(key, (1, "", f"unexpected: {key}"))


def test_gcloud_project_urls_need_no_gcloud(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    mod = load("gcloud_project")
    monkeypatch.setattr(mod.shutil, "which", which_none)
    assert mod.main(["my-proj", "--urls"]) == 0
    out = capsys.readouterr().out
    assert "https://console.cloud.google.com/auth/clients?project=my-proj" in out
    assert "gmail.googleapis.com?project=my-proj" in out
    assert mod.main(["my-proj"]) == 1
    assert "FAIL gcloud: not installed" in capsys.readouterr().out


def test_gcloud_project_reports_without_creating(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    mod = load("gcloud_project")
    monkeypatch.setattr(mod.shutil, "which", which_all)
    gcloud = fake_gcloud(
        {"auth list": (0, "you@example.com", ""), "projects describe": (1, "", "nope")}
    )
    monkeypatch.setattr(mod, "gcloud", gcloud)
    assert mod.main(["my-proj"]) == 1
    out = capsys.readouterr().out
    assert "ok   gcloud: logged in as you@example.com" in out
    assert "info project: my-proj not found" in out
    assert not any(c.startswith("projects create") for c in gcloud.calls)


def test_gcloud_project_creates_and_enables(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    mod = load("gcloud_project")
    monkeypatch.setattr(mod.shutil, "which", which_all)
    gcloud = fake_gcloud(
        {
            "auth list": (0, "you@example.com", ""),
            "projects describe": (1, "", "nope"),
            "projects create": (0, "", ""),
            "services list": (0, "", ""),
            "services enable": (0, "", ""),
        }
    )
    monkeypatch.setattr(mod, "gcloud", gcloud)
    assert mod.main(["my-proj", "--create", "--enable"]) == 0
    out = capsys.readouterr().out
    assert "ok   project: my-proj created" in out
    assert "ok   gmail api: enabled on my-proj" in out
    assert "auth/audience?project=my-proj" in out
    assert "projects create my-proj --name=wx-gmail-mcp" in gcloud.calls
    assert "services enable gmail.googleapis.com --project=my-proj" in gcloud.calls
    # Every project-scoped call names the project; the default is never used.
    assert all(
        "my-proj" in c for c in gcloud.calls if c.startswith(("services", "projects"))
    )


def test_gcloud_project_is_idempotent_and_reports_failures(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    mod = load("gcloud_project")
    monkeypatch.setattr(mod.shutil, "which", which_all)
    done = fake_gcloud(
        {
            "auth list": (0, "you@example.com", ""),
            "projects describe": (0, "my-proj", ""),
            "services list": (0, "gmail.googleapis.com", ""),
        }
    )
    monkeypatch.setattr(mod, "gcloud", done)
    assert mod.main(["my-proj", "--create", "--enable"]) == 0
    out = capsys.readouterr().out
    assert "ok   project: my-proj exists" in out
    assert "ok   gmail api: enabled on my-proj" in out
    assert not any(
        c.startswith(("projects create", "services enable")) for c in done.calls
    )

    taken = fake_gcloud(
        {
            "auth list": (0, "you@example.com", ""),
            "projects describe": (1, "", ""),
            "projects create": (1, "", "ERROR: already exists"),
        }
    )
    monkeypatch.setattr(mod, "gcloud", taken)
    assert mod.main(["my-proj", "--create"]) == 1
    assert (
        "FAIL project: create failed: ERROR: already exists" in capsys.readouterr().out
    )

    monkeypatch.setattr(mod, "gcloud", fake_gcloud({"auth list": (0, "", "")}))
    assert mod.main(["my-proj"]) == 1
    assert "FAIL gcloud: no active account" in capsys.readouterr().out


# --- install_client_json.py --------------------------------------------------


@pytest.fixture
def homes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """(user home with a Downloads folder, wx home) with the env pointing at them."""
    user = tmp_path / "user"
    (user / "Downloads").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: user))
    wx = tmp_path / "wx-home"
    monkeypatch.setenv("WX_GMAIL_MCP_HOME", str(wx))
    return user, wx


def write(path: Path, data: dict[str, Any]) -> Path:
    path.write_text(json.dumps(data))
    return path


def test_install_moves_newest_download_and_secures_it(
    homes: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    user, wx = homes
    mod = load("install_client_json")
    older = write(user / "Downloads/client_secret_old.json", {"installed": {}})
    newest = write(user / "Downloads/client_secret_new.json", CLIENT_JSON)
    import os

    os.utime(older, (1, 1))
    assert mod.main([]) == 0
    out = capsys.readouterr().out
    target = wx / "oauth_client.json"
    assert f"ok   oauth client: moved to {target}, project unknown, mode 600" in out
    assert not newest.exists() and older.exists()
    assert json.loads(target.read_text()) == CLIENT_JSON
    assert (wx.stat().st_mode & 0o777, target.stat().st_mode & 0o777) == (0o700, 0o600)
    for secret in SECRETS:
        assert secret not in out

    # Idempotent: with a good file in place, Downloads is not searched again
    # (the stale older download stays where it is); a path replaces it.
    assert mod.main([]) == 0
    assert "already installed" in capsys.readouterr().out
    assert older.exists()
    assert mod.main(["--check"]) == 0
    assert "ok   oauth client:" in capsys.readouterr().out


def test_install_refuses_wrong_shapes(
    homes: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    user, wx = homes
    mod = load("install_client_json")
    assert mod.main([]) == 1
    assert "no client_secret*.json" in capsys.readouterr().out
    web = write(user / "web.json", {"web": CLIENT_JSON["installed"]})
    assert mod.main([str(web)]) == 1
    assert "Web application client" in capsys.readouterr().out
    assert web.exists()
    partial = write(user / "partial.json", {"installed": {"client_id": "x"}})
    assert mod.main([str(partial)]) == 1
    assert "lacks client_secret, auth_uri, token_uri" in capsys.readouterr().out
    assert mod.main([str(user / "missing.json")]) == 1
    assert "is not a file" in capsys.readouterr().out
    assert mod.main(["--check"]) == 1
    assert "missing" in capsys.readouterr().out
    assert not wx.exists()


def test_install_keeps_the_previous_file(
    homes: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    user, wx = homes
    mod = load("install_client_json")
    first = write(user / "first.json", CLIENT_JSON)
    assert mod.main([str(first)]) == 0
    second_data = {"installed": {**CLIENT_JSON["installed"], "project_id": "p2"}}
    second = write(user / "second.json", second_data)
    assert mod.main([str(second)]) == 0
    out = capsys.readouterr().out
    assert "previous file kept as" in out
    assert "project p2" in out
    assert json.loads((wx / "oauth_client.json").read_text()) == second_data
    previous = wx / "oauth_client.json.previous"
    assert json.loads(previous.read_text()) == CLIENT_JSON
    assert previous.stat().st_mode & 0o777 == 0o600
    shutil.rmtree(wx)
