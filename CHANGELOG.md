# Changelog

All notable changes to this project are documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

Nothing yet.

## [0.1.0] - 2026-10-05

The first release: a self-hosted, multi-account Gmail MCP server over
stdio, 25 always-on tools plus 16 behind three opt-in gates, tested
against Claude Code, Claude Desktop, Codex CLI and Antigravity CLI.

### Added

**Server and gates.** Every mailbox tool takes an account alias; results
are plain text; tool schemas are flat (simple types, defaults instead of
unions, no nested objects) so any MCP client can use them. Reading,
searching, labels, organizing and drafts need only the base scopes
(`gmail.readonly`, `gmail.modify`). Three gates add more, each with
exactly one extra OAuth scope, and register their tools only when on:
`WX_GMAIL_ALLOW_SENDING` (`gmail.send`), `WX_GMAIL_ALLOW_SETTINGS`
(`gmail.settings.basic`) and `WX_GMAIL_ALLOW_DELETE` (the full
`https://mail.google.com/` scope). Only the value `true` turns a gate on.
A gate's tools refuse an account that has not granted its scope and name
the re-auth command. Tokens record the scopes Google actually granted;
`--auth` requests exactly the enabled gates' scopes, so turning a gate
off narrows the next grant. Gmail API errors read `HTTP <status>:
<message>`.

**CLI.** `--auth <alias> --email <address>` authorizes an account in the
browser (the loopback flow runs in a terminal, outside the client's
sandbox) and notes a replaced alias; `--list` shows accounts, token
health, granted scopes and one warning per account for gates that are
on but not granted; `--print-config <client>` prints a ready-to-paste
registration for `claude-code`, `claude-desktop`, `codex`, `antigravity`
or `cursor` with the absolute executable path and the gates on in the
environment; `--doctor` checks the installation (Python and `uv`,
`gcloud`, the home directory and its modes, the OAuth client file's
shape without printing it, gates, each account's token and scopes, and
the registrations found in each client's config) and exits 1 on any
failure; with no command the process serves MCP over stdio.

**Accounts.** `list_accounts` (same text as `--list`), `add_account`,
`remove_account` (optional `revoke` at Google), `get_profile`.

**Read and search.** `search` (thread id and labels per hit, paging,
`include_spam_trash`; snippets with HTML entities unescaped and
invisible padding characters stripped, spaces collapsed), `search_threads`,
`read_message` (Cc, labels, attachment list, text or HTML body),
`read_thread` (`max_body`), `list_attachments` (stable part numbers,
since Gmail's attachment ids change between reads) and
`download_attachment`, which saves under `~/.wx-gmail-mcp/downloads/`
with mode 600 and never overwrites unless asked.

**Labels.** `list_labels` (type, opt-in counts), `create_label` (nested
`Parent/Child` with missing parents created, colors, visibility),
`update_label` (rename or move, colors, visibility; reports where nested
labels went) and `delete_label` (the label only, never its messages).
Every tool accepts labels by name or id; system labels are refused.

**Organize.** `modify_labels`, `mark_read`, `mark_unread` and `archive`
on id lists via `batchModify` in chunks of 1000; `modify_thread_labels`
on whole threads; `modify_by_query` on every message matching a search,
dry run by default with a five-message sample and a `limit` (default
5000) above which the call fails. None of them adds `TRASH` or `SPAM`.

**Trash and delete** (`WX_GMAIL_ALLOW_DELETE`). `trash` and `untrash`
for messages or whole threads, up to 100 per call. `delete_permanently`
takes explicit ids only (no query form, no empty-trash tool), at most
100 per call, accepts only mail already in Trash unless
`require_trashed=false`, fetches each item's date, sender and subject
first as the audit trail, deletes exactly those messages in one
`batchDelete` (for threads too), and is a dry run by default.

**Drafts** (always on). `create_draft`, `list_drafts`, `get_draft`,
`update_draft` (replaces the content; a reply draft keeps its thread and
reply headers) and `delete_draft` (unsent drafts only, by id, up to
100; permanent, since Gmail has no Trash for drafts). Drafts and sent
mail take `cc`, `bcc`, `html`, `reply_to` and `attachments` from
`~/.wx-gmail-mcp/outbox/`, uploaded as `message/rfc822` media so
attachments may total 25 MB.

**Send** (`WX_GMAIL_ALLOW_SENDING`). `send_message`, `send_draft`
(reports the recipient and subject it had), `reply` (Reply-To or From,
or the original recipients for the account's own mail; `reply_all`;
quoted original with HTML rendered as text) and `forward` (quoted with
attachments re-attached, or the whole original as a `message/rfc822`
file with `Bcc` stripped). Both stay in the original's conversation and
refuse recipient fields that do not parse instead of dropping them.

**Filters** (`WX_GMAIL_ALLOW_SETTINGS`). `list_filters` and `get_filter`
render criteria, the equivalent Gmail search and the action with label
names. `create_filter` takes flat criteria flags, labels by name or id
with `create_missing_labels`, the web UI's shortcuts (`skip_inbox`,
`mark_read`, `star`, `always_important`, `never_important`,
`never_spam`, `category`) and `delete`, which adds `TRASH` only when the
delete gate is on too; `apply=true` also relabels existing matches
through the same engine as `modify_by_query`, filter first so mail
arriving in between is caught; dry run by default. `delete_filter`
takes an id list; `replace_filter` creates the new filter, then deletes
the old one (Gmail has no filter update).

**Settings** (`WX_GMAIL_ALLOW_SETTINGS`). `get_vacation` and
`set_vacation` (replaces the whole responder; dates as first and last
day in the machine's zone or an IANA `timezone`; Gmail keeps only the
HTML when both messages are given), `list_send_as` (identities with
flags, verification status and the signature as stored) and
`set_signature` (the signature only; whitespace clears it; Gmail refuses
alias changes on personal accounts). Forwarding, auto-forwarding, alias
creation and delegates are deliberately absent: they need the sharing
scope, which the server never requests.

**Setup and clients.** The setup skill
`.agents/skills/setting-up-wx-gmail-mcp/` (Agent Skills format,
reachable from Claude Code through `.claude/skills`): seven idempotent
steps from prerequisites to a verified registration, with sign-in,
policy acceptance and consent left to the user, and three stdlib-only
scripts (`prereqs.py`, `gcloud_project.py`, `install_client_json.py`).
`docs/SETUP-GOOGLE-CLOUD.md` is its human-readable twin.
`docs/CLIENTS.md` has the registration for Claude Code, Claude Desktop,
Codex CLI, Antigravity and Cursor, each checked against the client's
documentation, and the compatibility matrix from live runs (Claude Code,
Claude Desktop, Codex CLI and Antigravity CLI accepted all 41 tools with
no schema, name or rendering issue). `docs/TOOLS.md` is the full tool catalogue:
gate, scope, parameters, defaults, worked examples and the behaviors
found in live use per tool, kept equal to the server by a test.

**Repository.** README, AGENTS.md (conventions for contributors and
agents, imported by CLAUDE.md), CONTRIBUTING.md, SECURITY.md (what the
gates request, why trash sits behind the delete gate, private
vulnerability reporting), CODEOWNERS, issue and PR templates; CI,
gitleaks and a private-pattern guard, CodeQL, dependency review,
zizmor, Dependabot and pre-commit hooks; automatic Claude review on
pull requests with a verdict status check.

[Unreleased]: https://github.com/whitechno/wx-gmail-mcp/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/whitechno/wx-gmail-mcp/releases/tag/v0.1.0
