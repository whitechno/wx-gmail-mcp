# Changelog

All notable changes to this project are documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Foundations: `config` (home dir, `WX_GMAIL_ALLOW_*` gates, gate to
  scope mapping), `accounts` (alias validation, `accounts.json`), `auth`
  (OAuth flow, token refresh, scope bookkeeping, re-auth hints), `gmail`
  (service builder, pagination, `batchModify` in chunks of 1000),
  `safety` (readable tool errors, id caps, `downloads/` and `outbox/`
  path allowlist) and `server` (gated tool registration, no tools yet).
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
