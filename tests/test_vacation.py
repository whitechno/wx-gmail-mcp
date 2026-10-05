from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from wx_gmail_mcp import vacation
from wx_gmail_mcp.errors import WxGmailError

PARIS = ZoneInfo("Europe/Paris")
# 2026-10-05 00:00 in Paris (CEST, UTC+2) and 2026-11-05 00:00 (CET, UTC+1).
OCT_5 = str(int(datetime(2026, 10, 4, 22, 0, tzinfo=UTC).timestamp() * 1000))
NOV_5 = str(int(datetime(2026, 11, 4, 23, 0, tzinfo=UTC).timestamp() * 1000))


def test_resolve_zone() -> None:
    assert vacation.resolve_zone("") is None
    assert vacation.resolve_zone("  ") is None
    assert vacation.resolve_zone(" Europe/Paris ") == PARIS
    with pytest.raises(WxGmailError, match="not a known IANA zone"):
        vacation.resolve_zone("Mars/Olympus")
    with pytest.raises(WxGmailError, match="not a known IANA zone"):
        vacation.resolve_zone("../etc/passwd")


def test_parse_date() -> None:
    assert vacation.parse_date(" 2026-10-05 ", "start_date") == date(2026, 10, 5)
    with pytest.raises(WxGmailError, match=r"start_date: 'Oct 5' is not a date"):
        vacation.parse_date("Oct 5", "start_date")
    with pytest.raises(WxGmailError, match="end_date"):
        vacation.parse_date("2026-13-01", "end_date")


def test_start_of_day_is_dst_aware() -> None:
    assert vacation.start_of_day(date(2026, 10, 5), PARIS).utcoffset() == timedelta(
        hours=2
    )
    assert vacation.start_of_day(date(2026, 11, 5), PARIS).utcoffset() == timedelta(
        hours=1
    )
    local = vacation.start_of_day(date(2026, 10, 5), None)
    assert local == datetime.combine(date(2026, 10, 5), time.min).astimezone()
    assert local.tzinfo is not None


def test_period_in_a_named_zone() -> None:
    # The last day is inclusive: the end instant is the next midnight.
    assert vacation.period("2026-10-05", "2026-11-04", PARIS) == {
        "startTime": OCT_5,
        "endTime": NOV_5,
    }
    assert vacation.period("2026-10-05", "", PARIS) == {"startTime": OCT_5}
    assert vacation.period("", "2026-11-04", PARIS) == {"endTime": NOV_5}
    assert vacation.period("", "  ", PARIS) == {}
    # A one-day period is a day long.
    one = vacation.period("2026-10-05", "2026-10-05", PARIS)
    assert int(one["endTime"]) - int(one["startTime"]) == 24 * 3600 * 1000


def test_period_rejects_a_reversed_range() -> None:
    with pytest.raises(WxGmailError, match="end_date 2026-10-04 is before"):
        vacation.period("2026-10-05", "2026-10-04", PARIS)


def test_from_millis() -> None:
    assert vacation.from_millis(None, PARIS) is None
    assert vacation.from_millis("", PARIS) is None
    assert vacation.from_millis("0", PARIS) is None
    assert vacation.from_millis("abc", PARIS) is None
    moment = vacation.from_millis(OCT_5, PARIS)
    assert moment == datetime(2026, 10, 5, 0, 0, tzinfo=PARIS)
    assert vacation.from_millis(int(OCT_5), PARIS) == moment
    # Gmail sometimes rounds the instant off; the time then shows.
    later = vacation.from_millis(str(int(OCT_5) + 90_000), PARIS)
    assert later is not None and later.time() == time(0, 1, 30)
    # Without a zone the machine's local zone is attached.
    local = vacation.from_millis(OCT_5, None)
    assert local is not None and local.utcoffset() is not None
    assert local == moment


def test_text_full() -> None:
    settings = {
        "enableAutoReply": True,
        "responseSubject": "Away",
        "responseBodyPlainText": "Back on the 5th.\nThanks,\nMe",
        "responseBodyHtml": "<p>Back on the 5th.</p>",
        "restrictToContacts": True,
        "restrictToDomain": True,
        "startTime": OCT_5,
        "endTime": NOV_5,
    }
    assert vacation.text(settings, PARIS, "Europe/Paris") == (
        "Vacation responder: on\n"
        "  subject: Away\n"
        "  body: Back on the 5th.\n"
        "        Thanks,\n"
        "        Me\n"
        "  html: <p>Back on the 5th.</p>\n"
        "  first day: 2026-10-05\n"
        "  last day: 2026-11-04\n"
        "  time zone: Europe/Paris\n"
        "  only to: contacts, same domain"
    )


def test_text_minimal_and_odd_instants() -> None:
    assert vacation.text({}, PARIS) == "Vacation responder: off (nothing saved)"
    assert vacation.text({"enableAutoReply": False, "startTime": "0"}, PARIS) == (
        "Vacation responder: off (nothing saved)"
    )
    # An instant off midnight shows its time; the zone falls back to the
    # abbreviation when no name was given.
    settings = {
        "enableAutoReply": True,
        "responseBodyPlainText": "x",
        "startTime": str(int(OCT_5) + 9 * 3600 * 1000 + 30 * 60 * 1000),
        "endTime": str(int(NOV_5) + 3600 * 1000),
    }
    assert vacation.text(settings, PARIS) == (
        "Vacation responder: on\n"
        "  body: x\n"
        "  starts: 2026-10-05 09:30 CEST\n"
        "  ends: 2026-11-05 01:00 CET\n"
        "  time zone: CEST (local)"
    )
    # Only an end, in a fixed-offset zone.
    utc_minus_7 = timezone(timedelta(hours=-7))
    end = str(int(datetime(2026, 10, 8, 7, 0, tzinfo=UTC).timestamp() * 1000))
    assert vacation.text({"endTime": end}, utc_minus_7) == (
        "Vacation responder: off\n"
        "  last day: 2026-10-07\n"
        "  time zone: UTC-07:00 (local)"
    )
