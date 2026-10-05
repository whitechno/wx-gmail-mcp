"""Gmail API plumbing: service builder, pagination, batch modify, uploads.

Every call into ``googleapiclient`` goes through here. The discovery
client has no type information, so the service is typed as ``Any`` and
the rest of the package sees plain dicts and helper functions.

Outgoing messages (send, drafts) go up as a ``message/rfc822`` media
upload rather than a base64 ``raw`` field in the JSON body: the JSON form
is capped at 5 MB, the upload at 35 MB.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

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


def list_threads(
    svc: GmailService,
    query: str,
    max_results: int,
    page_token: str = "",
    include_spam_trash: bool = False,
) -> dict[str, Any]:
    """One page of ``threads.list``: ``threads`` and ``nextPageToken``."""
    kwargs: dict[str, Any] = {
        "userId": "me",
        "q": query,
        "maxResults": min(max_results, LIST_PAGE_LIMIT),
        "includeSpamTrash": include_spam_trash,
    }
    if page_token:
        kwargs["pageToken"] = page_token
    return svc.users().threads().list(**kwargs).execute()


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


def get_thread(
    svc: GmailService,
    thread_id: str,
    fmt: str = "full",
    metadata_headers: list[str] | None = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"userId": "me", "id": thread_id, "format": fmt}
    if metadata_headers:
        kwargs["metadataHeaders"] = metadata_headers
    return svc.users().threads().get(**kwargs).execute()


def get_attachment(
    svc: GmailService, message_id: str, attachment_id: str
) -> dict[str, Any]:
    """``messages.attachments.get``: ``data`` (base64url) and ``size``."""
    return (
        svc.users()
        .messages()
        .attachments()
        .get(userId="me", messageId=message_id, id=attachment_id)
        .execute()
    )


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


def modify_thread(
    svc: GmailService, thread_id: str, add: list[str], remove: list[str]
) -> dict[str, Any]:
    """``threads.modify``: every message in the thread gets the change."""
    body = {"addLabelIds": add, "removeLabelIds": remove}
    return svc.users().threads().modify(userId="me", id=thread_id, body=body).execute()


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


def trash_message(svc: GmailService, message_id: str) -> dict[str, Any]:
    """``messages.trash``: adds TRASH; Gmail purges Trash after 30 days."""
    return svc.users().messages().trash(userId="me", id=message_id).execute()


def untrash_message(svc: GmailService, message_id: str) -> dict[str, Any]:
    """``messages.untrash``: removes TRASH; the other labels are kept."""
    return svc.users().messages().untrash(userId="me", id=message_id).execute()


def trash_thread(svc: GmailService, thread_id: str) -> dict[str, Any]:
    """``threads.trash``: every message in the thread goes to Trash."""
    return svc.users().threads().trash(userId="me", id=thread_id).execute()


def untrash_thread(svc: GmailService, thread_id: str) -> dict[str, Any]:
    """``threads.untrash``: every message in the thread leaves Trash."""
    return svc.users().threads().untrash(userId="me", id=thread_id).execute()


def batch_delete(svc: GmailService, message_ids: list[str]) -> int:
    """``messages.batchDelete`` in chunks of 1000: permanent, no Trash step."""
    for chunk in chunked(message_ids, BATCH_LIMIT):
        svc.users().messages().batchDelete(userId="me", body={"ids": chunk}).execute()
    return len(message_ids)


def rfc822_upload(data: bytes) -> MediaIoBaseUpload:
    """An RFC 822 message as the media body of send or draft calls.
    Resumable: the upload protocol Gmail documents for messages up to
    35 MB (no retries are attempted; a failure surfaces to the user)."""
    return MediaIoBaseUpload(
        io.BytesIO(data), mimetype="message/rfc822", resumable=True
    )


def send_message(svc: GmailService, data: bytes, thread_id: str = "") -> dict[str, Any]:
    """``messages.send`` of an RFC 822 message; ``thread_id`` files it in an
    existing conversation (the headers must reference it too)."""
    kwargs: dict[str, Any] = {"userId": "me", "media_body": rfc822_upload(data)}
    if thread_id:
        kwargs["body"] = {"threadId": thread_id}
    return svc.users().messages().send(**kwargs).execute()


def _draft_kwargs(data: bytes, thread_id: str) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"userId": "me", "media_body": rfc822_upload(data)}
    if thread_id:
        kwargs["body"] = {"message": {"threadId": thread_id}}
    return kwargs


def create_draft(svc: GmailService, data: bytes, thread_id: str = "") -> dict[str, Any]:
    kwargs = _draft_kwargs(data, thread_id)
    return svc.users().drafts().create(**kwargs).execute()


def list_drafts(
    svc: GmailService, query: str, max_results: int, page_token: str = ""
) -> dict[str, Any]:
    """One page of ``drafts.list``: ``drafts`` (ids plus message id and
    thread id) and ``nextPageToken``."""
    kwargs: dict[str, Any] = {
        "userId": "me",
        "maxResults": min(max_results, LIST_PAGE_LIMIT),
    }
    if query:
        kwargs["q"] = query
    if page_token:
        kwargs["pageToken"] = page_token
    return svc.users().drafts().list(**kwargs).execute()


def get_draft(svc: GmailService, draft_id: str, fmt: str = "full") -> dict[str, Any]:
    """``drafts.get``: the draft id and its message in the given format."""
    return svc.users().drafts().get(userId="me", id=draft_id, format=fmt).execute()


def update_draft(
    svc: GmailService, draft_id: str, data: bytes, thread_id: str = ""
) -> dict[str, Any]:
    """``drafts.update``: replaces the draft's message entirely."""
    kwargs = _draft_kwargs(data, thread_id)
    return svc.users().drafts().update(id=draft_id, **kwargs).execute()


def delete_draft(svc: GmailService, draft_id: str) -> None:
    """``drafts.delete``: immediate and permanent, no Trash step."""
    svc.users().drafts().delete(userId="me", id=draft_id).execute()


def send_draft(svc: GmailService, draft_id: str) -> dict[str, Any]:
    """``drafts.send``: sends the draft as stored and removes it."""
    body = {"id": draft_id}
    return svc.users().drafts().send(userId="me", body=body).execute()


def list_filters(svc: GmailService) -> list[dict[str, Any]]:
    """``settings.filters.list``: every filter of the account."""
    return (
        svc.users().settings().filters().list(userId="me").execute().get("filter", [])
        or []
    )


def get_filter(svc: GmailService, filter_id: str) -> dict[str, Any]:
    return svc.users().settings().filters().get(userId="me", id=filter_id).execute()


def create_filter(svc: GmailService, body: dict[str, Any]) -> dict[str, Any]:
    return svc.users().settings().filters().create(userId="me", body=body).execute()


def delete_filter(svc: GmailService, filter_id: str) -> None:
    svc.users().settings().filters().delete(userId="me", id=filter_id).execute()


def get_vacation(svc: GmailService) -> dict[str, Any]:
    """``settings.getVacation``: the vacation responder resource."""
    return svc.users().settings().getVacation(userId="me").execute()


def update_vacation(svc: GmailService, body: dict[str, Any]) -> dict[str, Any]:
    """``settings.updateVacation``: replaces the whole resource (a PUT)."""
    return svc.users().settings().updateVacation(userId="me", body=body).execute()
