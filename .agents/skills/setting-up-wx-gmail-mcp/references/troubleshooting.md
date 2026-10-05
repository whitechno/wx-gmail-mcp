# Troubleshooting

Start with `wx-gmail-mcp --doctor` (same gates as the registration);
every `FAIL` line names its fix. Then the cases below.

## Authorizing

- **"Google hasn't verified this app"** on the consent screen: expected
  for a personal project. Click Advanced, then "Go to WX Gmail MCP
  (unsafe)". Nothing is unsafe about it: the user owns the app.
- **"Access blocked: WX Gmail MCP has not completed the Google
  verification process" / error 403 access_denied**: the account is not
  a test user and the app is in Testing. Add it under Audience > Test
  users, or publish the app (`references/gcloud.md`).
- **"Access blocked: This app is blocked" / admin policy**: a Workspace
  account whose administrator blocks unverified third-party apps. The
  admin must allow the OAuth client id (Admin console > Security > API
  controls > App access control), or use a personal account.
- **"The OAuth client was not found" / invalid_client / error 401**: the
  client JSON belongs to a deleted client or project, or it is a Web
  application client. Download the Desktop client's JSON again and run
  `scripts/install_client_json.py <downloaded file>` (with the path:
  without one the script keeps a valid installed file); it checks the
  shape and keeps the old file as `oauth_client.json.previous`.
- **redirect_uri_mismatch**: not a Desktop app client. Only that type
  allows the loopback redirect the server uses.
- **Browser never opens / "could not locate runnable browser"**: run
  `--auth` in a plain terminal, not inside an MCP client's sandbox;
  copy the URL the command prints into any browser on the same machine.
- **Signed in as the wrong account**: `--auth` prints
  `Note: you signed in as X, not Y`. Run it again and pick the right
  account; `--email` only pre-selects.
- **A scope was unticked** on the consent screen: the command warns
  that a gate's scope was not granted. Run `--auth` again and tick all.

## Tokens

- **"Token refresh failed" / invalid_grant after about a week**: the
  app is in Testing, where refresh tokens expire after 7 days. Re-run
  the `--auth` command the error prints (same gates), or publish the app
  to stop the expiry.
- **invalid_grant right after a password change or a revoke** at
  https://myaccount.google.com/permissions: same fix, re-run `--auth`.
- **"has not granted the ... scope"** from a tool: the account was
  authorized without that gate. Either keep it that way (a base-scope
  account is a deliberate choice) or re-run `--auth` with the gate's
  env var set to `true`.
- **Permissions**: the doctor fails on anything but 700 on `<home>` and
  `tokens/`, 600 on the files, and prints the `chmod` to run.

## Registration

- **Codex: tools "unavailable" or missing**: the server took longer
  than Codex's 10 s default; set `startup_timeout_sec = 30` in the
  `[mcp_servers.wx-gmail-mcp]` table (`--print-config codex` includes
  it).
- **Claude Code shows an old tool list** after an upgrade or a gate
  change: it keeps the server process across `/clear`; restart Claude
  Code.
- **"spawn ... ENOENT" / command not found** in a client log: the
  registration's command path is wrong or relative. Use the absolute
  path `--print-config` prints; the doctor warns when the path does not
  exist.
- **Gates differ between clients**: each registration carries its own
  env; the doctor lists them side by side.
- **A client strips or rejects a tool schema**: not seen in the tested
  clients (schemas are flat by design). Report it with the client and
  version at https://github.com/whitechno/wx-gmail-mcp/issues.

## Google Cloud

- **Project id taken** (`gcloud projects create` fails): ids are global;
  add a suffix.
- **Gmail API not enabled**: tools fail with HTTP 403 "Gmail API has not
  been used in project ... or it is disabled". Enable it
  (`scripts/gcloud_project.py <id> --enable` or the console URL).
- **Policy acceptance**: the consent wizard's last step needs the user
  to agree to the Google API Services User Data Policy in person.
- **Download JSON left no file**: a browser tool may cancel the save
  dialog or leave a temporary file; download again from the client's
  row on the Clients page and pass the path to
  `scripts/install_client_json.py`.
- **Wrong account in the console**: the URL's `authuser=` index is not
  reliable; check the avatar/account on the page and switch there.

## Tools

- **"Filter already exists"** from `replace_filter`: the replacement is
  identical to the old filter; Gmail refuses before anything is deleted.
- **HTTP 429 / rate limit**: Gmail per-user quotas; bulk tools chunk
  requests already, so wait and retry.
- **A client caps tools**: run with fewer gates, or filter on the client
  side (Codex `enabled_tools`).
