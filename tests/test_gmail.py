from __future__ import annotations

from typing import Any

import pytest
from google.oauth2.credentials import Credentials

from wx_gmail_mcp import gmail
from wx_gmail_mcp.config import Settings

from .conftest import write_token
from .fake_gmail import FakeGmail


def test_header_lookup_is_case_insensitive() -> None:
    payload = {"headers": [{"name": "Subject", "value": "Hi"}]}
    assert gmail.header(payload, "subject") == "Hi"
    assert gmail.header(payload, "From") == ""
    assert gmail.header({}, "From") == ""


def test_list_messages_arguments() -> None:
    fake = FakeGmail({"users.messages.list": {"messages": []}})
    gmail.list_messages(fake, "is:unread", 2000)
    gmail.list_messages(fake, "x", 5, page_token="p2", include_spam_trash=True)
    first, second = fake.calls_to("users.messages.list")
    assert first == {
        "userId": "me",
        "q": "is:unread",
        "maxResults": 500,
        "includeSpamTrash": False,
    }
    assert second["pageToken"] == "p2"
    assert second["includeSpamTrash"] is True
    assert second["maxResults"] == 5


def test_iter_message_ids_paginates_and_stops_at_limit() -> None:
    pages = [
        {"messages": [{"id": "1"}, {"id": "2"}], "nextPageToken": "t1"},
        {"messages": [{"id": "3"}, {"id": "4"}], "nextPageToken": "t2"},
        {"messages": [{"id": "5"}]},
    ]
    fake = FakeGmail({"users.messages.list": list(pages)})
    assert list(gmail.iter_message_ids(fake, "q", limit=3)) == ["1", "2", "3"]
    assert len(fake.calls_to("users.messages.list")) == 2

    fake = FakeGmail({"users.messages.list": list(pages)})
    assert list(gmail.iter_message_ids(fake, "q", limit=100)) == [
        "1",
        "2",
        "3",
        "4",
        "5",
    ]
    calls = fake.calls_to("users.messages.list")
    assert [c.get("pageToken") for c in calls] == [None, "t1", "t2"]


def test_batch_modify_chunks_of_1000() -> None:
    fake = FakeGmail()
    ids = [str(i) for i in range(2500)]
    assert gmail.batch_modify(fake, ids, ["STARRED"], ["INBOX"]) == 2500
    calls = fake.calls_to("users.messages.batchModify")
    assert [len(c["body"]["ids"]) for c in calls] == [1000, 1000, 500]
    assert calls[0]["body"]["addLabelIds"] == ["STARRED"]
    assert calls[0]["body"]["removeLabelIds"] == ["INBOX"]
    assert calls[2]["body"]["ids"][-1] == "2499"


def test_batch_delete_chunks_of_1000() -> None:
    fake = FakeGmail()
    ids = [str(i) for i in range(1200)]
    assert gmail.batch_delete(fake, ids) == 1200
    calls = fake.calls_to("users.messages.batchDelete")
    assert [len(c["body"]["ids"]) for c in calls] == [1000, 200]
    assert set(calls[0]["body"]) == {"ids"}
    assert calls[1]["body"]["ids"][-1] == "1199"


def test_batch_modify_with_no_ids_makes_no_call() -> None:
    fake = FakeGmail()
    assert gmail.batch_modify(fake, [], [], []) == 0
    assert fake.calls == []


def test_single_calls_pass_expected_arguments() -> None:
    fake = FakeGmail(
        {
            "users.labels.list": {"labels": [{"id": "L1", "name": "x"}]},
            "users.getProfile": {"emailAddress": "you@example.com"},
        }
    )
    gmail.modify_message(fake, "m1", ["A"], ["B"])
    gmail.get_message(fake, "m1", "metadata", ["From"])
    gmail.get_thread(fake, "t1")
    gmail.get_label(fake, "L1")
    assert gmail.list_labels(fake) == [{"id": "L1", "name": "x"}]
    assert gmail.get_profile(fake)["emailAddress"] == "you@example.com"
    assert fake.calls_to("users.messages.modify") == [
        {
            "userId": "me",
            "id": "m1",
            "body": {"addLabelIds": ["A"], "removeLabelIds": ["B"]},
        }
    ]
    assert fake.calls_to("users.messages.get") == [
        {"userId": "me", "id": "m1", "format": "metadata", "metadataHeaders": ["From"]}
    ]
    assert fake.calls_to("users.threads.get") == [
        {"userId": "me", "id": "t1", "format": "full"}
    ]
    assert fake.calls_to("users.labels.get") == [{"userId": "me", "id": "L1"}]


def test_runtime_builds_service_from_stored_token(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_token(settings, "work")
    built: list[Any] = []

    def fake_build(creds: Credentials) -> str:
        built.append(creds)
        return "service"

    monkeypatch.setattr(gmail, "build_service", fake_build)
    rt = gmail.Runtime(settings)
    assert rt.service("work") == "service"
    assert isinstance(built[0], Credentials)


def test_outgoing_messages_go_up_as_rfc822_media() -> None:
    fake = FakeGmail()
    data = b"To: a@example.com\r\nSubject: s\r\n\r\nbody\r\n"
    gmail.send_message(fake, data)
    gmail.send_message(fake, data, "t1")
    gmail.create_draft(fake, data)
    gmail.create_draft(fake, data, "t2")
    gmail.update_draft(fake, "d1", data, "t3")
    plain, threaded = fake.calls_to("users.messages.send")
    assert "body" not in plain  # the upload is the whole request
    assert threaded["body"] == {"threadId": "t1"}
    for kw in (plain, threaded):
        assert kw["userId"] == "me"
        assert "raw" not in kw.get("body", {})
        media = kw["media_body"]
        assert media.mimetype() == "message/rfc822"
        assert media.resumable()
        assert media.getbytes(0, media.size()) == data
    created, created_in_thread = fake.calls_to("users.drafts.create")
    assert "body" not in created
    assert created_in_thread["body"] == {"message": {"threadId": "t2"}}
    (updated,) = fake.calls_to("users.drafts.update")
    assert updated["id"] == "d1"
    assert updated["body"] == {"message": {"threadId": "t3"}}
    assert updated["media_body"].getbytes(0, len(data)) == data
