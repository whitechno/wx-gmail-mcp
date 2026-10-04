"""Guardrails shared by every tool: error wrapper, caps, path allowlist."""

from __future__ import annotations

import functools
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from googleapiclient.errors import HttpError
from mcp.server.mcpserver import MCPServer

from wx_gmail_mcp.accounts import FILE_MODE, ensure_private_dir
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
            return f"Gmail API error: {describe_http_error(e)}"
        except WxGmailError as e:
            return f"Error: {e}"
        except Exception as e:  # the model needs a message, not a trace
            return f"Error: {type(e).__name__}: {e}"

    return wrapper


def describe_http_error(e: HttpError) -> str:
    """``HTTP 404: Requested entity was not found.``

    ``str(e)`` also carries the request URL and the raw error details,
    which only cost context without helping the model.
    """
    status = getattr(e.resp, "status", "") or ""
    reason = (e.reason or "").strip() or "request failed"
    return f"HTTP {status}: {reason}"


def describe_error(e: Exception) -> str:
    """Readable text for any failure: HTTP errors by status and message,
    everything else by type and message."""
    if isinstance(e, HttpError):
        return describe_http_error(e)
    return f"{type(e).__name__}: {e}"


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


def write_download(
    settings: Settings, name: str, data: bytes, overwrite: bool = False
) -> Path:
    """Write ``data`` to ``name`` inside ``downloads/`` with mode 600.

    Every directory from ``downloads/`` down is created with mode 700. An
    existing file is an error unless ``overwrite`` is set.
    """
    path = download_path(settings, name)
    directory = settings.downloads_dir.resolve()
    ensure_private_dir(directory)
    for part in path.parent.relative_to(directory).parts:
        directory = directory / part
        ensure_private_dir(directory)
    flags = os.O_WRONLY | os.O_CREAT | (os.O_TRUNC if overwrite else os.O_EXCL)
    try:
        fd = os.open(path, flags, FILE_MODE)
    except FileExistsError:
        raise WxGmailError(
            f"'{name}' already exists in {settings.downloads_dir}. Pass "
            "overwrite=true or another filename."
        ) from None
    except IsADirectoryError:
        raise WxGmailError(
            f"'{name}' is a directory in {settings.downloads_dir}."
        ) from None
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return path


def outbox_path(settings: Settings, name: str) -> Path:
    """A readable attachment inside ``~/.wx-gmail-mcp/outbox/``."""
    path = _resolve_inside(settings.outbox_dir, name, "attachment path")
    if not path.is_file():
        raise WxGmailError(
            f"attachment path: '{name}' is not a file in {settings.outbox_dir}."
        )
    return path
