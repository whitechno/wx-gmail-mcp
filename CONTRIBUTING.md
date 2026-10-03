# Contributing

Thanks for helping. This page covers the setup and the PR flow. The
conventions themselves are in [AGENTS.md](AGENTS.md); read it first.

## Setup

```bash
git clone https://github.com/whitechno/wx-gmail-mcp.git
cd wx-gmail-mcp
uv sync --all-groups        # Python 3.14 venv with dev tools
uvx pre-commit install      # ruff, gitleaks and the repo guards
uv run pytest
```

## Pull requests

1. Branch from `main`: `dev/<topic>`.
2. Keep the change focused. Add or update tests, and add a line under
   `Unreleased` in `CHANGELOG.md`.
3. Run locally: `uv run ruff check .`, `uv run ruff format .`,
   `uv run pyright`, `uv run pytest`.
4. Open the PR. These checks must pass: `ci`, `secrets`, `codeql`,
   `dependency-review` and the `Claude review` verdict.
5. Address the review, then squash-merge. Direct pushes to `main` are
   blocked.

PRs from forks run without secrets, so the Claude review and the
private-pattern guard are skipped there. A maintainer runs the review
with an `@claude` comment.

## No personal data

Never commit a real email address, a home directory path, a Google
Cloud project number or an OAuth client id, not even in tests, fixtures
or commit messages. Use `you@example.com`, `<alias>` and
`~/.wx-gmail-mcp/`. The `secrets` workflow fails a PR that contains a
maintainer-listed pattern, and gitleaks plus GitHub push protection
catch credentials.

## Testing against a real mailbox

The automated suite never touches the network. If you test manually,
use a dedicated account, keep every artifact under a `wx-test/...`
label, and send, trash or delete only messages you sent to yourself.
