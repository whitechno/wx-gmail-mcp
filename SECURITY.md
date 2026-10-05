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
  scope it needs: `gmail.send`, `gmail.settings.basic` and the full
  `https://mail.google.com/` scope. A gate does two things: it adds its
  scope when an account is authorized, and it registers its tools when
  the server starts. The tools of a gate refuse an account that has not
  granted the gate's scope. The gates are enforced in the server, not by
  the client.
- The full mail scope that `WX_GMAIL_ALLOW_DELETE` requests also covers
  reading, labels and sending (it does not cover the settings scope). An
  account authorized with the delete gate can therefore use the send
  tools whenever the server runs with the sending gate on. Authorize
  each account with exactly the gates it should have; `--list` and
  `list_accounts` show what each one granted.
- Trash and untrash need only the base scope at Google, but they sit
  behind `WX_GMAIL_ALLOW_DELETE` with the full scope on purpose, so that
  every tool that makes mail disappear is one opt-in. The always-on
  relabel tools never add `TRASH` or `SPAM`, and a filter adds `TRASH`
  only through its `delete` flag, which needs that gate too.
- Permanent deletion takes explicit ids only (no query form, no
  empty-trash tool), is capped at 100 per call, accepts only mail already
  in Trash unless told otherwise, is a dry run by default and returns an
  audit trail. Mailbox forwarding is deliberately not exposed.
- The gates cover mail. Two tools are always on because they need only
  the base `modify` scope: `delete_label` removes no message, but it
  does take the label off every message for good; `delete_draft`
  removes unsent drafts for good (Gmail has no Trash for drafts), by
  explicit id, at most 100 per call, and never touches sent or received
  mail.
- File access is limited to `~/.wx-gmail-mcp/downloads/` and
  `~/.wx-gmail-mcp/outbox/`.

Reports that cross any of these lines are very welcome.
