# wx-gmail-mcp: contributor and agent conventions

This file is read by every agent harness (Claude Code via `CLAUDE.md`,
Codex, Antigravity and others read it directly) and by human contributors.
It holds conventions only, not implementation notes.

If `AGENTS.local.md` exists at the repo root, read it before any work
(maintainer-only, gitignored).

## What this is

A self-hosted, multi-account Gmail MCP server, usable from any
MCP-capable agent harness. Python 3.14+, `uv`, `src/` layout, MIT.

## Layout

| Path                      | Holds                                              |
|---------------------------|----------------------------------------------------|
| `src/wx_gmail_mcp/`       | the package: `cli`, `config`, `auth`, `gmail`, ... |
| `src/wx_gmail_mcp/tools/` | one module per tool group, each with `register()`  |
| `tests/`                  | pytest suite; mirrors `src/`; no network           |
| `scripts/`                | repo tooling (guards), not shipped in the package  |
| `.agents/skills/`         | agent skills, harness-neutral; `.claude/skills`    |
|                           | is a symlink to it                                 |
| `.github/`                | workflows, Dependabot, templates, CODEOWNERS       |
| `docs/`                   | user documentation                                 |

## Commands

```bash
uv sync --all-groups          # create .venv with runtime + dev deps
uv run pytest                 # tests
uv run ruff check . && uv run ruff format --check .
uv run pyright
uv run wx-gmail-mcp --version
uvx pre-commit install        # once per clone: ruff, gitleaks, guards
```

CI runs the same four checks on every PR and on `main`.

## Rules

- **No personal data in this repo, ever.** No real email addresses,
  home paths (`/Users/...`, `/home/...`), Google Cloud project numbers
  or OAuth client ids, in code, docs, tests, fixtures, commit messages
  or PR text. Use placeholders: `you@example.com`, `<alias>`,
  `~/.wx-gmail-mcp/`. The private-pattern guard (`secrets` workflow,
  pre-commit hook) backs this up; it does not replace care.
- **No secrets.** Client JSON, tokens and account lists live only under
  `~/.wx-gmail-mcp/` (mode 700/600). `.gitignore` lists them; gitleaks
  and GitHub push protection scan for the rest.
- **Harness-neutral.** Nothing client-specific in the server. Tool
  descriptions say "the user", never the name of an assistant. Tool
  schemas stay flat: simple types, defaults instead of `X | None`, no
  nested objects, `$ref` or `anyOf`.
- **Gated writes, server-side.** Sending, settings and trash/delete
  tools register only when their `WX_GMAIL_ALLOW_*` env gate is on, and
  each gate requests only the OAuth scope it needs. Guardrails never
  depend on a client's approval prompts. The gates cover mail. Two
  always-on exceptions, both base scope: `delete_label` removes no
  message; `delete_draft` removes unsent drafts only (no Trash step).
- **Thin tools.** Tools validate input, call helpers and format plain
  text output. Gmail plumbing lives in the helper modules.
- **Nothing registers at import time.** `server.py` calls each tool
  module's `register(mcp)` only when its gate is on, so tests can build
  a server for any gate combination.
- **Tests with every change.** Unit tests run against a fake Gmail
  service; nothing in `tests/` touches the network or a real mailbox.
- **Docstrings stay short.** They load into every session's context.
  Examples go to `docs/TOOLS.md`.
- **Style.** `ruff` (lint + format, line length 88) and `pyright` must
  pass. Prose in Markdown wraps at 80 columns except tables, code and
  URLs.

## Workflow

- `main` accepts pull requests only. Work on a `dev/<topic>` branch,
  open a PR, wait for CI, `secrets`, `codeql` and the Claude review
  verdict, then squash-merge.
- Never push to `main`, never force-push, never rewrite shared history.
- Pin third-party GitHub Actions to a commit SHA with the version in a
  trailing comment; Dependabot keeps them current.
- Keep the changelog (`CHANGELOG.md`, Unreleased section) in the same
  PR as the change.
