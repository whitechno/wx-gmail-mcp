# Changelog

All notable changes to this project are documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `reply` and `forward`, registered only with `WX_GMAIL_ALLOW_SENDING=true`
  and only usable by accounts that granted the send scope. Both stay in
  the original's conversation (Gmail thread id plus `In-Reply-To` and
  `References`) and prefix the subject with `Re:` or `Fwd:`. A reply goes
  to Reply-To or From, or to the original recipients when the account
  sent it; `reply_all` copies the others minus the account itself; the
  original text is quoted by default. A forward carries the original
  text under a forwarded-message header with its attachments re-attached,
  or, with `as_attachment`, the complete original as a `message/rfc822`
  file. Both take outbox attachments.
- Draft management, always on: `list_drafts` (newest first, Gmail query
  syntax, paged), `get_draft` (headers, attachments, body),
  `update_draft` (replaces the content with the same fields as
  `create_draft`; a reply draft keeps its thread and reply headers) and
  `delete_draft` (an id list, up to 100, one call each). Deleting a
  draft is permanent and, like `delete_label`, not behind a gate: it
  needs only the base scope and removes unsent drafts only (see
  SECURITY.md). `send_draft`, registered only with `WX_GMAIL_ALLOW_SENDING=true`
  and only usable by accounts that granted the send scope, sends a draft
  as stored and reports the recipient and subject it had.
- `trash` and `untrash`, registered only with `WX_GMAIL_ALLOW_DELETE=true`
  and only usable by accounts that granted the full mail scope. Both take
  an id list of messages (default) or whole threads (`kind="thread"`), up
  to 100 per call, one API call each; a failure midway reports how many
  were done. Trash is reversible; Gmail purges it after 30 days.
- `delete_permanently` (same gate and scope): messages or whole threads
  by explicit id only, at most 100 per call, no query form and no
  empty-trash tool. By default only mail already in Trash is accepted
  (`require_trashed`); every item's date, sender and subject are fetched
  before deleting and returned as the audit trail; exactly those messages
  are then deleted in one `batchDelete`, for threads too. `dry_run`
  defaults to true and shows that trail without deleting anything.
- `list_filters` and `get_filter`, registered only with
  `WX_GMAIL_ALLOW_SETTINGS=true` and only usable by accounts that granted
  the `gmail.settings.basic` scope. Each filter is shown with its
  criteria, the equivalent Gmail search (the translation the web UI
  uses for "also apply to matching conversations", in `query.py`) and
  its action with label names.
- `create_filter` (same gate and scope): criteria flags, labels by
  name or id with `create_missing_labels`, the web UI's shortcuts
  (`skip_inbox`, `mark_read`, `star`, `always_important`,
  `never_important`, `never_spam`, `category`) and `delete`, which adds
  TRASH and works only when `WX_GMAIL_ALLOW_DELETE` is also on. A filter
  catches future mail; `apply=true` also relabels existing matches
  through the same engine as `modify_by_query` (filter first, then the
  apply, so mail arriving in between is caught; `apply_limit` default
  5000). `dry_run` defaults to true and shows the filter, the labels it
  would create and the matching mail without changing anything.
- `delete_filter` (an id list, each filter shown as it was) and
  `replace_filter` (Gmail has no filter update: the new filter is
  created from the same flags as `create_filter`, then the old one is
  deleted, then `apply` runs if asked; `dry_run` default true shows
  both). Same gate and scope.
- `create_label` (nested `Parent/Child`, missing parents created,
  colors, visibility), `update_label` (rename or move, colors,
  visibility) and `delete_label` (the label only, never its messages).
  System labels are refused.
- `modify_by_query`: add or remove labels on every message matching a
  Gmail search. `dry_run` defaults to true and reports the match count
  with a five-message sample; the call fails when more than `limit`
  (default 5000) messages match. `modify_thread_labels` relabels whole
  threads. Both share the search-and-relabel engine (`bulk.py`) that
  filter apply will use.
- `get_profile` (address, message and thread totals, history id),
  `search_threads` (conversations with message count, last message
  headers, labels and snippet), `list_attachments` and
  `download_attachment`, which saves one attachment (by id or file
  name) under `~/.wx-gmail-mcp/downloads/` with mode 600 and never
  overwrites unless asked.
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

- `send_message`, `create_draft`, `update_draft`, `reply` and `forward`
  upload the message as `message/rfc822` media (resumable) instead of a
  base64 `raw` field in the JSON body, which Gmail caps at 5 MB; the
  attachments of one message may now total up to Gmail's 25 MB, checked
  before anything is read or sent. A message with `html` and no plain
  `body` is sent as a single `text/html` part instead of carrying an
  empty `text/plain` alternative. `forward` checks the original's
  declared attachment sizes before fetching any, does not re-attach a
  body part Gmail stored out of line, and strips `Bcc` from the original
  when forwarding it as an attachment; `reply` lists each Cc address
  once.
- `search` unescapes HTML entities in snippets (`&#39;` -> `'`).
- Gmail API errors read `HTTP <status>: <message>` instead of the full
  `HttpError` text with the request URL.
