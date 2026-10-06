# Registering wx-gmail-mcp with an MCP client

wx-gmail-mcp is a plain MCP server over stdio, so any MCP client can run
it. This page shows the registration for the clients the project tests,
checked against each client's own documentation on the date in the
[compatibility matrix](#compatibility-matrix). Those docs change often;
when a snippet here and the client's page disagree, the client's page
wins.

## Before you register

1. Install the server and authorize each account **in a terminal**, not
   from inside a client. OAuth opens a browser on a loopback port, which
   a client's sandbox may block:

   ```bash
   uv tool install git+https://github.com/whitechno/wx-gmail-mcp
   WX_GMAIL_ALLOW_SETTINGS=true wx-gmail-mcp --auth work --email you@example.com
   wx-gmail-mcp --list
   ```

   Set the same `WX_GMAIL_ALLOW_*` gates at `--auth` time as in the
   registration: a gate adds its OAuth scope when you authorize and
   registers its tools when the server starts. An account authorized
   without a gate refuses that gate's tools with a message naming the
   re-auth command.

2. Print the registration block for your client with the gates you
   want. The block carries the absolute path of the executable you ran,
   the gates on in your environment and `WX_GMAIL_MCP_HOME` if set:

   ```bash
   WX_GMAIL_ALLOW_SETTINGS=true wx-gmail-mcp --print-config codex
   ```

   Clients: `claude-code`, `claude-desktop`, `codex`, `antigravity`,
   `cursor`. The block goes to stdout; one line on stderr says where to
   paste it. Nothing secret is read or printed.

   `uvx wx-gmail-mcp --print-config ...` works too, but the path it
   prints lies in uv's cache, which a prune can remove; the command
   warns about that. `uv tool install` gives a stable path.

3. After registering, `wx-gmail-mcp --doctor` lists the registrations
   it found in each client's config file next to the token and scope
   checks. Then ask the agent to call `list_accounts` and a read-only
   `search`. Both need no gate.

The examples below show the executable as `~/.local/bin/wx-gmail-mcp`
(where `uv tool install` puts it) or `/path/to/wx-gmail-mcp`;
`--print-config` prints the real, absolute path.

## Claude Code

Registration is a command; `--scope user` makes the server available in
every project (`local`, the default, is this project only, and
`project` writes a shared `.mcp.json`). Per the Claude Code MCP docs,
`--transport stdio` sits between the last `--env` and the server name,
and everything after `--` is the server command.

```bash
claude mcp add --scope user \
  --env WX_GMAIL_ALLOW_SETTINGS=true \
  --transport stdio wx-gmail-mcp -- ~/.local/bin/wx-gmail-mcp
```

Check with `claude mcp list` (the server should show as connected) or
`/mcp` inside a session. Remove with `claude mcp remove wx-gmail-mcp
-s user`.

Source: [Connect Claude Code to tools via MCP](https://code.claude.com/docs/en/mcp).

## Claude Desktop

Claude Desktop reads `mcpServers` from a JSON file: on macOS
`~/Library/Application Support/Claude/claude_desktop_config.json`, on
Windows `%APPDATA%\Claude\claude_desktop_config.json` (Settings >
Developer > Edit Config opens it). Paths must be absolute. Restart the
app after saving.

```json
{
  "mcpServers": {
    "wx-gmail-mcp": {
      "command": "/path/to/wx-gmail-mcp",
      "args": [],
      "env": {
        "WX_GMAIL_ALLOW_SETTINGS": "true"
      }
    }
  }
}
```

Logs: `~/Library/Logs/Claude/mcp-server-wx-gmail-mcp.log` (macOS) or
`%APPDATA%\Claude\logs\mcp-server-wx-gmail-mcp.log` (Windows) holds
the server's stderr.

Source: [Connect to local MCP servers](https://modelcontextprotocol.io/docs/develop/connect-local-servers)
(Claude Desktop is the example client).

## Codex CLI

Either the command or the TOML. `codex mcp add` writes the same table
into `~/.codex/config.toml`:

```bash
codex mcp add wx-gmail-mcp --env WX_GMAIL_ALLOW_SETTINGS=true \
  -- ~/.local/bin/wx-gmail-mcp
```

```toml
[mcp_servers.wx-gmail-mcp]
command = "/path/to/wx-gmail-mcp"
args = []
startup_timeout_sec = 30

[mcp_servers.wx-gmail-mcp.env]
WX_GMAIL_ALLOW_SETTINGS = "true"
```

`startup_timeout_sec` matters: Codex allows 10 s by default, and a
Python server with the Google client libraries takes a few seconds to
start, more on a busy machine. In the live runs one session found no
tools at all until the timeout was raised; `--print-config codex`
includes the line. `codex mcp list` shows the configured servers, and
`enabled_tools` / `disabled_tools` in the same table filter the tool
list if you want fewer than the gates give.

Source: [Model Context Protocol (Codex)](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).

## Antigravity (agy CLI and IDE)

The CLI, the IDE and the SDK share one global file,
`~/.gemini/config/mcp_config.json`; a workspace can add
`.agents/mcp_config.json`. Flags go before the name:

```bash
agy mcp add -e WX_GMAIL_ALLOW_SETTINGS=true wx-gmail-mcp \
  -- ~/.local/bin/wx-gmail-mcp
```

```json
{
  "mcpServers": {
    "wx-gmail-mcp": {
      "command": "/path/to/wx-gmail-mcp",
      "args": [],
      "env": {
        "WX_GMAIL_ALLOW_SETTINGS": "true"
      }
    }
  }
}
```

`agy mcp list` shows type and status; `agy mcp disable <name>` keeps
the entry but turns it off (`"disabled": true` in the file).

Source: [MCP in Antigravity](https://antigravity.google/docs/mcp).

## Cursor

Global: `~/.cursor/mcp.json`; project: `.cursor/mcp.json`. Cursor's
docs list `type` as required for stdio servers.

```json
{
  "mcpServers": {
    "wx-gmail-mcp": {
      "type": "stdio",
      "command": "/path/to/wx-gmail-mcp",
      "args": [],
      "env": {
        "WX_GMAIL_ALLOW_SETTINGS": "true"
      }
    }
  }
}
```

Source: [Model Context Protocol (Cursor)](https://cursor.com/docs/context/mcp).

## Other clients

Any client that takes a `command` plus `env` for a stdio server works
the same way; the JSON blocks above are the usual `mcpServers` shape.
The server adds nothing client-specific: tool names match
`^[a-z][a-z0-9_]{0,40}$`, schemas are flat (simple types, defaults
instead of unions, no nested objects or `$ref`) and results are plain
text, so a client that strips richer JSON Schema still gets every tool.

## Compatibility matrix

Each tested client ran a scripted pass against a real mailbox, with
every gate on, built from the same steps: `list_accounts`,
`get_profile`, `list_labels`, `search`, label create and relabel,
`modify_by_query` dry run, draft create and delete, `create_filter`
(dry run, then real with `apply`), `list_filters`, `delete_filter`,
`delete_label` for the test labels, `get_vacation`, signature set and
cleared, `list_send_as`, and one settings-gate refusal on an account
authorized with the base scopes only. Driven non-interactively where
the client allows it; in Claude Desktop the prompts were typed by hand
and the effects checked from another client. Every pass ended with the
mailbox back at system labels only, no filters and no drafts.

| Client | Version | Tested | Tools accepted | Schema | Names | Results | Notes |
|---|---|---|---|---|---|---|---|
| Claude Code | 2.1.289 | 2026-10-05 | 41 of 41 | no complaints | fine | verbatim | Local-scope registration. Claude Code starts the server once per process and keeps it across `/clear`, so a long-running process kept an older 27-tool list after the server gained tools; restart Claude Code after upgrading the server. |
| Claude Desktop | 2.19675.0 | 2026-10-05 | 41 of 41 | no complaints | fine | verbatim | `claude_desktop_config.json` entry with absolute paths; the app starts one server process per window and listed the tools within two seconds of a restart. Each tool call asks for approval in the chat. |
| Codex CLI | 0.160.0, 0.160.1 | 2026-10-05 | 41 of 41 | no complaints | fine | verbatim | `codex exec`. With the default 10 s `startup_timeout_sec` one run saw no tools; 30 s fixed it. On a machine at load average 500 and above, two runs found no tools whatever the timeout (the server itself took two minutes to start); the same script passed once the machine was quiet. Codex loads MCP tool metadata through its own discovery step, whose first listing of 41 tools was truncated on its side; the calls were unaffected. No approval prompts in `exec` mode. |
| Antigravity CLI | 1.2.14, 1.2.17 | 2026-10-05 | 41 of 41 | no complaints | fine | verbatim | `agy --print`, optionally `--output-format json`. No permission prompts for MCP tools in print mode. |
| Cursor | - | not run | - | - | - | - | - |

"Tools accepted" is the number the client listed out of the 41 the
server registers with all three gates on (25 with none). No client
needed a tool allowlist; gates are the first answer to a client that
caps tools, and `enabled_tools` / `disabled_tools` (Codex) are the
client-side answer.
