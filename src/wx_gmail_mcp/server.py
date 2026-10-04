"""Build the MCP server and register tool groups behind their gates.

Nothing registers at import time. ``build_server`` calls each tool
module's ``register(mcp, rt)`` only when that module's gate is on, so a
test can build a server for any gate combination.
"""

from __future__ import annotations

from collections.abc import Callable
from types import ModuleType

from mcp.server.mcpserver import MCPServer

from wx_gmail_mcp import __version__
from wx_gmail_mcp.config import Gates, Settings
from wx_gmail_mcp.gmail import Runtime
from wx_gmail_mcp.tools import accounts, drafts, labels, organize, read, send

SERVER_NAME = "wx-gmail-mcp"
INSTRUCTIONS = (
    "Multi-account Gmail. Every mailbox tool takes an account alias; call "
    "list_accounts first to see the aliases and what each has granted. "
    "Results are plain text."
)

GateCheck = Callable[[Gates], bool]

# (gate check, tool modules). Gated modules arrive with their phases.
TOOL_GROUPS: tuple[tuple[GateCheck, tuple[ModuleType, ...]], ...] = (
    (lambda _: True, (accounts, read, labels, organize, drafts)),
    (lambda g: g.sending, (send,)),
    (lambda g: g.settings, ()),
    (lambda g: g.delete, ()),
)


def build_server(rt: Runtime) -> MCPServer:
    mcp = MCPServer(SERVER_NAME, instructions=INSTRUCTIONS, version=__version__)
    for is_on, modules in TOOL_GROUPS:
        if not is_on(rt.settings.gates):
            continue
        for module in modules:
            module.register(mcp, rt)
    return mcp


def serve(settings: Settings) -> None:
    """Run the stdio server until the client closes stdin."""
    build_server(Runtime(settings)).run()
