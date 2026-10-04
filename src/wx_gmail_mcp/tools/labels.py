"""Label tools: list_labels, create_label, update_label, delete_label."""

from __future__ import annotations

from typing import Any

from googleapiclient.errors import HttpError
from mcp.server.mcpserver import MCPServer

from wx_gmail_mcp import gmail, labels
from wx_gmail_mcp.errors import WxGmailError
from wx_gmail_mcp.gmail import Runtime
from wx_gmail_mcp.labels import LabelMap
from wx_gmail_mcp.safety import describe_http_error, register_tool


def format_label(label: dict[str, Any], counts: bool) -> str:
    line = f"{label.get('id', '')}: {label.get('name', '')} [{label.get('type', '')}]"
    if counts:
        line += (
            f" messages={label.get('messagesTotal', 0)}"
            f" unread={label.get('messagesUnread', 0)}"
            f" threads={label.get('threadsTotal', 0)}"
        )
    return line


def _create_parents(svc: gmail.GmailService, lm: LabelMap, name: str) -> str:
    """Create the missing ancestors of a nested name, after the label itself.

    Gmail nests by name alone, so the order does not matter to it; doing
    the label first means a rejected label leaves nothing behind. Returns
    a note for the tool output.
    """
    missing = lm.missing_ancestors(name)
    created: list[str] = []
    for parent in missing:
        try:
            gmail.create_label(svc, {"name": parent})
        except HttpError as e:
            return f" Creating parent {parent} failed: {describe_http_error(e)}." + (
                f" Created parent {', '.join(created)}." if created else ""
            )
        created.append(parent)
    return f" Also created parent {', '.join(created)}." if created else ""


def _nested_note(
    before: LabelMap, after: LabelMap, old: str, new: str, label_id: str
) -> str:
    """After renaming ``old`` to ``new``: where did its nested labels go?

    The renamed label itself is excluded: moving ``A`` under ``A/X`` puts
    it among the children of its own old name.
    """
    if not before.children(old):
        return ""
    left = [str(x["name"]) for x in after.children(old) if x["id"] != label_id]
    moved = [str(x["name"]) for x in after.children(new) if x["id"] != label_id]
    notes = []
    if moved:
        notes.append(f" Nested labels moved with it: {', '.join(moved)}.")
    if left:
        notes.append(
            f" Nested labels kept the old path and need their own rename: "
            f"{', '.join(left)}."
        )
    return "".join(notes)


def _check_free(lm: LabelMap, name: str, except_id: str = "") -> None:
    existing = lm.find(name)
    if existing and str(existing["id"]) != except_id:
        raise WxGmailError(
            f"Label '{existing['name']}' already exists (id {existing['id']})."
        )


def register(mcp: MCPServer, rt: Runtime) -> None:
    def list_labels(account: str, include_counts: bool = False) -> str:
        """List an account's labels as 'id: name [type]'. Tools accept either
        the name or the id. `include_counts=true` adds message and thread
        counts (one extra API call per label, so it is slow)."""
        svc = rt.service(account)
        found = gmail.list_labels(svc)
        if not found:
            return "No labels."
        found = sorted(found, key=lambda x: (x.get("type", ""), str(x.get("name", ""))))
        if include_counts:
            found = [gmail.get_label(svc, str(x["id"])) for x in found]
        return "\n".join(format_label(x, include_counts) for x in found)

    def create_label(
        account: str,
        name: str,
        color_background: str = "",
        color_text: str = "",
        label_list_visibility: str = "",
        message_list_visibility: str = "",
    ) -> str:
        """Create a user label. 'Parent/Child' nests it; missing parents are
        created too. Colors are a pair of hex values from Gmail's label
        palette. label_list_visibility: labelShow, labelShowIfUnread or
        labelHide; message_list_visibility: show or hide. Returns the id."""
        body = labels.label_body(
            name=name,
            color_background=color_background,
            color_text=color_text,
            label_list_visibility=label_list_visibility,
            message_list_visibility=message_list_visibility,
        )
        if "name" not in body:
            raise WxGmailError("Label name is required.")
        svc = rt.service(account)
        lm = LabelMap.fetch(svc)
        _check_free(lm, body["name"])
        label = gmail.create_label(svc, body)
        note = _create_parents(svc, lm, body["name"])
        return (
            f"Created label '{label.get('name', body['name'])}' "
            f"(id {label.get('id', '')}).{note}"
        )

    def update_label(
        account: str,
        label: str,
        new_name: str = "",
        color_background: str = "",
        color_text: str = "",
        label_list_visibility: str = "",
        message_list_visibility: str = "",
    ) -> str:
        """Rename a user label (name or id; renaming 'A/B' to 'C/B' moves it)
        or change its colors or visibility, with the same values as
        create_label. Fields left empty keep their current value."""
        body = labels.label_body(
            name=new_name,
            color_background=color_background,
            color_text=color_text,
            label_list_visibility=label_list_visibility,
            message_list_visibility=message_list_visibility,
        )
        if not body:
            raise WxGmailError("Give a new_name, both colors, or a visibility.")
        svc = rt.service(account)
        lm = LabelMap.fetch(svc)
        target = lm.require_user_label(label)
        label_id = str(target["id"])
        old_name = str(target.get("name", ""))
        if "name" in body:
            _check_free(lm, body["name"], except_id=label_id)
        gmail.patch_label(svc, label_id, body)
        note = ""
        if "name" in body and body["name"].lower() != old_name.lower():
            # A fresh snapshot: the old name is gone, so a move under the
            # old path (A -> A/X) recreates the parent A.
            after = LabelMap.fetch(svc)
            note = _create_parents(svc, after, body["name"])
            note += _nested_note(lm, after, old_name, body["name"], label_id)
        return (
            f"Updated label '{old_name}' (id {label_id}): "
            f"{labels.describe_body(body)}.{note}"
        )

    def delete_label(account: str, label: str) -> str:
        """Delete a user label (name or id). Its messages stay in the mailbox
        and keep their other labels; nothing is trashed."""
        svc = rt.service(account)
        lm = LabelMap.fetch(svc)
        target = lm.require_user_label(label)
        name = str(target.get("name", ""))
        had_children = bool(lm.children(name))
        gmail.delete_label(svc, str(target["id"]))
        out = f"Deleted label '{name}' (id {target['id']}); no messages were removed."
        if had_children:
            left = [str(x["name"]) for x in LabelMap.fetch(svc).children(name)]
            out += (
                f" Nested labels still exist: {', '.join(left)}."
                if left
                else " Its nested labels were deleted with it."
            )
        return out

    register_tool(mcp, list_labels)
    register_tool(mcp, create_label)
    register_tool(mcp, update_label)
    register_tool(mcp, delete_label)
