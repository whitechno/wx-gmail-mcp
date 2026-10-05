# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub's
[private vulnerability reporting](https://github.com/whitechno/wx-gmail-mcp/security/advisories/new)
for this repository. Do not open a public issue for a security problem.

Include what you found, how to reproduce it and, if you have one, a fix.
You will get an acknowledgement within a week.

## Supported versions

Only the latest release on `main` receives fixes.

## What this project protects

wx-gmail-mcp runs on your machine with your own Google Cloud OAuth
client. Things to know:

- OAuth tokens and the client JSON live under `~/.wx-gmail-mcp/` with
  modes 700/600. They never leave the machine.
- Sending, settings changes and trash/delete are off unless their
  `WX_GMAIL_ALLOW_*` gate is on, and each gate requests only the OAuth
  scope it needs. The gates are enforced in the server, not by the
  client.
- Permanent deletion takes explicit ids only (no query form, no
  empty-trash tool), is capped at 100 per call, accepts only mail already
  in Trash unless told otherwise, is a dry run by default and returns an
  audit trail. Mailbox forwarding is deliberately not exposed.
- The gates cover mail. Deleting a *label* (`delete_label`) is always
  on: it needs only the base `modify` scope and removes no message, but
  it does take the label off every message for good.
- File access is limited to `~/.wx-gmail-mcp/downloads/` and
  `~/.wx-gmail-mcp/outbox/`.

Reports that cross any of these lines are very welcome.
