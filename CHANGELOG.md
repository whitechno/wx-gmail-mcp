# Changelog

All notable changes to this project are documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Project scaffold: `pyproject.toml` (Python 3.14, uv, hatchling), the
  `wx_gmail_mcp` package skeleton with `--version`, tests, ruff and
  pyright configuration.
- Repository guards: CI, gitleaks and private-pattern scan, CodeQL,
  dependency review, zizmor, Dependabot, pre-commit hooks.
- Automatic Claude review on pull requests with a verdict status check
  and run stats; `@claude` on-demand assistance.
- Community files: AGENTS.md, CONTRIBUTING.md, SECURITY.md, CODEOWNERS,
  issue and PR templates.
