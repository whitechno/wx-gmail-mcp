# Changelog

All notable changes to this project are documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `create_label` (nested `Parent/Child`, missing parents created,
  colors, visibility), `update_label` (rename or move, colors,
  visibility) and `delete_label` (the label only, never its messages).
  System labels are refused.
- Foundations: `config` (home dir, `WX_GMAIL_ALLOW_*` gates, gate to
  scope mapping), `accounts` (alias validation, `accounts.json`), `auth`
  (OAuth flow, token refresh, scope bookkeeping, re-auth hints), `gmail`
  (service builder, pagination, `batchModify` in chunks of 1000),
  `safety` (readable tool errors, id caps, `downloads/` and `outbox/`
  path allowlist) and `server` (gated tool registration, no tools yet).
- The eleven always-on tools ported from the predecessor, extended:
  `list_accounts` (granted scopes, gate warnings), `add_account`,
  `remove_account` (optional `revoke`), `search` (thread id and labels
  per hit, `page_token`, `include_spam_trash`), `read_message` (thread
  id, labels, Cc, attachment list), `read_thread` (per-message id and
  labels, `max_body`), `list_labels` (type, opt-in counts), and
  `modify_labels`, `mark_read`, `mark_unread`, `archive` on id lists via
  `batchModify`. Labels are accepted by name or id.
- `create_draft` (always on) and `send_message` (only with
  `WX_GMAIL_ALLOW_SENDING=true`, and only if the account granted the
  send scope), both with `cc`, `bcc`, `html`, `reply_to` and
  `attachments` read from `~/.wx-gmail-mcp/outbox/`.
- CLI: `--auth <alias> --email <address>` authorizes an account in the
  browser; `--list` shows accounts, token health, granted scopes and
  gates that are on but not granted; with no command the process serves
  MCP over stdio.
- Project scaffold: `pyproject.toml` (Python 3.14, uv, hatchling), the
  `wx_gmail_mcp` package skeleton with `--version`, tests, ruff and
  pyright configuration.
- Repository guards: CI, gitleaks and private-pattern scan, CodeQL,
  dependency review, zizmor, Dependabot, pre-commit hooks.
- Automatic Claude review on pull requests with a verdict status check
  and run stats; `@claude` on-demand assistance.
- Community files: AGENTS.md, CONTRIBUTING.md, SECURITY.md, CODEOWNERS,
  issue and PR templates.

### Changed

- `search` unescapes HTML entities in snippets (`&#39;` -> `'`).
- Gmail API errors read `HTTP <status>: <message>` instead of the full
  `HttpError` text with the request URL.
