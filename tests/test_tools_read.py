from __future__ import annotations

from typing import Any

from wx_gmail_mcp.config import Settings

from .conftest import LABELS, b64, call, message, tool_server
from .fake_gmail import FakeGmail


def _fake(**responses: Any) -> FakeGmail:
    base: dict[str, Any] = {"users.labels.list": {"labels": LABELS}}
    base.update(responses)
    return FakeGmail(base)


def test_search_formats_hits_with_thread_and_labels(settings: Settings) -> None:
    fake = _fake(
        **{
            "users.messages.list": {
                "messages": [{"id": "m1"}, {"id": "m2"}],
                "nextPageToken": "tok-2",
            },
            "users.messages.get": [
                message("m1", "t1", ("INBOX", "Label_1")),
                message("m2", "t2", (), headers={"Subject": "Second"}),
            ],
        }
    )
    text = call(
        tool_server(settings, fake), "search", account="work", query="is:unread"
    )
    assert "[m1] Fri, 02 Oct 2026 10:00:00 +0000 | thread t1" in text
    assert "  Labels: INBOX, wx-test" in text
    assert "  From: Sender <sender@example.com>" in text
    assert "  Subj: Second" in text
    assert "  Labels: (none)" in text
    assert text.endswith("next_page_token: tok-2")
    (list_call,) = fake.calls_to("users.messages.list")
    assert list_call["q"] == "is:unread"
    assert list_call["maxResults"] == 10
    assert list_call["includeSpamTrash"] is False
    assert "pageToken" not in list_call
    assert fake.calls_to("users.messages.get")[0]["format"] == "metadata"
    assert fake.calls_to("users.messages.get")[0]["metadataHeaders"] == [
        "From",
        "Subject",
        "Date",
    ]


def test_search_unescapes_html_entities_in_snippets(settings: Settings) -> None:
    fake = _fake(
        **{
            "users.messages.list": {"messages": [{"id": "m1"}]},
            "users.messages.get": message(snippet="Don&#39;t stop &amp; go &lt;3"),
        }
    )
    text = call(tool_server(settings, fake), "search", account="work", query="x")
    assert text.endswith("  Don't stop & go <3")


def test_search_passes_page_token_and_spam_trash(settings: Settings) -> None:
    fake = _fake(**{"users.messages.list": {"messages": []}})
    text = call(
        tool_server(settings, fake),
        "search",
        account="work",
        query="x",
        max_results=50,
        page_token="tok",
        include_spam_trash=True,
    )
    assert text == "No messages matched."
    (list_call,) = fake.calls_to("users.messages.list")
    assert list_call["pageToken"] == "tok"
    assert list_call["includeSpamTrash"] is True
    assert list_call["maxResults"] == 50
    assert fake.calls_to("users.labels.list") == []


def test_search_validates_max_results(settings: Settings) -> None:
    fake = _fake()
    text = call(
        tool_server(settings, fake), "search", account="work", query="x", max_results=0
    )
    assert text.startswith("Error: max_results must be between 1 and 100")
    assert fake.calls == []


def test_unknown_account_is_a_readable_error(settings: Settings) -> None:
    text = call(tool_server(settings, _fake()), "search", account="nope", query="x")
    assert text == "Error: No token for account 'nope'. Known accounts: work"


def test_read_message_full_output(settings: Settings) -> None:
    parts = [
        {"mimeType": "text/plain", "body": {"data": b64("Body text")}},
        {
            "mimeType": "application/pdf",
            "filename": "a.pdf",
            "body": {"attachmentId": "att-1", "size": 10},
        },
    ]
    msg = message(
        "m1", "t9", ("INBOX", "Label_2"), headers={"Cc": "cc@example.com"}, parts=parts
    )
    fake = _fake(**{"users.messages.get": msg})
    text = call(
        tool_server(settings, fake), "read_message", account="work", message_id="m1"
    )
    assert text == (
        "Message id: m1\n"
        "Thread id: t9\n"
        "Date: Fri, 02 Oct 2026 10:00:00 +0000\n"
        "From: Sender <sender@example.com>\n"
        "To: you@example.com\n"
        "Cc: cc@example.com\n"
        "Subject: Test subject\n"
        "Labels: INBOX, wx-test/sub\n"
        "Attachments:\n"
        "  - a.pdf (application/pdf, 10 bytes) id=att-1\n"
        "\n"
        "Body text"
    )
    assert fake.calls_to("users.messages.get") == [
        {"userId": "me", "id": "m1", "format": "full"}
    ]


def test_read_message_without_cc_or_attachments_and_truncation(
    settings: Settings,
) -> None:
    s = Settings(home=settings.home, gates=settings.gates, max_body=5)
    fake = _fake(**{"users.messages.get": message(body="0123456789")})
    text = call(tool_server(s, fake), "read_message", account="work", message_id="m1")
    assert "Cc:" not in text
    assert "Attachments:" not in text
    assert text.endswith("\n\n01234\n...[truncated]")


def test_read_thread_lists_messages_oldest_first(settings: Settings) -> None:
    thread = {
        "messages": [
            message("m1", "t1", ("Label_1",), body="first"),
            message(
                "m2", "t1", ("INBOX",), headers={"From": "b@example.com"}, body="second"
            ),
        ]
    }
    fake = _fake(**{"users.threads.get": thread})
    text = call(
        tool_server(settings, fake), "read_thread", account="work", thread_id="t1"
    )
    first, second = text.split("\n\n")
    assert first == (
        "--- [m1] Fri, 02 Oct 2026 10:00:00 +0000 | Sender <sender@example.com>\n"
        "Subject: Test subject\n"
        "Labels: wx-test\n"
        "first"
    )
    assert second.startswith("--- [m2] ")
    assert second.endswith("Labels: INBOX\nsecond")
    assert fake.calls_to("users.threads.get") == [
        {"userId": "me", "id": "t1", "format": "full"}
    ]


def test_read_thread_max_body_and_empty(settings: Settings) -> None:
    thread = {"messages": [message(body="abcdefghij")]}
    fake = _fake(**{"users.threads.get": thread})
    text = call(
        tool_server(settings, fake),
        "read_thread",
        account="work",
        thread_id="t1",
        max_body=3,
    )
    assert text.endswith("\nabc\n...[truncated]")
    fake = _fake(**{"users.threads.get": {}})
    assert call(
        tool_server(settings, fake), "read_thread", account="work", thread_id="t1"
    ) == ("Empty thread.")


def test_api_errors_come_back_as_text(settings: Settings) -> None:
    import httplib2
    from googleapiclient.errors import HttpError

    def boom(**kwargs: Any) -> dict[str, Any]:
        raise HttpError(
            httplib2.Response({"status": 404}), b'{"error": {"message": "gone"}}'
        )

    fake = _fake(**{"users.messages.get": boom})
    text = call(
        tool_server(settings, fake), "read_message", account="work", message_id="x"
    )
    assert text == "Gmail API error: HTTP 404: gone"
