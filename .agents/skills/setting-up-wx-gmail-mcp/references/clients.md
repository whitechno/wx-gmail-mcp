# Registering the server with an MCP client

`wx-gmail-mcp --print-config <client>` prints the block for one client
with the absolute path of the executable that ran, the gates on in the
environment and `WX_GMAIL_MCP_HOME` if set; stderr says where to paste
it. The full page with sources is `docs/CLIENTS.md` in the repo
(https://github.com/whitechno/wx-gmail-mcp/blob/main/docs/CLIENTS.md).

Set the same gates as at `--auth`. A gate on in the registration but
not granted by an account makes that gate's tools refuse the account
with the re-auth command; `list_accounts` and `--doctor` warn about it.

| Client | Register | Where it lands | Verify / remove |
|---|---|---|---|
| Claude Code | run the printed `claude mcp add --scope user ...` command | `~/.claude.json` (`--scope local` is per project, `project` writes `.mcp.json`) | `claude mcp list`, `/mcp`; `claude mcp remove wx-gmail-mcp -s user` |
| Claude Desktop | merge the JSON into `claude_desktop_config.json`, restart the app | macOS `~/Library/Application Support/Claude/`, Windows `%APPDATA%\Claude\` | Settings > Developer; logs in `~/Library/Logs/Claude/mcp-server-wx-gmail-mcp.log` |
| Codex CLI | `codex mcp add wx-gmail-mcp --env K=V -- <path>` or append the TOML | `~/.codex/config.toml` `[mcp_servers.wx-gmail-mcp]` | `codex mcp list`; `codex mcp remove wx-gmail-mcp` |
| Antigravity (agy CLI, IDE) | `agy mcp add -e K=V wx-gmail-mcp -- <path>` or merge the JSON | `~/.gemini/config/mcp_config.json` (global) or `.agents/mcp_config.json` | `agy mcp list`; `agy mcp remove wx-gmail-mcp` |
| Cursor | merge the JSON (`"type": "stdio"`) | `~/.cursor/mcp.json` or `.cursor/mcp.json` | Settings > MCP |
| other | any stdio `command` + `env` block | the client's `mcpServers` | the client's MCP list |

Notes that matter in practice:

- **Codex** allows 10 s for a server to start by default; the printed
  TOML carries `startup_timeout_sec = 30`. Keep it: without it Codex
  may report the tools as unavailable. On a heavily loaded machine even
  30 s was once too short; raise it rather than retry. `codex mcp add`
  does not set it (add the line by hand) and rewrites the whole
  `config.toml` when it saves, normalizing other tables' values (an
  existing `30` came back as `30.0`, harmless). Codex 0.160 loads MCP
  tools through its own discovery step: if it answers that the server's
  tools "aren't exposed", ask it in the prompt to discover the server's
  tools first.
- **Claude Code** starts the server once per process and keeps it
  across `/clear`. After installing, upgrading or changing gates,
  restart Claude Code (or `claude mcp remove` and add again) before
  expecting a new tool list.
- **Executable path.** `uv tool install` gives a stable path
  (`~/.local/bin/wx-gmail-mcp`). `uvx` works but its path lies in uv's
  cache, which a prune can remove; `--print-config` warns about that.
- **Tool count.** 25 tools with no gate, 41 with all three. No tested
  client needed fewer; Codex can filter with `enabled_tools` /
  `disabled_tools` in the same table.
- `wx-gmail-mcp --doctor` reads each client's config file and lists the
  registration it finds, with a warning when the command path does not
  exist or the home differs from the one it checked.
