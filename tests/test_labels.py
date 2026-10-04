from __future__ import annotations

import pytest

from wx_gmail_mcp.errors import WxGmailError
from wx_gmail_mcp.labels import LabelMap

from .conftest import LABELS
from .fake_gmail import FakeGmail


def test_fetch_uses_labels_list() -> None:
    fake = FakeGmail({"users.labels.list": {"labels": LABELS}})
    labels = LabelMap.fetch(fake)
    assert labels.name("Label_1") == "wx-test"
    assert fake.calls_to("users.labels.list") == [{"userId": "me"}]


def test_resolve_accepts_ids_names_and_system_labels() -> None:
    labels = LabelMap(LABELS)
    assert labels.resolve("Label_2") == "Label_2"
    assert labels.resolve("wx-test/sub") == "Label_2"
    assert labels.resolve("WX-TEST") == "Label_1"
    assert labels.resolve(" inbox ") == "INBOX"
    assert labels.resolve("TRASH") == "TRASH"  # system label absent from the list


def test_resolve_rejects_unknown_and_empty() -> None:
    labels = LabelMap(LABELS)
    with pytest.raises(WxGmailError, match="Unknown label 'nope'"):
        labels.resolve("nope")
    with pytest.raises(WxGmailError, match="Empty label"):
        labels.resolve("  ")


def test_resolve_all_dedupes_and_names_round_trip() -> None:
    labels = LabelMap(LABELS)
    ids = labels.resolve_all(["wx-test", "Label_1", "STARRED"])
    assert ids == ["Label_1", "STARRED"]
    assert labels.names(["Label_1", "Label_x"]) == ["wx-test", "Label_x"]
