# wx-gmail-mcp

**wx-gmail-mcp** is a self-hosted MCP server that gives your AI agent
(Claude Code, Codex, Antigravity, Cursor, any MCP client) full,
controlled access to *several* Gmail accounts at once.

- **Multiple accounts, one server.** Every tool takes an account alias,
  so personal, work and project inboxes are all available in one
  session. Hosted connectors authorize a single Google account.
- **Filters, not just mail.** List, create, replace and delete Gmail
  filters, and optionally apply a new filter to existing mail (dry run
  first).
- **Bulk operations with previews.** Relabel, archive or mark read by
  id list, or by query with a dry run as the default.
- **You choose the power level.** Env gates switch sending, settings
  and trash/delete on or off; each gate requests only the OAuth scope
  it needs.
- **Full control, nothing in between.** Your own Google Cloud OAuth
  client, tokens on your machine (mode 600), no third-party service in
  the path to your inbox.
- **Works with any agent.** Plain MCP over stdio, portable tool
  schemas, and copy-paste config for each major harness.
- **Guided setup.** A bundled agent skill walks you through Google
  Cloud, authorization and client registration.
- **Safety rails.** Permanent delete takes explicit ids, is capped and
  audited; mailbox forwarding is deliberately not exposed; file access
  is limited to allowlisted folders.
- **Small, typed, tested, auditable.** Modular Python, unit tests
  against a fake Gmail API, CI with secret scanning and code scanning.

**When a hosted connector is the better choice:** one account, no wish
to create a Google Cloud project, and no need for filters or bulk
operations.

**Status:** pre-release. The first tagged release will be `v0.1.0`; see
[CHANGELOG.md](CHANGELOG.md).

## Quick start

You need Python 3.14 or newer, [uv](https://docs.astral.sh/uv/) and a
Google account per mailbox. Setup takes about fifteen minutes, most of
it in the Google Cloud console.

**With an agent.** Clone the repo and tell your agent to "set up
wx-gmail-mcp". The skill in
[`.agents/skills/setting-up-wx-gmail-mcp/`](.agents/skills/setting-up-wx-gmail-mcp/SKILL.md)
checks prerequisites, creates the Google Cloud project (with `gcloud`
where present), guides the console steps, installs the client JSON,
runs the authorization and prints the registration for your client.
Signing in and consenting stay with you.

**By hand.**

1. Install and check:

   ```bash
   uv tool install git+https://github.com/whitechno/wx-gmail-mcp
   wx-gmail-mcp --doctor
   ```

2. Create a Google Cloud project with the Gmail API, an external OAuth
   consent screen in Testing with your addresses as test users, and a
   **Desktop app** OAuth client; save its JSON as
   `~/.wx-gmail-mcp/oauth_client.json` (mode 600). Step by step in
   [docs/SETUP-GOOGLE-CLOUD.md](docs/SETUP-GOOGLE-CLOUD.md).

3. Authorize each account in a terminal, with the gates you want for
   it (none here):

   ```bash
   wx-gmail-mcp --auth work --email you@example.com
   wx-gmail-mcp --list
   ```

4. Register with your client and verify:

   ```bash
   wx-gmail-mcp --print-config claude-code     # or claude-desktop, codex, antigravity, cursor
   ```

   Paste the block where the command says, restart the client, then
   ask the agent for `list_accounts` and a read-only `search`. Per-client
   steps and the compatibility matrix are in
   [docs/CLIENTS.md](docs/CLIENTS.md).

## Gates

Reading, searching, labels, organizing and drafts are always on. Three
gates add more, each with exactly one extra OAuth scope. A gate must be
on when you authorize an account (it adds the scope) and in the client
registration (it registers the tools); accounts can differ.

| Env var | Adds | Scope |
|---|---|---|
| `WX_GMAIL_ALLOW_SENDING=true` | `send_message`, `send_draft`, `reply`, `forward` | `gmail.send` |
| `WX_GMAIL_ALLOW_SETTINGS=true` | filters, vacation responder, send-as and signature | `gmail.settings.basic` |
| `WX_GMAIL_ALLOW_DELETE=true` | `trash`, `untrash`, `delete_permanently`, filter action "delete" | `https://mail.google.com/` |

Only the value `true` (any case) turns a gate on. Tools of a gate refuse an
account that has not granted the gate's scope and name the re-auth
command.

## Tools

25 tools with no gate, 41 with all three. Every mailbox tool takes an
`account` alias; results are plain text. The Gate column names the
gate from the table above that registers the group. Parameters,
defaults, worked examples and known behaviors per tool are in
[docs/TOOLS.md](docs/TOOLS.md).

| Group | Tools | Gate |
|---|---|---|
| Accounts | `list_accounts`, `add_account`, `remove_account`, `get_profile` | - |
| Read and search | `search`, `search_threads`, `read_message`, `read_thread`, `list_attachments`, `download_attachment` | - |
| Labels | `list_labels`, `create_label`, `update_label`, `delete_label` | - |
| Organize | `modify_labels`, `mark_read`, `mark_unread`, `archive`, `modify_thread_labels`, `modify_by_query` (dry run by default) | - |
| Drafts | `create_draft`, `list_drafts`, `get_draft`, `update_draft`, `delete_draft` | - |
| Send | `send_message`, `send_draft`, `reply`, `forward` | sending |
| Filters | `list_filters`, `get_filter`, `create_filter` (optional apply to existing mail, dry run), `delete_filter`, `replace_filter` | settings |
| Settings | `get_vacation`, `set_vacation`, `list_send_as`, `set_signature` | settings |
| Trash and delete | `trash`, `untrash`, `delete_permanently` (explicit ids, capped at 100, Trash only by default, dry run by default, audit trail) | delete |

Deliberately absent: forwarding addresses and auto-forwarding (they need
the sharing scope, which the server never requests), empty-trash and
query-based permanent delete, Pub/Sub watch, IMAP/POP settings.

## Security notes

- The client JSON and the tokens live under `~/.wx-gmail-mcp/`
  (`WX_GMAIL_MCP_HOME` to move it) with modes 700 and 600, and never
  leave the machine. `wx-gmail-mcp --doctor` checks the modes and the
  scopes each account granted against the gates that are on.
- Gates and guardrails are enforced in the server, not by a client's
  approval prompts.
- Two always-on tools act for good because they need only the base
  scope: `delete_label` removes a label from every message (no mail is
  deleted) and `delete_draft` removes unsent drafts.
- File access is limited to `~/.wx-gmail-mcp/downloads/` (attachment
  downloads) and `~/.wx-gmail-mcp/outbox/` (files to attach).
- While the consent screen is in Testing, Google expires refresh tokens
  after 7 days; publishing the app (still unverified) stops that. See
  [SECURITY.md](SECURITY.md) for reporting.

## Development

```bash
uv sync --all-groups
uv run pytest
uv run ruff check . && uv run ruff format --check . && uv run pyright
uv run wx-gmail-mcp --version
```

[CONTRIBUTING.md](CONTRIBUTING.md) has the PR flow and
[AGENTS.md](AGENTS.md) the conventions every contributor and agent
follows.

## License

[MIT](LICENSE).
