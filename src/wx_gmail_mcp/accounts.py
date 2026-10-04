"""The alias -> email map (``accounts.json``) and alias validation."""

from __future__ import annotations

import json
import re
import stat
from pathlib import Path

from wx_gmail_mcp.config import Settings
from wx_gmail_mcp.errors import WxGmailError

# Aliases become token file names, so the charset is restricted: no dots,
# slashes or spaces, which blocks path traversal.
ALIAS_RE = re.compile(r"^[A-Za-z0-9_-]+$")

DIR_MODE = stat.S_IRWXU  # 700
FILE_MODE = stat.S_IRUSR | stat.S_IWUSR  # 600


def check_alias(alias: str) -> str:
    """Return ``alias`` if it is safe, else raise a readable error."""
    if not ALIAS_RE.fullmatch(alias):
        raise WxGmailError(
            f"Invalid alias '{alias}'. Use only letters, digits, hyphen and "
            "underscore (no dots, slashes or spaces)."
        )
    return alias


def ensure_private_dir(path: Path) -> None:
    """Create ``path`` (and parents) and force mode 700 on it."""
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(DIR_MODE)


def write_private(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` with mode 600, creating the directory."""
    ensure_private_dir(path.parent)
    path.write_text(text)
    path.chmod(FILE_MODE)


def load_accounts(settings: Settings) -> dict[str, str]:
    path = settings.accounts_file
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise WxGmailError(f"{path} must hold a JSON object of alias -> email.")
    return {str(k): str(v) for k, v in data.items()}


def save_accounts(settings: Settings, accounts: dict[str, str]) -> None:
    write_private(settings.accounts_file, json.dumps(accounts, indent=2) + "\n")


def known_aliases(settings: Settings) -> str:
    accounts = load_accounts(settings)
    return ", ".join(accounts) if accounts else "(none)"


def token_path(settings: Settings, alias: str) -> Path:
    return settings.tokens_dir / f"{check_alias(alias)}.json"


def set_account(settings: Settings, alias: str, email: str) -> None:
    accounts = load_accounts(settings)
    accounts[check_alias(alias)] = email
    save_accounts(settings, accounts)


def delete_account(settings: Settings, alias: str) -> bool:
    """Remove the alias and its token file. Returns False if unknown."""
    accounts = load_accounts(settings)
    if alias not in accounts:
        return False
    token_path(settings, alias).unlink(missing_ok=True)
    del accounts[alias]
    save_accounts(settings, accounts)
    return True
