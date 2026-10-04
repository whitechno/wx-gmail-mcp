"""Label name <-> id resolution. Every tool that takes labels accepts both."""

from __future__ import annotations

from typing import Any

from wx_gmail_mcp import gmail
from wx_gmail_mcp.errors import WxGmailError

# Gmail's built-in labels have fixed ids equal to their names.
SYSTEM_LABELS = frozenset(
    {
        "INBOX",
        "SPAM",
        "TRASH",
        "UNREAD",
        "STARRED",
        "IMPORTANT",
        "SENT",
        "DRAFT",
        "CHAT",
        "CATEGORY_PERSONAL",
        "CATEGORY_SOCIAL",
        "CATEGORY_PROMOTIONS",
        "CATEGORY_UPDATES",
        "CATEGORY_FORUMS",
    }
)


class LabelMap:
    """Snapshot of an account's labels with lookups both ways."""

    def __init__(self, labels: list[dict[str, Any]]) -> None:
        self.labels = labels
        self.by_id: dict[str, dict[str, Any]] = {str(x["id"]): x for x in labels}
        self.by_name: dict[str, str] = {
            str(x["name"]).lower(): str(x["id"]) for x in labels
        }

    @classmethod
    def fetch(cls, svc: gmail.GmailService) -> LabelMap:
        return cls(gmail.list_labels(svc))

    def name(self, label_id: str) -> str:
        """Display name for an id; unknown ids come back unchanged."""
        label = self.by_id.get(label_id)
        return str(label["name"]) if label else label_id

    def names(self, label_ids: list[str]) -> list[str]:
        return [self.name(i) for i in label_ids]

    def resolve(self, ref: str) -> str:
        """Turn a label name or id into an id, or raise a readable error."""
        ref = ref.strip()
        if not ref:
            raise WxGmailError("Empty label name.")
        if ref in self.by_id:
            return ref
        if ref.upper() in SYSTEM_LABELS:
            return ref.upper()
        label_id = self.by_name.get(ref.lower())
        if label_id is None:
            raise WxGmailError(
                f"Unknown label '{ref}'. Use list_labels to see names and ids."
            )
        return label_id

    def resolve_all(self, refs: list[str]) -> list[str]:
        seen: list[str] = []
        for ref in refs:
            label_id = self.resolve(ref)
            if label_id not in seen:
                seen.append(label_id)
        return seen
