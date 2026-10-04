"""Unit tests for FilterRequest / plan_filter: no server, no fake service."""

from __future__ import annotations

import pytest

from wx_gmail_mcp import filters
from wx_gmail_mcp.errors import WxGmailError
from wx_gmail_mcp.filters import FilterRequest
from wx_gmail_mcp.labels import LabelMap

from .conftest import LABELS

LM = LabelMap(LABELS)


def test_criteria_keeps_only_what_was_given() -> None:
    req = FilterRequest(from_="  a@example.com ", query="is:unread")
    assert req.criteria() == {"from": "a@example.com", "query": "is:unread"}
    req = FilterRequest(has_attachment=True, exclude_chats=True)
    assert req.criteria() == {"hasAttachment": True, "excludeChats": True}


def test_criteria_size() -> None:
    req = FilterRequest(size=2048, size_comparison=" Smaller ")
    assert req.criteria() == {"size": 2048, "sizeComparison": "smaller"}
    assert FilterRequest(subject="x", size=0).criteria() == {"subject": "x"}
    with pytest.raises(WxGmailError, match="size_comparison must be one of"):
        FilterRequest(size=1, size_comparison="bigger").criteria()
    with pytest.raises(WxGmailError, match="size must be a number of bytes"):
        FilterRequest(size=-1).criteria()


def test_criteria_requires_one() -> None:
    with pytest.raises(WxGmailError, match="Give at least one criterion"):
        FilterRequest(from_="  ", subject="").criteria()


def test_shortcut_changes() -> None:
    req = FilterRequest(
        skip_inbox=True,
        mark_read=True,
        star=True,
        always_important=True,
        never_spam=True,
        category=" Promotions ",
        delete=True,
    )
    assert req.shortcut_changes() == (
        ["STARRED", "IMPORTANT", "CATEGORY_PROMOTIONS", "TRASH"],
        ["INBOX", "UNREAD", "SPAM"],
    )
    assert FilterRequest(never_important=True).shortcut_changes() == (
        [],
        ["IMPORTANT"],
    )
    assert FilterRequest().shortcut_changes() == ([], [])
    with pytest.raises(WxGmailError, match="exclude each other"):
        FilterRequest(always_important=True, never_important=True).shortcut_changes()
    with pytest.raises(WxGmailError, match="category must be one of: personal"):
        FilterRequest(category="spam").shortcut_changes()


def test_plan_filter_resolves_names_and_dedupes() -> None:
    req = FilterRequest(
        from_="a@example.com",
        add_labels=["wx-test", "Label_1", "starred"],
        remove_labels=["inbox"],
        star=True,
        skip_inbox=True,
    )
    spec = filters.plan_filter(req, LM, False)
    assert (spec.add, spec.remove, spec.missing) == (
        ["Label_1", "STARRED"],
        ["INBOX"],
        [],
    )
    assert spec.body() == {
        "criteria": {"from": "a@example.com"},
        "action": {"addLabelIds": ["Label_1", "STARRED"], "removeLabelIds": ["INBOX"]},
    }
    assert spec.search() == "from:(a@example.com)"


def test_plan_filter_missing_labels() -> None:
    req = FilterRequest(from_="a@example.com", add_labels=["wx-test/new", "wx-test"])
    with pytest.raises(WxGmailError, match="Unknown label 'wx-test/new'"):
        filters.plan_filter(req, LM, False)
    spec = filters.plan_filter(req, LM, True)
    assert (spec.add, spec.missing) == (["Label_1"], ["wx-test/new"])
    # A bad name is refused even when creating is allowed.
    req = FilterRequest(from_="a@example.com", add_labels=["a//b"])
    with pytest.raises(WxGmailError, match="empty segment"):
        filters.plan_filter(req, LM, True)
    with pytest.raises(WxGmailError, match="Empty label name"):
        filters.plan_filter(FilterRequest(from_="a", add_labels=[" "]), LM, True)
    # Removing a label that does not exist is always an error.
    req = FilterRequest(from_="a@example.com", remove_labels=["nope"])
    with pytest.raises(WxGmailError, match="Unknown label 'nope'"):
        filters.plan_filter(req, LM, True)


def test_plan_filter_refusals() -> None:
    f = "a@example.com"
    with pytest.raises(WxGmailError, match="cannot add TRASH: pass delete=true"):
        filters.plan_filter(FilterRequest(from_=f, add_labels=["trash"]), LM, False)
    with pytest.raises(WxGmailError, match="cannot add SPAM: Gmail filters cannot"):
        filters.plan_filter(FilterRequest(from_=f, add_labels=["SPAM"]), LM, False)
    with pytest.raises(WxGmailError, match="INBOX cannot be both added and removed"):
        filters.plan_filter(
            FilterRequest(from_=f, add_labels=["INBOX"], skip_inbox=True), LM, False
        )
    with pytest.raises(WxGmailError, match="Give at least one action"):
        filters.plan_filter(FilterRequest(from_=f), LM, False)
    # Criteria are checked before actions.
    with pytest.raises(WxGmailError, match="Give at least one criterion"):
        filters.plan_filter(FilterRequest(star=True), LM, False)
