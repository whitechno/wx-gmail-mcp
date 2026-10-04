"""Label name <-> id resolution, and validation of label fields.

Every tool that takes labels accepts names or ids.
"""

from __future__ import annotations

import re
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

LABEL_LIST_VISIBILITY = ("labelShow", "labelShowIfUnread", "labelHide")
MESSAGE_LIST_VISIBILITY = ("show", "hide")
# Gmail's documented cap on a label name.
MAX_LABEL_NAME = 225

_HEX_COLOR_RE = re.compile(r"^#[0-9a-f]{6}$")


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

    def find(self, name: str) -> dict[str, Any] | None:
        """The label with this name (case-insensitive), if any."""
        label_id = self.by_name.get(name.strip().lower())
        return self.by_id.get(label_id) if label_id else None

    def require_user_label(self, ref: str) -> dict[str, Any]:
        """The full label resource for a user label name or id.

        System labels cannot be created, changed or deleted.
        """
        label = self.by_id.get(self.resolve(ref))
        if label is None or str(label.get("type", "")) == "system":
            raise WxGmailError(
                f"'{ref.strip()}' is a system label; only user labels can be "
                "created, changed or deleted."
            )
        return label

    def missing_ancestors(self, name: str) -> list[str]:
        """Parents of a nested name that do not exist yet, outermost first."""
        parts = name.split("/")
        return [
            "/".join(parts[:i])
            for i in range(1, len(parts))
            if self.find("/".join(parts[:i])) is None
        ]

    def children(self, name: str) -> list[dict[str, Any]]:
        """Labels nested under ``name``, sorted by name."""
        prefix = name.lower() + "/"
        found = [x for x in self.labels if str(x["name"]).lower().startswith(prefix)]
        return sorted(found, key=lambda x: str(x["name"]))


def check_label_name(name: str) -> str:
    """A valid user label name: non-empty segments, not a system name.

    Whitespace around the name and around each ``/`` is dropped, so the
    name the tool reports is the name Gmail stores.
    """
    name = name.strip()
    if not name:
        raise WxGmailError("Label name is required.")
    if len(name) > MAX_LABEL_NAME:
        raise WxGmailError(f"Label name is longer than {MAX_LABEL_NAME} characters.")
    segments = [seg.strip() for seg in name.split("/")]
    if any(not seg for seg in segments):
        raise WxGmailError(
            f"Label name '{name}' has an empty segment; nest as 'Parent/Child'."
        )
    name = "/".join(segments)
    if name.upper() in SYSTEM_LABELS:
        raise WxGmailError(f"'{name}' is a system label name.")
    return name


def _check_choice(value: str, what: str, allowed: tuple[str, ...]) -> str:
    value = value.strip()
    if value not in allowed:
        raise WxGmailError(f"{what} must be one of: {', '.join(allowed)}.")
    return value


def _check_color(value: str, what: str) -> str:
    value = value.strip().lower()
    if not _HEX_COLOR_RE.fullmatch(value):
        raise WxGmailError(f"{what} must be a hex color like #16a765.")
    return value


def label_body(
    *,
    name: str = "",
    color_background: str = "",
    color_text: str = "",
    label_list_visibility: str = "",
    message_list_visibility: str = "",
) -> dict[str, Any]:
    """Validated fields of a label resource; empty strings are left unset."""
    body: dict[str, Any] = {}
    if name.strip():
        body["name"] = check_label_name(name)
    if label_list_visibility.strip():
        body["labelListVisibility"] = _check_choice(
            label_list_visibility, "label_list_visibility", LABEL_LIST_VISIBILITY
        )
    if message_list_visibility.strip():
        body["messageListVisibility"] = _check_choice(
            message_list_visibility, "message_list_visibility", MESSAGE_LIST_VISIBILITY
        )
    if color_background.strip() or color_text.strip():
        if not (color_background.strip() and color_text.strip()):
            raise WxGmailError(
                "Give both color_background and color_text (hex colors from "
                "Gmail's label palette)."
            )
        body["color"] = {
            "backgroundColor": _check_color(color_background, "color_background"),
            "textColor": _check_color(color_text, "color_text"),
        }
    return body


def describe_body(body: dict[str, Any]) -> str:
    """One clause per changed field, for tool output."""
    parts: list[str] = []
    if "name" in body:
        parts.append(f"name '{body['name']}'")
    if "color" in body:
        c = body["color"]
        parts.append(f"color {c['textColor']} on {c['backgroundColor']}")
    if "labelListVisibility" in body:
        parts.append(f"label list {body['labelListVisibility']}")
    if "messageListVisibility" in body:
        parts.append(f"message list {body['messageListVisibility']}")
    return ", ".join(parts)
