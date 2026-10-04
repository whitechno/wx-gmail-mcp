"""The search-and-relabel engine behind modify_by_query and filter apply.

Find every message matching a Gmail query (Spam and Trash excluded), up to
a limit, then relabel them with ``batchModify`` in chunks of 1000. A dry
run stops after counting and sampling.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from googleapiclient.errors import HttpError

from wx_gmail_mcp import gmail
from wx_gmail_mcp.errors import WxGmailError
from wx_gmail_mcp.gmail import GmailService, header
from wx_gmail_mcp.safety import describe_http_error

DEFAULT_LIMIT = 5000
# Upper bound for ``limit``: 200 list pages of 500 ids.
MAX_LIMIT = 100_000
SAMPLE_SIZE = 5


@dataclass(frozen=True)
class RelabelReport:
    query: str
    matched: int
    modified: int
    dry_run: bool
    sample: list[str] = field(default_factory=list)
    error: str = ""

    def text(self, change: str) -> str:
        """Plain-text summary; ``change`` names the labels, e.g. 'added X'."""
        noun = "message" if self.matched == 1 else "messages"
        if self.matched == 0:
            return f"No messages match '{self.query}'. Nothing to do."
        if self.dry_run:
            head = (
                f"Dry run: {self.matched} {noun} match '{self.query}'. "
                f"Would have {change}."
            )
            tail = "Run again with dry_run=false to apply."
        elif self.error:
            head = (
                f"Modified {self.modified} of {self.matched} {noun} matching "
                f"'{self.query}' before an error: {self.error}"
            )
            tail = "Run again to finish; messages already modified are unaffected."
        else:
            head = f"Modified {self.matched} {noun} matching '{self.query}': {change}."
            tail = ""
        lines = [head, "Sample:", *(f"  {s}" for s in self.sample)]
        if tail:
            lines.append(tail)
        return "\n".join(lines)


def check_limit(limit: int) -> int:
    if not 1 <= limit <= MAX_LIMIT:
        raise WxGmailError(f"limit must be between 1 and {MAX_LIMIT}.")
    return limit


def sample_line(msg: dict[str, Any]) -> str:
    p = msg.get("payload", {}) or {}
    return (
        f"[{msg.get('id', '')}] {header(p, 'Date')} | {header(p, 'From')} | "
        f"{header(p, 'Subject')}"
    )


def relabel_by_query(
    svc: GmailService,
    query: str,
    add: list[str],
    remove: list[str],
    *,
    limit: int = DEFAULT_LIMIT,
    dry_run: bool = True,
) -> RelabelReport:
    """Count, sample and (unless ``dry_run``) relabel the matches of ``query``.

    Raises if more than ``limit`` messages match: the caller then narrows
    the query or raises the limit on purpose. A failure partway through
    the batches comes back in ``RelabelReport.error`` with the count done.
    """
    query = query.strip()
    if not query:
        raise WxGmailError("query is required.")
    check_limit(limit)
    ids = list(gmail.iter_message_ids(svc, query, limit + 1))
    if len(ids) > limit:
        raise WxGmailError(
            f"More than {limit} messages match '{query}'. Narrow the query or "
            f"raise limit (at most {MAX_LIMIT})."
        )
    sample = [
        sample_line(gmail.get_message(svc, i, "metadata", ["From", "Subject", "Date"]))
        for i in ids[:SAMPLE_SIZE]
    ]
    if dry_run or not ids:
        return RelabelReport(query, len(ids), 0, dry_run, sample)
    modified = 0
    error = ""
    try:
        for chunk in gmail.chunked(ids, gmail.BATCH_LIMIT):
            gmail.batch_modify(svc, chunk, add, remove)
            modified += len(chunk)
    except HttpError as e:
        error = describe_http_error(e)
    return RelabelReport(query, len(ids), modified, False, sample, error)
