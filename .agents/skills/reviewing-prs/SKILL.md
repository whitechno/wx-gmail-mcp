---
name: reviewing-prs
description: Review brief for pull requests to wx-gmail-mcp. Used by the Claude review workflow and by any agent asked to review a PR locally. Read it in full before reviewing, then follow it exactly.
---

# Reviewing a pull request

You are the reviewer, not the author. Find what is wrong; do not fix
it. Change no files and push no commits. Read, grep and diff only.

## Read first

1. `AGENTS.md`: the conventions every change must meet.
2. The diff of the revision you were given (base...head). Review that
   revision only, never the live branch.
3. Every file the diff touches, at the head revision, in full when it
   is short enough to matter.
4. The tests that cover the change, and the changelog entry.

## What to check, in this order

1. **Personal data and secrets.** Any real email address, home path
   (`/Users/...`, `/home/...`), Google Cloud project number, OAuth
   client id, token or client JSON content, anywhere in the diff,
   including tests, fixtures, comments, docs and the PR text. One hit
   is blocking.
2. **Security posture.** Gated tools (send, settings, trash/delete)
   register only behind their `WX_GMAIL_ALLOW_*` gate. Each gate
   requests only its scope. `delete_permanently` keeps its guardrails:
   explicit ids only, capped, `require_trashed` default on, audit
   trail. No sharing-scope tools and no forwarding. File access stays
   inside `downloads/` and `outbox/`. Workflow changes keep SHA pins,
   minimal permissions and never `pull_request_target`.
3. **Harness neutrality.** No client-specific behavior. Descriptions
   say "the user", never an assistant's name. Tool schemas are flat:
   simple types, defaults instead of `X | None`, no nested objects,
   `$ref`, `$defs` or `anyOf`. Tool names match `^[a-z][a-z0-9_]{0,40}$`.
4. **Correctness.** Logic errors, unhandled Gmail API failures,
   pagination and chunking mistakes (`batchModify` chunks of 1000),
   label name/id confusion, MIME and header mistakes in reply/forward,
   dry-run paths that still write.
5. **Tests.** New behavior has tests against the fake Gmail service;
   nothing in `tests/` touches the network. Registration tests still
   match the catalogue when a tool is added or moved.
6. **Code rules.** Thin tools, plumbing in helpers, nothing registers
   at import time, short docstrings, plain-text results.
7. **Docs and changelog.** User-visible changes have a line under
   `Unreleased` in `CHANGELOG.md` and, when they add or change a tool,
   an update to `docs/TOOLS.md` once that file exists.

## What not to do

- Do not run code, tests or CI. They are out of scope; assume the suite
  passes and say nothing about it.
- Do not restyle. `ruff` and `pyright` own formatting and typing.
- Do not request changes for taste. A finding names a rule, a bug or a
  risk.
- Do not approve on the strength of the description. Verify in the
  diff.

## Severity

- **Blocking:** personal data, a security-posture violation, a
  correctness bug on a code path a user can reach, a missing test for
  a gated or destructive action. Any blocking finding means
  `REQUEST_CHANGES`.
- **Should fix:** everything else that violates `AGENTS.md`. Alone,
  these still allow `APPROVE` when you state them; use judgement.
- **Nit:** optional. Say so.

## Write-up

Keep it short and concrete. Reference `path:line`. Structure:

```
Summary: one or two sentences on what the PR does and your verdict.

Findings:
- [blocking] path:line — what is wrong, why it matters, what would fix it
- [should] ...
- [nit] ...
(or "No findings.")

Verdict form: review | comment (state whether the other was refused)

Reviewed-head: <full head SHA>
Reviewed-base: <base branch>
Reviewed-base-oid: <full base SHA>
Reviewer-model: <model id> · reasoning_effort <value> · CLAUDE_EFFORT <value>
```

The four metadata lines are mandatory and parsed by the merge gate.
Use the SHAs you were given, never ones you looked up from the live
branch.

## Posting the verdict

Exactly one verdict per run, as your last act:

1. A formal review: `gh pr review <n> --approve --body "<write-up>"`
   or `--request-changes`. A refusal to approve from a GitHub Actions
   identity is expected; it is not a finding.
2. If that failed, a top-level comment whose first line is exactly
   `VERDICT: APPROVE` or `VERDICT: REQUEST_CHANGES`, then a blank line,
   then the write-up.

Inline comments on specific lines are welcome in addition, never
instead.
