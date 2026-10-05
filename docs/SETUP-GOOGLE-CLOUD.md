# Setting up wx-gmail-mcp

This page is the human-readable twin of the bundled agent skill
(`.agents/skills/setting-up-wx-gmail-mcp/`). If your agent harness
supports skills, you can say "set up wx-gmail-mcp" and let the agent
walk you through the same steps; otherwise follow them here. Every step
is safe to repeat.

You need: `uv` ([install](https://docs.astral.sh/uv/getting-started/)),
a Google account for each mailbox, and about fifteen minutes. `gcloud`
is optional. Steps marked **you** happen in your browser and cannot be
delegated: signing in, accepting Google's policy, consenting.

## 1. Install and check

```bash
uv tool install git+https://github.com/whitechno/wx-gmail-mcp
wx-gmail-mcp --doctor
```

The doctor prints one line per check. Expect `FAIL home` and
`FAIL oauth client` on a fresh machine; the next steps fix them. Run it
again after each step.

## 2. Choose your gates

Everything that reads, searches, labels, organizes or drafts is always
on. Three gates add more, each with exactly one extra OAuth scope:

| Gate | Env var | Tools | Scope |
|---|---|---|---|
| sending | `WX_GMAIL_ALLOW_SENDING=true` | send_message, send_draft, reply, forward | `gmail.send` |
| settings | `WX_GMAIL_ALLOW_SETTINGS=true` | filters, vacation responder, send-as and signature | `gmail.settings.basic` |
| delete | `WX_GMAIL_ALLOW_DELETE=true` | trash, untrash, delete_permanently | `https://mail.google.com/` (full) |

A gate must be on both when you authorize an account (it adds the scope)
and in the client registration (it registers the tools). You can
authorize different accounts with different gates: a primary mailbox
with none, a work account with settings, and so on. Start small; a
later `--auth` with more gates upgrades an account.

## 3. Google Cloud project, consent screen, client

Each installation gets its own project. Reusing another app's project
would share its consent screen and test-user list.

### 3a. Project and Gmail API

With gcloud:

```bash
gcloud auth login                       # you, once
gcloud projects create <project-id> --name=<project-id>
gcloud services enable gmail.googleapis.com --project=<project-id>
```

Project ids are global: use `wx-gmail-mcp` if it is free, else
`wx-gmail-mcp-<something>`, and use the same id everywhere below.
Without gcloud:
[create a project](https://console.cloud.google.com/projectcreate) in
the console, then open
`https://console.cloud.google.com/apis/library/gmail.googleapis.com?project=<project-id>`
and click **Enable**. No billing account is needed.

### 3b. Consent screen

Open `https://console.cloud.google.com/auth/overview?project=<project-id>`
and click **Get started**:

1. App name `WX Gmail MCP`; user support email: yours.
2. Audience: **External**.
3. Contact information: your email.
4. Agree to the Google API Services User Data Policy (**you**), then
   **Create**.

Then **Audience** (left menu) > **Test users** > **Add users**: every
Gmail address you will authorize. If the first **Save** only turns the
address into a chip, click it again. Leave the app in **Testing** for
now; **Data access** (scopes) stays empty, the server requests its
scopes when you authorize.

### 3c. Desktop client

**Clients** > **Create client**:

- Application type **Desktop app**, name `wx-gmail-mcp-desktop`.
- Tick **"This client will be used by an AI-powered agent"**. The
  console's help text says it "designates this client for AI agents
  that take actions on behalf of users", which is what an MCP server
  does. It is a declaration to Google, not a switch: in a side-by-side
  test on 2026-10-05 the consent screens and granted scopes were the
  same with and without it, and Google's public OAuth docs do not
  describe it. A client created without it works too.
- **Create**, then **Download JSON** in the confirmation dialog. The
  file is called `client_secret_<id>.json`; note where the browser put
  it (Chrome may use a subfolder of Downloads). You can download it
  again later from the client's row.

### 3d. Put the client JSON in place

```bash
mkdir -p ~/.wx-gmail-mcp && chmod 700 ~/.wx-gmail-mcp
mv ~/Downloads/client_secret_<id>.json ~/.wx-gmail-mcp/oauth_client.json
chmod 600 ~/.wx-gmail-mcp/oauth_client.json
wx-gmail-mcp --doctor
```

Or let the skill's script do it, which also checks that the file is a
Desktop app client: `python3
.agents/skills/setting-up-wx-gmail-mcp/scripts/install_client_json.py
~/Downloads/client_secret_<id>.json` (from a clone of the repo).

(`WX_GMAIL_MCP_HOME` moves the whole directory elsewhere; set it for
every command and in the registration.) The doctor's `oauth client`
line should now read `Desktop app client, project <project-id>, mode
600`. The file holds your client id and secret: keep it there, never in
a repository.

## 4. Authorize each account

In a terminal, with the gates you chose for this account:

```bash
WX_GMAIL_ALLOW_SETTINGS=true wx-gmail-mcp --auth work --email you@example.com
wx-gmail-mcp --auth personal --email other@example.com      # base scopes only
wx-gmail-mcp --list
```

A browser opens (**you**): pick the account, pass the "Google hasn't
verified this app" screen (**Continue** while the app is in Testing;
**Advanced** > **Go to WX Gmail MCP** once it is published), tick every
scope, **Allow**. The command confirms the address Gmail
reports and the scopes granted; tokens land in
`~/.wx-gmail-mcp/tokens/<alias>.json` with mode 600. Aliases use
letters, digits, `-` and `_`.

While the app is in Testing, Google expires refresh tokens after 7
days; `--list` or any tool then says `needs re-auth` with the exact
command to run. To stop that, publish the app: **Audience** > **Publish
app**. The unverified-app warning stays, which is fine for personal use.

## 5. Register with your agent

```bash
WX_GMAIL_ALLOW_SETTINGS=true wx-gmail-mcp --print-config claude-code
```

Clients: `claude-code`, `claude-desktop`, `codex`, `antigravity`,
`cursor`. The block carries the absolute path of the executable and the
gates in your environment; the line on stderr says where it goes.
[docs/CLIENTS.md](CLIENTS.md) has each client's steps, sources and the
compatibility matrix. Use the same gates as in step 4.

## 6. Verify

Ask the agent to call `list_accounts` (every alias with its scopes; a
warning on an account that lacks a gate's scope is expected), then a
read-only `search` such as `newer_than:7d` on one alias. Finish with
`wx-gmail-mcp --doctor`, which now lists the registration it found.

## Adding an account or a gate later

Add the address as a test user (while in Testing), run `--auth` for the
new alias, and, for a new gate, run `--auth` again for each account that
should have it and update the registration's env. Then restart the
client.

## Removing

`remove_account` (a tool, with `revoke=true` to also revoke the grant at
Google) or delete `~/.wx-gmail-mcp/tokens/<alias>.json` and the alias in
`accounts.json`. Grants can also be revoked at
https://myaccount.google.com/permissions. Deleting the Google Cloud
project revokes every token at once.

## If something fails

The skill's `references/troubleshooting.md` lists the known cases:
unverified-app and access-blocked screens, the 7-day expiry, Workspace
admin blocks, insufficient-scope errors, Codex's startup timeout and
Claude Code's cached tool list.
