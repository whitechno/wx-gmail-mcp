from __future__ import annotations

from typing import Any

from wx_gmail_mcp.config import Settings

from .conftest import LABELS, call, message, tool_server
from .fake_gmail import FakeGmail


def _fake(**responses: Any) -> FakeGmail:
    base: dict[str, Any] = {"users.labels.list": {"labels": LABELS}}
    base.update(responses)
    return FakeGmail(base)


def test_get_profile(settings: Settings) -> None:
    fake = _fake(
        **{
            "users.getProfile": {
                "emailAddress": "you@example.com",
                "messagesTotal": 1234,
                "threadsTotal": 567,
                "historyId": "98765",
            }
        }
    )
    text = call(tool_server(settings, fake), "get_profile", account="work")
    assert text == (
        "Email: you@example.com\nMessages: 1234\nThreads: 567\nHistory id: 98765"
    )
    assert fake.calls_to("users.getProfile") == [{"userId": "me"}]


def test_search_threads_formats_last_message_and_label_union(
    settings: Settings,
) -> None:
    t1 = {
        "id": "t1",
        "messages": [
            message("m1", "t1", ("INBOX", "Label_1")),
            message(
                "m2",
                "t1",
                ("Label_1", "UNREAD"),
                headers={
                    "From": "Reply <reply@example.com>",
                    "Subject": "Re: Test subject",
                    "Date": "Sat, 03 Oct 2026 09:00:00 +0000",
                },
            ),
        ],
    }
    t2 = {"id": "t2", "messages": [message("m3", "t2", ())]}
    fake = _fake(
        **{
            "users.threads.list": {
                "threads": [
                    {"id": "t1", "snippet": "Don&#39;t forget"},
                    {"id": "t2", "snippet": "solo"},
                ],
                "nextPageToken": "tok-9",
            },
            "users.threads.get": [t1, t2],
        }
    )
    text = call(
        tool_server(settings, fake),
        "search_threads",
        account="work",
        query="is:unread",
        max_results=2,
    )
    first, second, token = text.split("\n\n")
    assert first == (
        "[thread t1] 2 messages | last Sat, 03 Oct 2026 09:00:00 +0000\n"
        "  From: Reply <reply@example.com>\n"
        "  Subj: Re: Test subject\n"
        "  Labels: INBOX, wx-test, UNREAD\n"
        "  Don't forget"
    )
    assert second.startswith("[thread t2] 1 message | last Fri, 02 Oct 2026")
    assert "  Labels: (none)\n  solo" in second
    assert token == "next_page_token: tok-9"
    (list_call,) = fake.calls_to("users.threads.list")
    assert list_call == {
        "userId": "me",
        "q": "is:unread",
        "maxResults": 2,
        "includeSpamTrash": False,
    }
    assert fake.calls_to("users.threads.get")[0] == {
        "userId": "me",
        "id": "t1",
        "format": "metadata",
        "metadataHeaders": ["From", "Subject", "Date"],
    }


def test_search_threads_empty_and_params(settings: Settings) -> None:
    fake = _fake(**{"users.threads.list": {}})
    text = call(
        tool_server(settings, fake),
        "search_threads",
        account="work",
        query="x",
        page_token="tok",
        include_spam_trash=True,
    )
    assert text == "No threads matched."
    (list_call,) = fake.calls_to("users.threads.list")
    assert list_call["pageToken"] == "tok"
    assert list_call["includeSpamTrash"] is True
    assert fake.calls_to("users.labels.list") == []
    assert call(
        tool_server(settings, fake),
        "search_threads",
        account="work",
        query="x",
        max_results=101,
    ) == ("Error: max_results must be between 1 and 100.")
