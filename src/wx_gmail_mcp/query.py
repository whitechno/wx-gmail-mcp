"""Filter criteria -> Gmail search query, the way the web UI translates them.

Gmail's "Also apply filter to matching conversations" runs a search built
from the filter's criteria. ``criteria_to_query`` builds the same search,
so ``create_filter(apply=true)`` touches the mail the web UI would. It
works on the API's ``FilterCriteria`` shape (camelCase keys), so it
serves both new filters and the ones ``list_filters`` renders.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

SIZE_LARGER = "larger"
SIZE_SMALLER = "smaller"
SIZE_COMPARISONS: tuple[str, ...] = (SIZE_LARGER, SIZE_SMALLER)

KIB = 1024
MIB = 1024 * 1024

# Header criteria: the web UI wraps each value in parentheses, so a value
# with spaces or OR stays one operand.
_HEADER_FIELDS: tuple[str, ...] = ("from", "to", "subject")


def size_text(size: int) -> str:
    """Bytes as a Gmail size operand: whole mebibytes as ``10M``, whole
    kibibytes as ``512K``, anything else as plain bytes."""
    if size > 0 and size % MIB == 0:
        return f"{size // MIB}M"
    if size > 0 and size % KIB == 0:
        return f"{size // KIB}K"
    return str(size)


def _text(criteria: Mapping[str, Any], key: str) -> str:
    return str(criteria.get(key, "") or "").strip()


def size_clause(criteria: Mapping[str, Any]) -> str:
    """``larger:10M`` / ``smaller:512K``, or '' without a usable size."""
    size = criteria.get("size", 0) or 0
    comparison = _text(criteria, "sizeComparison")
    if (
        not isinstance(size, int)
        or isinstance(size, bool)
        or size <= 0
        or comparison not in SIZE_COMPARISONS
    ):
        return ""
    return f"{comparison}:{size_text(size)}"


def criteria_to_query(criteria: Mapping[str, Any]) -> str:
    """The Gmail search equivalent to a filter's criteria, '' if it has none.

    ``from``/``to``/``subject`` become ``from:(value)``; ``query`` is used
    verbatim; ``negatedQuery`` becomes ``-{value}``; ``hasAttachment`` adds
    ``has:attachment``; ``excludeChats`` adds ``-in:chats``; ``size`` with
    ``sizeComparison`` adds ``larger:``/``smaller:``.
    """
    parts: list[str] = []
    for field in _HEADER_FIELDS:
        value = _text(criteria, field)
        if value:
            parts.append(f"{field}:({value})")
    query = _text(criteria, "query")
    if query:
        parts.append(query)
    negated = _text(criteria, "negatedQuery")
    if negated:
        parts.append(f"-{{{negated}}}")
    if criteria.get("hasAttachment"):
        parts.append("has:attachment")
    if criteria.get("excludeChats"):
        parts.append("-in:chats")
    size = size_clause(criteria)
    if size:
        parts.append(size)
    return " ".join(parts)
