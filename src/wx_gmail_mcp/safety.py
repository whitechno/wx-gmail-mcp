"""Guardrails shared by every tool: error wrapper, caps, path allowlist."""

from __future__ import annotations

import functools
from collections.abc import Callable
from pathlib import Path
from typing import Any

from googleapiclient.errors import HttpError
from mcp.server.mcpserver import MCPServer

from wx_gmail_mcp.config import Settings
from wx_gmail_mcp.errors import WxGmailError

ToolFn = Callable[..., str]


def safe(fn: ToolFn) -> ToolFn:
    """Turn errors into readable text; keep the tool's parameter schema.

    The MCP SDK hides the text of unexpected exceptions from the client, so
    a tool that raised would tell the model nothing useful.
    """

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> str:
        try:
            return fn(*args, **kwargs)
        except HttpError as e:
            return f"Gmail API error: {e}"
        except WxGmailError as e:
            return f"Error: {e}"
        except Exception as e:  # the model needs a message, not a trace
            return f"Error: {type(e).__name__}: {e}"

    return wrapper


def register_tool(mcp: MCPServer, fn: ToolFn) -> None:
    """Register ``fn`` wrapped in ``safe`` as a plain-text tool."""
    mcp.add_tool(safe(fn), structured_output=False)


def require_ids(
    ids: list[str], what: str = "message_ids", cap: int = 1000
) -> list[str]:
    """Reject empty id lists, blanks and lists above ``cap``."""
    cleaned = [i.strip() for i in ids if i and i.strip()]
    if not cleaned:
        raise WxGmailError(f"{what} must contain at least one id.")
    if len(cleaned) > cap:
        raise WxGmailError(f"{what} holds {len(cleaned)} ids; the cap is {cap}.")
    return cleaned


def _resolve_inside(base: Path, name: str, what: str) -> Path:
    if not name or not name.strip():
        raise WxGmailError(f"{what}: a file name is required.")
    candidate = Path(name)
    if candidate.is_absolute():
        raise WxGmailError(f"{what}: give a name relative to {base}, not a full path.")
    resolved = (base / candidate).resolve()
    base_resolved = base.resolve()
    if resolved != base_resolved and base_resolved not in resolved.parents:
        raise WxGmailError(f"{what}: '{name}' escapes {base}.")
    if resolved == base_resolved:
        raise WxGmailError(f"{what}: '{name}' is the directory itself.")
    return resolved


def download_path(settings: Settings, name: str) -> Path:
    """A write target inside ``~/.wx-gmail-mcp/downloads/``."""
    return _resolve_inside(settings.downloads_dir, name, "download path")


def outbox_path(settings: Settings, name: str) -> Path:
    """A readable attachment inside ``~/.wx-gmail-mcp/outbox/``."""
    path = _resolve_inside(settings.outbox_dir, name, "attachment path")
    if not path.is_file():
        raise WxGmailError(
            f"attachment path: '{name}' is not a file in {settings.outbox_dir}."
        )
    return path
