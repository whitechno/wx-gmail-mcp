"""Filter helpers: plain-text rendering of Gmail filter resources.

A filter is ``{"id", "criteria": {...}, "action": {...}}``. Actions hold
label ids; the rendering shows label names so the text reads like the
web UI's filter list.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from wx_gmail_mcp import query
from wx_gmail_mcp.labels import LabelMap


def _text(mapping: Mapping[str, Any], key: str) -> str:
    return str(mapping.get(key, "") or "").strip()


def describe_criteria(criteria: Mapping[str, Any]) -> str:
    """The criteria as readable clauses, e.g. ``from "a@x", has attachment``."""
    clauses: list[str] = []
    for key, label in (
        ("from", "from"),
        ("to", "to"),
        ("subject", "subject"),
        ("query", "has words"),
        ("negatedQuery", "lacks words"),
    ):
        value = _text(criteria, key)
        if value:
            clauses.append(f'{label} "{value}"')
    if criteria.get("hasAttachment"):
        clauses.append("has attachment")
    if criteria.get("excludeChats"):
        clauses.append("no chats")
    size = query.size_clause(criteria)
    if size:
        comparison, _, amount = size.partition(":")
        clauses.append(f"{comparison} than {amount}")
    return ", ".join(clauses) or "(none)"


def describe_action(action: Mapping[str, Any], labels: LabelMap) -> str:
    """The action as ``add X, Y; remove Z; forward to a@x``, with label names."""
    parts: list[str] = []
    add = [str(x) for x in action.get("addLabelIds", []) or []]
    remove = [str(x) for x in action.get("removeLabelIds", []) or []]
    if add:
        parts.append("add " + ", ".join(labels.names(add)))
    if remove:
        parts.append("remove " + ", ".join(labels.names(remove)))
    forward = _text(action, "forward")
    if forward:
        parts.append(f"forward to {forward}")
    return "; ".join(parts) or "(none)"


def filter_text(flt: Mapping[str, Any], labels: LabelMap) -> str:
    """Four lines: id, what it matches, the equivalent search, what it does."""
    criteria = flt.get("criteria", {}) or {}
    action = flt.get("action", {}) or {}
    return "\n".join(
        [
            _text(flt, "id") or "(no id)",
            f"  match: {describe_criteria(criteria)}",
            f"  query: {query.criteria_to_query(criteria) or '(none)'}",
            f"  do: {describe_action(action, labels)}",
        ]
    )
