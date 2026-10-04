from __future__ import annotations

from typing import Any

import httplib2
import pytest
from googleapiclient.errors import HttpError

from wx_gmail_mcp import bulk
from wx_gmail_mcp.errors import WxGmailError

from .conftest import message
from .fake_gmail import FakeGmail


def paged_list(ids: list[str], page_size: int = 500) -> Any:
    """A ``messages.list`` fake that pages through ``ids`` by pageToken."""

    def respond(**kwargs: Any) -> dict[str, Any]:
        start = int(kwargs.get("pageToken") or 0)
        size = min(int(kwargs["maxResults"]), page_size)
        page = ids[start : start + size]
        out: dict[str, Any] = {"messages": [{"id": i} for i in page]}
        if start + size < len(ids):
            out["nextPageToken"] = str(start + size)
        return out

    return respond


def get_by_id(**kwargs: Any) -> dict[str, Any]:
    return message(kwargs["id"], headers={"Subject": f"subj {kwargs['id']}"})


def _fake(ids: list[str], **responses: Any) -> FakeGmail:
    base: dict[str, Any] = {
        "users.messages.list": paged_list(ids),
        "users.messages.get": get_by_id,
    }
    base.update(responses)
    return FakeGmail(base)


def test_dry_run_counts_samples_and_writes_nothing() -> None:
    ids = [f"m{i}" for i in range(7)]
    fake = _fake(ids)
    report = bulk.relabel_by_query(fake, " is:unread ", ["Label_1"], ["INBOX"])
    assert (report.query, report.matched, report.modified, report.dry_run) == (
        "is:unread",
        7,
        0,
        True,
    )
    assert report.error == ""
    assert len(report.sample) == 5
    assert report.sample[0] == (
        "[m0] Fri, 02 Oct 2026 10:00:00 +0000 | Sender <sender@example.com> | subj m0"
    )
    assert fake.calls_to("users.messages.batchModify") == []
    assert [c["id"] for c in fake.calls_to("users.messages.get")] == ids[:5]
    (list_call,) = fake.calls_to("users.messages.list")
    assert list_call["q"] == "is:unread"
    assert list_call["includeSpamTrash"] is False
    assert list_call["maxResults"] == 500


def test_apply_pages_and_chunks_by_1000() -> None:
    ids = [f"m{i}" for i in range(1500)]
    fake = _fake(ids)
    report = bulk.relabel_by_query(
        fake, "older_than:1y", ["Label_1"], [], limit=2000, dry_run=False
    )
    assert (report.matched, report.modified, report.dry_run) == (1500, 1500, False)
    # 2001 ids requested: three pages of 500, the last with no next token.
    assert len(fake.calls_to("users.messages.list")) == 3
    bodies = [c["body"] for c in fake.calls_to("users.messages.batchModify")]
    assert [len(b["ids"]) for b in bodies] == [1000, 500]
    assert bodies[0]["ids"][:2] == ["m0", "m1"]
    assert bodies[1]["ids"][-1] == "m1499"
    assert bodies[0]["addLabelIds"] == ["Label_1"]
    assert bodies[0]["removeLabelIds"] == []


def test_more_matches_than_limit_is_an_error_before_any_write() -> None:
    fake = _fake([f"m{i}" for i in range(11)])
    with pytest.raises(WxGmailError, match="More than 10 messages match 'x'"):
        bulk.relabel_by_query(fake, "x", ["Label_1"], [], limit=10, dry_run=False)
    assert fake.calls_to("users.messages.batchModify") == []
    assert fake.calls_to("users.messages.get") == []
    # Exactly the limit is fine.
    fake = _fake([f"m{i}" for i in range(10)])
    report = bulk.relabel_by_query(fake, "x", ["Label_1"], [], limit=10, dry_run=False)
    assert report.modified == 10


def test_no_matches() -> None:
    fake = _fake([])
    report = bulk.relabel_by_query(fake, "x", ["Label_1"], [], dry_run=False)
    assert (report.matched, report.modified, report.sample) == (0, 0, [])
    assert fake.calls_to("users.messages.batchModify") == []
    assert report.text("added a") == "No messages match 'x'. Nothing to do."


def test_partial_failure_reports_count_done() -> None:
    calls = 0

    def flaky(**kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise HttpError(
                httplib2.Response({"status": 500}), b'{"error": {"message": "boom"}}'
            )
        return {}

    fake = _fake(
        [f"m{i}" for i in range(2500)], **{"users.messages.batchModify": flaky}
    )
    report = bulk.relabel_by_query(
        fake, "x", ["Label_1"], [], limit=5000, dry_run=False
    )
    assert (report.matched, report.modified) == (2500, 1000)
    assert report.error == "HTTP 500: boom"
    text = report.text("added wx-test")
    assert text.startswith(
        "Modified 1000 of 2500 messages matching 'x' before an error: HTTP 500: boom"
    )
    assert text.endswith(
        "Run again to finish; messages already modified are unaffected."
    )


def test_partial_failure_of_any_kind_keeps_the_count() -> None:
    calls = 0

    def flaky(**kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise TimeoutError("timed out")
        return {}

    fake = _fake(
        [f"m{i}" for i in range(2500)], **{"users.messages.batchModify": flaky}
    )
    report = bulk.relabel_by_query(
        fake, "x", ["Label_1"], [], limit=5000, dry_run=False
    )
    assert (report.matched, report.modified) == (2500, 2000)
    assert report.error == "TimeoutError: timed out"


def test_validation() -> None:
    fake = _fake([])
    with pytest.raises(WxGmailError, match="query is required"):
        bulk.relabel_by_query(fake, "  ", ["Label_1"], [])
    with pytest.raises(WxGmailError, match="limit must be between 1 and 100000"):
        bulk.relabel_by_query(fake, "x", ["Label_1"], [], limit=0)
    with pytest.raises(WxGmailError, match="limit must be between"):
        bulk.relabel_by_query(fake, "x", ["Label_1"], [], limit=100_001)
    assert fake.calls == []


def test_report_text_forms() -> None:
    dry = bulk.RelabelReport("q", 1, 0, True, ["[m1] d | f | s"])
    assert dry.text("added A; removed B") == (
        "Dry run: 1 message match 'q'. Would have added A; removed B.\n"
        "Sample:\n"
        "  [m1] d | f | s\n"
        "Run again with dry_run=false to apply."
    )
    done = bulk.RelabelReport("q", 3, 3, False, ["a", "b"])
    assert done.text("added A") == (
        "Modified 3 messages matching 'q': added A.\nSample:\n  a\n  b"
    )
