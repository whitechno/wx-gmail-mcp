# wx-gmail-mcp

A self-hosted MCP server that gives your AI agent (Claude Code, Codex,
Gemini CLI, Cursor, any MCP client) controlled access to *several* Gmail
accounts at once: mail, labels, filters, drafts and bulk operations, with
sending, settings and deletion behind opt-in gates.

**Status: under development, not yet usable.** The first release will be
`v0.1.0`; see [CHANGELOG.md](CHANGELOG.md).

## Development

Requires Python 3.14+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --all-groups
uv run pytest
uv run wx-gmail-mcp --version
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the PR flow and
[AGENTS.md](AGENTS.md) for the conventions that every contributor and
agent follows.

## License

[MIT](LICENSE).
