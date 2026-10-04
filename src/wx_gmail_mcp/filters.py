"""Filter helpers: build a filter from the tool's flags, render one as text.

A filter is ``{"id", "criteria": {...}, "action": {...}}``. Actions hold
label ids; the rendering shows label names so the text reads like the
web UI's filter list. ``FilterRequest`` turns ``create_filter``'s flat
flags into a validated criteria dict and label changes.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from wx_gmail_mcp import gmail
from wx_gmail_mcp import query as gquery
from wx_gmail_mcp.errors import WxGmailError
from wx_gmail_mcp.labels import (
    DISAPPEARING_LABELS,
    LabelMap,
    check_label_name,
    create_parents,
)
from wx_gmail_mcp.safety import describe_error

CATEGORIES: dict[str, str] = {
    "personal": "CATEGORY_PERSONAL",
    "social": "CATEGORY_SOCIAL",
    "promotions": "CATEGORY_PROMOTIONS",
    "updates": "CATEGORY_UPDATES",
    "forums": "CATEGORY_FORUMS",
}
# A filter adds TRASH only through ``delete`` (behind WX_GMAIL_ALLOW_DELETE)
# and never adds SPAM: Gmail has no "mark as spam" filter action.
NEVER_ADDED = DISAPPEARING_LABELS
# Gmail's user label ids look like ``Label_12``; such a ref is never a name
# to create.
_LABEL_ID_RE = re.compile(r"^Label_\d+$")


@dataclass(frozen=True)
class FilterRequest:
    """The flags of ``create_filter`` / ``replace_filter``, validated lazily."""

    from_: str = ""
    to: str = ""
    subject: str = ""
    query: str = ""
    negated_query: str = ""
    has_attachment: bool = False
    exclude_chats: bool = False
    size: int = 0
    size_comparison: str = gquery.SIZE_LARGER
    add_labels: Sequence[str] = ()
    remove_labels: Sequence[str] = ()
    skip_inbox: bool = False
    mark_read: bool = False
    star: bool = False
    always_important: bool = False
    never_important: bool = False
    never_spam: bool = False
    category: str = ""
    delete: bool = False

    def criteria(self) -> dict[str, Any]:
        """The API ``FilterCriteria``; raises without any criterion."""
        out: dict[str, Any] = {}
        for key, value in (
            ("from", self.from_),
            ("to", self.to),
            ("subject", self.subject),
            ("query", self.query),
            ("negatedQuery", self.negated_query),
        ):
            if value.strip():
                out[key] = value.strip()
        if self.has_attachment:
            out["hasAttachment"] = True
        if self.exclude_chats:
            out["excludeChats"] = True
        comparison = self.size_comparison.strip().lower()
        if comparison not in gquery.SIZE_COMPARISONS:
            raise WxGmailError(
                "size_comparison must be one of: "
                + ", ".join(gquery.SIZE_COMPARISONS)
                + "."
            )
        if self.size < 0:
            raise WxGmailError("size must be a number of bytes, 0 or more.")
        if self.size:
            out["size"] = self.size
            out["sizeComparison"] = comparison
        if not out:
            raise WxGmailError(
                "Give at least one criterion: from_, to, subject, query, "
                "negated_query, has_attachment, exclude_chats or size."
            )
        return out

    def shortcut_changes(self) -> tuple[list[str], list[str]]:
        """System label ids the shortcut flags add and remove."""
        if self.always_important and self.never_important:
            raise WxGmailError(
                "always_important and never_important exclude each other."
            )
        add: list[str] = []
        remove: list[str] = []
        if self.skip_inbox:
            remove.append("INBOX")
        if self.mark_read:
            remove.append("UNREAD")
        if self.star:
            add.append("STARRED")
        if self.always_important:
            add.append("IMPORTANT")
        if self.never_important:
            remove.append("IMPORTANT")
        if self.never_spam:
            remove.append("SPAM")
        category = self.category.strip().lower()
        if category:
            if category not in CATEGORIES:
                raise WxGmailError(
                    "category must be one of: " + ", ".join(CATEGORIES) + "."
                )
            add.append(CATEGORIES[category])
        if self.delete:
            add.append("TRASH")
        return add, remove


@dataclass(frozen=True)
class FilterSpec:
    """A filter ready to create: criteria plus label ids to add and remove."""

    criteria: dict[str, Any]
    add: list[str]
    remove: list[str]
    missing: list[str] = field(default_factory=list)  # names still to create

    def body(self) -> dict[str, Any]:
        return {
            "criteria": self.criteria,
            "action": {"addLabelIds": self.add, "removeLabelIds": self.remove},
        }

    def search(self) -> str:
        return gquery.criteria_to_query(self.criteria)


def _dedupe(items: list[str]) -> list[str]:
    seen: list[str] = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen


def plan_filter(
    req: FilterRequest, labels: LabelMap, create_missing_labels: bool
) -> FilterSpec:
    """Validate ``req`` against the account's labels.

    Unknown names in ``add_labels`` go to ``FilterSpec.missing`` when
    ``create_missing_labels`` is set and are an error otherwise; an unknown
    name in ``remove_labels`` is always an error. Nothing is created here.
    """
    criteria = req.criteria()
    shortcut_add, shortcut_remove = req.shortcut_changes()
    add: list[str] = []
    missing: list[str] = []
    for ref in req.add_labels:
        if not ref.strip():
            raise WxGmailError("Empty label name.")
        try:
            label_id = labels.resolve(ref)
        except WxGmailError:
            if not create_missing_labels or _LABEL_ID_RE.fullmatch(ref.strip()):
                raise WxGmailError(
                    f"Unknown label '{ref.strip()}'. Use list_labels to see names "
                    "and ids, or pass create_missing_labels=true with a name."
                ) from None
            missing.append(check_label_name(ref))
            continue
        if label_id in NEVER_ADDED:
            hint = (
                "pass delete=true (needs WX_GMAIL_ALLOW_DELETE=true)"
                if label_id == "TRASH"
                else "Gmail filters cannot mark mail as spam"
            )
            raise WxGmailError(f"A filter cannot add {label_id}: {hint}.")
        add.append(label_id)
    add = _dedupe([*add, *shortcut_add])
    remove = _dedupe([*labels.resolve_all(list(req.remove_labels)), *shortcut_remove])
    missing = _dedupe(missing)
    both = sorted(set(add) & set(remove))
    if both:
        raise WxGmailError(
            f"{', '.join(labels.names(both))} cannot be both added and removed."
        )
    if not add and not remove and not missing:
        raise WxGmailError(
            "Give at least one action: add_labels, remove_labels or a shortcut "
            "such as skip_inbox, mark_read, star or category."
        )
    return FilterSpec(criteria, add, remove, missing)


def create_missing(svc: gmail.GmailService, spec: FilterSpec) -> tuple[FilterSpec, str]:
    """Create ``spec.missing`` labels (parents too) and add their ids.

    Returns the completed spec and a note naming what was created,
    including the parent notes ``create_parents`` returns. The label map
    is refreshed after each label so a parent made for one missing label
    is not created twice for the next.
    """
    if not spec.missing:
        return spec, ""
    created: list[str] = []
    notes: list[str] = []
    add = list(spec.add)
    for name in spec.missing:
        lm = LabelMap.fetch(svc)
        existing = lm.find(name)
        if existing:  # a parent created a moment ago, or a race
            add.append(str(existing["id"]))
            continue
        try:
            label = gmail.create_label(svc, {"name": name})
        except Exception as e:
            made = _created_note(created, notes)
            raise WxGmailError(
                f"Creating label '{name}' failed ({describe_error(e)}); no filter "
                f"was created.{' ' + made + ' They remain.' if made else ''}"
            ) from e
        add.append(str(label["id"]))
        created.append(f"{name} ({label['id']})")
        parent_note = create_parents(svc, lm, name).strip()
        if parent_note:
            notes.append(parent_note)
    return FilterSpec(spec.criteria, _dedupe(add), spec.remove, []), _created_note(
        created, notes
    )


def _created_note(created: list[str], notes: list[str]) -> str:
    head = [f"Created labels: {', '.join(created)}."] if created else []
    return " ".join([*head, *notes])


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
    size = gquery.size_clause(criteria)
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


def body_text(
    criteria: Mapping[str, Any], action: Mapping[str, Any], labels: LabelMap
) -> list[str]:
    """Three indented lines: what it matches, the equivalent search, what it does."""
    return [
        f"  match: {describe_criteria(criteria)}",
        f"  query: {gquery.criteria_to_query(criteria) or '(none)'}",
        f"  do: {describe_action(action, labels)}",
    ]


def filter_text(flt: Mapping[str, Any], labels: LabelMap) -> str:
    """Four lines: id, what it matches, the equivalent search, what it does."""
    criteria = flt.get("criteria", {}) or {}
    action = flt.get("action", {}) or {}
    return "\n".join(
        [_text(flt, "id") or "(no id)", *body_text(criteria, action, labels)]
    )


def spec_text(spec: FilterSpec, labels: LabelMap) -> list[str]:
    """``body_text`` for a filter not created yet; missing labels by name."""
    action = {
        "addLabelIds": [*spec.add, *spec.missing],
        "removeLabelIds": spec.remove,
    }
    return body_text(spec.criteria, action, labels)
