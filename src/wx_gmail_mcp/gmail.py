"""Gmail API plumbing: service builder, pagination, batch modify.

Every call into ``googleapiclient`` goes through here. The discovery
client has no type information, so the service is typed as ``Any`` and
the rest of the package sees plain dicts and helper functions.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from wx_gmail_mcp import auth
from wx_gmail_mcp.config import Settings

GmailService = Any

# Gmail's cap for messages.batchModify and messages.batchDelete.
BATCH_LIMIT = 1000
# Gmail's cap for list calls.
LIST_PAGE_LIMIT = 500


def build_service(creds: Credentials) -> GmailService:
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


class Runtime:
    """Settings plus the per-alias service factory tools call.

    Tests replace ``service`` with a fake; nothing else in the package
    talks to Gmail.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def credentials(self, alias: str) -> Credentials:
        return auth.load_credentials(self.settings, alias)

    def service(self, alias: str) -> GmailService:
        return build_service(self.credentials(alias))


def header(payload: dict[str, Any], name: str) -> str:
    """Case-insensitive header lookup in a message payload."""
    for h in payload.get("headers", []) or []:
        if str(h.get("name", "")).lower() == name.lower():
            return str(h.get("value", ""))
    return ""


def get_profile(svc: GmailService) -> dict[str, Any]:
    return svc.users().getProfile(userId="me").execute()


def list_messages(
    svc: GmailService,
    query: str,
    max_results: int,
    page_token: str = "",
    include_spam_trash: bool = False,
) -> dict[str, Any]:
    """One page of ``messages.list``: ``messages`` and ``nextPageToken``."""
    kwargs: dict[str, Any] = {
        "userId": "me",
        "q": query,
        "maxResults": min(max_results, LIST_PAGE_LIMIT),
        "includeSpamTrash": include_spam_trash,
    }
    if page_token:
        kwargs["pageToken"] = page_token
    return svc.users().messages().list(**kwargs).execute()


def iter_message_ids(
    svc: GmailService,
    query: str,
    limit: int,
    include_spam_trash: bool = False,
) -> Iterator[str]:
    """Message ids matching ``query``, across pages, at most ``limit``."""
    token = ""
    yielded = 0
    while yielded < limit:
        page = list_messages(svc, query, limit - yielded, token, include_spam_trash)
        for m in page.get("messages", []) or []:
            if yielded >= limit:
                return
            yield str(m["id"])
            yielded += 1
        token = str(page.get("nextPageToken", "") or "")
        if not token:
            return


def get_message(
    svc: GmailService,
    message_id: str,
    fmt: str = "full",
    metadata_headers: list[str] | None = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"userId": "me", "id": message_id, "format": fmt}
    if metadata_headers:
        kwargs["metadataHeaders"] = metadata_headers
    return svc.users().messages().get(**kwargs).execute()


def get_thread(svc: GmailService, thread_id: str, fmt: str = "full") -> dict[str, Any]:
    return svc.users().threads().get(userId="me", id=thread_id, format=fmt).execute()


def list_labels(svc: GmailService) -> list[dict[str, Any]]:
    return svc.users().labels().list(userId="me").execute().get("labels", []) or []


def get_label(svc: GmailService, label_id: str) -> dict[str, Any]:
    return svc.users().labels().get(userId="me", id=label_id).execute()


def create_label(svc: GmailService, body: dict[str, Any]) -> dict[str, Any]:
    return svc.users().labels().create(userId="me", body=body).execute()


def patch_label(
    svc: GmailService, label_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    return svc.users().labels().patch(userId="me", id=label_id, body=body).execute()


def delete_label(svc: GmailService, label_id: str) -> None:
    svc.users().labels().delete(userId="me", id=label_id).execute()


def modify_message(
    svc: GmailService, message_id: str, add: list[str], remove: list[str]
) -> dict[str, Any]:
    body = {"addLabelIds": add, "removeLabelIds": remove}
    return (
        svc.users().messages().modify(userId="me", id=message_id, body=body).execute()
    )


def chunked(items: list[str], size: int) -> Iterator[list[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def batch_modify(
    svc: GmailService, message_ids: list[str], add: list[str], remove: list[str]
) -> int:
    """``messages.batchModify`` in chunks of 1000; returns the id count."""
    for chunk in chunked(message_ids, BATCH_LIMIT):
        body = {"ids": chunk, "addLabelIds": add, "removeLabelIds": remove}
        svc.users().messages().batchModify(userId="me", body=body).execute()
    return len(message_ids)


def send_raw(svc: GmailService, raw: str) -> dict[str, Any]:
    """``messages.send`` of a base64url RFC 822 message."""
    return svc.users().messages().send(userId="me", body={"raw": raw}).execute()


def create_draft(svc: GmailService, raw: str) -> dict[str, Any]:
    body = {"message": {"raw": raw}}
    return svc.users().drafts().create(userId="me", body=body).execute()
