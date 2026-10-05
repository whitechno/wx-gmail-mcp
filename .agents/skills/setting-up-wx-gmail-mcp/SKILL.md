---
name: setting-up-wx-gmail-mcp
description: Set up wx-gmail-mcp, a self-hosted multi-account Gmail MCP server, from nothing to a verified registration - prerequisites, Google Cloud project, OAuth consent screen and Desktop client, client JSON, account authorization, MCP client registration, verification. Use when the user asks to install, set up, configure, add a Gmail account to, or troubleshoot wx-gmail-mcp. Idempotent and resumable at every step; works with or without gcloud and with or without a browser tool.
---

# Setting up wx-gmail-mcp

Walk the user through the seven steps below, in order, skipping any that
is already done. Check before you act: every step starts with a
read-only probe, so the skill can resume after a break. Steps marked
**[you]** need the user in a browser or terminal: say what to do, stop,
and continue when they confirm. Never read a token or the client JSON
aloud, and never paste either into a chat or a file in a repo.

Paths: `<home>` is `$WX_GMAIL_MCP_HOME` if set, else `~/.wx-gmail-mcp/`.
Scripts are in this skill's `scripts/`; run them with `python3`.

## 1. Doctor

- If `wx-gmail-mcp` is installed: `wx-gmail-mcp --doctor` (with the gates
  from step 2 in the environment, once chosen). One line per check; `FAIL`
  lines say what to fix. With no `FAIL` or `warn` line, resume at the
  first step still open: step 6 if every `client` line says
  `not registered`, else step 7. To **add an account** to a working
  install: add it as a test user (step 3.2, while in Testing), then
  step 5 for it. To **add a gate**: step 5 again for each account that
  gets it, then step 6 with the new env.
- If not: `python3 scripts/prereqs.py`, then install:
  `uv tool install git+https://github.com/whitechno/wx-gmail-mcp`
  (needs `uv`; stop and ask before installing `uv` or anything else).
  Re-run the doctor afterwards.

## 2. Choose gates

Ask which of these the user wants, and keep the answer for steps 5
and 6. Each gate adds one OAuth scope at `--auth` time and registers its
tools when the server starts; off by default.

| Gate | Env var | Adds |
|---|---|---|
| none | - | read, search, labels, organize, drafts (always on) |
| sending | `WX_GMAIL_ALLOW_SENDING=true` | send, reply, forward, send_draft |
| settings | `WX_GMAIL_ALLOW_SETTINGS=true` | filters, vacation responder, signatures |
| delete | `WX_GMAIL_ALLOW_DELETE=true` | trash, untrash, delete_permanently (full mail scope) |

Recommend starting without gates for a primary mailbox; a gate can be
added later with one more `--auth`.

## 3. Google Cloud

Skip if the doctor's `oauth client` line is `ok`. Otherwise, each user
needs their own project (one consent screen per project):

1. **Project and Gmail API.** With gcloud (doctor says `gcloud login: ok`):
   `python3 scripts/gcloud_project.py <project-id> --create --enable`.
   Project ids are global; if `wx-gmail-mcp` is taken, add a suffix.
   Without gcloud: `python3 scripts/gcloud_project.py <project-id> --urls`
   prints the console pages; the user creates the project at
   https://console.cloud.google.com/projectcreate and enables the Gmail
   API from the "Gmail API" URL. See `references/gcloud.md`.
2. **Consent screen** (console only; drive the browser tool if you have
   one, otherwise give the URLs and values from `references/gcloud.md`):
   External, app name `WX Gmail MCP`, the user's email as support and
   developer contact, no scopes, and every account to be authorized
   added as a test user. **[you]** sign-in, the policy acceptance on the
   wizard's last step, and any 2FA prompt.
3. **Desktop client** (console only): Clients > Create client, type
   Desktop app, name `wx-gmail-mcp-desktop`, tick "used by an
   AI-powered agent" (`references/gcloud.md` says why), create. **[you]**
   **Download JSON** on the confirmation dialog, and say where the
   browser saved it.

The app stays in **Testing**: tokens expire after 7 days and need a
re-auth (step 5). Publishing removes that; see `references/gcloud.md`.

## 4. Client JSON

`python3 scripts/install_client_json.py <downloaded file>` moves it to
`<home>/oauth_client.json` with modes 700/600 after checking it is a
Desktop app client. Without a path it takes the newest
`client_secret*.json` in `~/Downloads`, but browsers often save into a
subfolder, so prefer the path. Verify with `wx-gmail-mcp --doctor`.

## 5. Authorize

In a terminal, with the user present, one account at a time, with the
step 2 gates in the environment (none for a base-scope account):

```bash
WX_GMAIL_ALLOW_SETTINGS=true wx-gmail-mcp --auth <alias> --email you@example.com
```

**[you]** sign in, pass the "Google hasn't verified this app" screen
(Continue in Testing status), tick every scope, allow. The command
prints the address it confirmed and the scopes granted; `wx-gmail-mcp
--list` shows every account. It needs a terminal where a browser can
open (an MCP client's sandbox may block the loopback flow); if no
browser opens, it prints the URL to visit. Aliases: letters, digits,
`-`, `_`.

## 6. Register

`WX_GMAIL_ALLOW_...=true wx-gmail-mcp --print-config <client>` prints a
ready-to-paste block for `claude-code`, `claude-desktop`, `codex`,
`antigravity` or `cursor`, with the executable's absolute path and the
gates from the environment; one line on stderr says where it goes. The
same gates as at `--auth`. `references/clients.md` has the `mcp add`
commands and restart notes; a client that keeps a running server (Claude
Code) needs a restart to see new tools.

## 7. Verify

Through the registered client: `list_accounts` (every alias with its
scopes; a gate warning is expected on a base-scope account), then a
read-only `search` such as `newer_than:7d` on one alias. Then
`wx-gmail-mcp --doctor` once more: it lists the registration it found.
If anything fails, `references/troubleshooting.md`.
