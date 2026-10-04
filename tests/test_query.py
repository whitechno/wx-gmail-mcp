from __future__ import annotations

from typing import Any

import pytest

from wx_gmail_mcp import query

# --- size_text ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        (10 * 1024 * 1024, "10M"),
        (1024 * 1024, "1M"),
        (512 * 1024, "512K"),
        (1024, "1K"),
        (1536, "1536"),  # 1.5K: not a whole number of either unit
        (10_000_000, "10000000"),
        (1, "1"),
        (0, "0"),
    ],
)
def test_size_text(size: int, expected: str) -> None:
    assert query.size_text(size) == expected


# --- criteria_to_query: one criterion at a time -------------------------------


@pytest.mark.parametrize(
    ("criteria", "expected"),
    [
        ({"from": "alice@example.com"}, "from:(alice@example.com)"),
        ({"to": "team@example.com"}, "to:(team@example.com)"),
        ({"subject": "weekly report"}, "subject:(weekly report)"),
        ({"query": "is:unread older_than:30d"}, "is:unread older_than:30d"),
        ({"negatedQuery": "urgent"}, "-{urgent}"),
        ({"negatedQuery": "urgent OR asap"}, "-{urgent OR asap}"),
        ({"hasAttachment": True}, "has:attachment"),
        ({"excludeChats": True}, "-in:chats"),
        ({"size": 10 * 1024 * 1024, "sizeComparison": "larger"}, "larger:10M"),
        ({"size": 512 * 1024, "sizeComparison": "smaller"}, "smaller:512K"),
        ({"size": 12345, "sizeComparison": "larger"}, "larger:12345"),
    ],
)
def test_single_criterion(criteria: dict[str, Any], expected: str) -> None:
    assert query.criteria_to_query(criteria) == expected


def test_header_values_keep_or_and_quotes_inside_the_group() -> None:
    criteria = {
        "from": "alice@example.com OR bob@example.com",
        "subject": '"exact phrase"',
    }
    assert query.criteria_to_query(criteria) == (
        'from:(alice@example.com OR bob@example.com) subject:("exact phrase")'
    )


def test_header_values_are_stripped() -> None:
    assert query.criteria_to_query({"from": "  a@example.com  "}) == (
        "from:(a@example.com)"
    )
    assert query.criteria_to_query({"query": "  is:starred  "}) == "is:starred"


# --- combinations, order and omissions --------------------------------------


def test_every_criterion_in_web_ui_order() -> None:
    criteria = {
        "from": "news@example.com",
        "to": "me@example.com",
        "subject": "digest",
        "query": "has:userlabels",
        "negatedQuery": "unsubscribe",
        "hasAttachment": True,
        "excludeChats": True,
        "size": 2 * 1024 * 1024,
        "sizeComparison": "smaller",
    }
    assert query.criteria_to_query(criteria) == (
        "from:(news@example.com) to:(me@example.com) subject:(digest) "
        "has:userlabels -{unsubscribe} has:attachment -in:chats smaller:2M"
    )


@pytest.mark.parametrize(
    "criteria",
    [
        {},
        {"from": "", "to": "   ", "subject": None},
        {"query": "", "negatedQuery": ""},
        {"hasAttachment": False, "excludeChats": False},
        {"size": 0, "sizeComparison": "larger"},
        {"size": 1024},  # no comparison
        {"size": 1024, "sizeComparison": "unspecified"},
        {"size": 1024, "sizeComparison": ""},
        {"size": "1024", "sizeComparison": "larger"},  # not an int
        {"size": -5, "sizeComparison": "larger"},
    ],
)
def test_empty_or_unusable_criteria_give_an_empty_query(
    criteria: dict[str, Any],
) -> None:
    assert query.criteria_to_query(criteria) == ""


def test_false_flags_add_nothing_next_to_real_criteria() -> None:
    criteria = {"from": "a@example.com", "hasAttachment": False, "excludeChats": False}
    assert query.criteria_to_query(criteria) == "from:(a@example.com)"


def test_unknown_keys_are_ignored() -> None:
    criteria = {"from": "a@example.com", "forward": "x@example.com", "id": "f1"}
    assert query.criteria_to_query(criteria) == "from:(a@example.com)"


def test_size_clause_alone() -> None:
    assert query.size_clause({"size": 3 * 1024, "sizeComparison": "larger"}) == (
        "larger:3K"
    )
    assert query.size_clause({"size": 3 * 1024}) == ""
    assert query.size_clause({}) == ""


def test_negated_query_keeps_inner_braces_as_given() -> None:
    # The web UI wraps "Doesn't have" in -{...} whatever the user typed.
    assert query.criteria_to_query({"negatedQuery": "{a b}"}) == "-{{a b}}"
