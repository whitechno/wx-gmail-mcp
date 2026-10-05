"""Vacation responder: dates to Gmail's epoch milliseconds, and back to text.

Gmail stores ``startTime`` and ``endTime`` as epoch milliseconds and
treats them as instants: replies go to mail received from the start
instant up to (not including) the end instant. The web UI shows a first
and a last day instead, both inclusive, at midnight in the mailbox's
zone. The tools speak dates the same way: ``start_date`` is midnight at
the start of that day, ``end_date`` is midnight at the end of it, in the
zone given or the machine's local zone.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from wx_gmail_mcp.errors import WxGmailError

DATE_FORMAT = "YYYY-MM-DD"


def resolve_zone(name: str) -> tzinfo | None:
    """An IANA zone by name; None (the default) means the machine's zone."""
    name = name.strip()
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError, ValueError:
        raise WxGmailError(
            f"timezone: '{name}' is not a known IANA zone (like Europe/Paris)."
        ) from None


def parse_date(value: str, what: str) -> date:
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise WxGmailError(
            f"{what}: '{value}' is not a date ({DATE_FORMAT})."
        ) from None


def start_of_day(day: date, zone: tzinfo | None) -> datetime:
    """Midnight starting ``day``; DST-aware in both the local and named case."""
    naive = datetime.combine(day, time.min)
    return naive.astimezone() if zone is None else naive.replace(tzinfo=zone)


def to_millis(moment: datetime) -> str:
    """The string form Gmail uses for its int64 time fields."""
    return str(int(moment.timestamp() * 1000))


def from_millis(value: Any, zone: tzinfo | None) -> datetime | None:
    """Gmail's time field (a string or int of epoch ms) as a zoned datetime;
    None when absent or zero."""
    try:
        millis = int(value)
    except TypeError, ValueError:
        return None
    if millis <= 0:
        return None
    moment = datetime.fromtimestamp(millis / 1000, UTC)
    return moment.astimezone() if zone is None else moment.astimezone(zone)


def period(start_date: str, end_date: str, zone: tzinfo | None) -> dict[str, str]:
    """``startTime``/``endTime`` for the request body: the first day's
    midnight and the midnight that ends the last day. Either may be
    missing; both present must be in order."""
    fields: dict[str, str] = {}
    start = parse_date(start_date, "start_date") if start_date.strip() else None
    end = parse_date(end_date, "end_date") if end_date.strip() else None
    if start and end and end < start:
        raise WxGmailError(
            f"end_date {end.isoformat()} is before start_date {start.isoformat()}."
        )
    if start:
        fields["startTime"] = to_millis(start_of_day(start, zone))
    if end:
        fields["endTime"] = to_millis(start_of_day(end + timedelta(days=1), zone))
    return fields


def _block(name: str, value: str) -> str:
    """``  name: first line`` with continuation lines aligned under it."""
    first, *rest = value.splitlines() or [""]
    pad = " " * (len(name) + 4)
    return "\n".join([f"  {name}: {first}", *(pad + line for line in rest)])


def _when(moment: datetime, end: bool) -> str:
    """A midnight reads as a day (the last day for the end instant); any
    other instant reads with its time and zone."""
    if moment.time() == time.min:
        if end:
            return f"last day: {(moment.date() - timedelta(days=1)).isoformat()}"
        return f"first day: {moment.date().isoformat()}"
    label = "ends" if end else "starts"
    return f"{label}: {moment.strftime('%Y-%m-%d %H:%M %Z')}"


def text(settings: dict[str, Any], zone: tzinfo | None, zone_name: str = "") -> str:
    """The responder as plain text: state, message, period, restrictions."""
    on = bool(settings.get("enableAutoReply"))
    lines = [f"Vacation responder: {'on' if on else 'off'}"]
    subject = str(settings.get("responseSubject", "") or "")
    plain = str(settings.get("responseBodyPlainText", "") or "")
    html = str(settings.get("responseBodyHtml", "") or "")
    if subject:
        lines.append(f"  subject: {subject}")
    if plain:
        lines.append(_block("body", plain))
    if html:
        lines.append(_block("html", html))
    start = from_millis(settings.get("startTime"), zone)
    end = from_millis(settings.get("endTime"), zone)
    if start:
        lines.append("  " + _when(start, end=False))
    if end:
        lines.append("  " + _when(end, end=True))
    anchor = start or end
    if anchor:
        shown = zone_name.strip() or f"{anchor.tzname()} (local)"
        lines.append(f"  time zone: {shown}")
    only = [
        label
        for key, label in (
            ("restrictToContacts", "contacts"),
            ("restrictToDomain", "same domain"),
        )
        if settings.get(key)
    ]
    if only:
        lines.append(f"  only to: {', '.join(only)}")
    if len(lines) == 1:
        lines[0] += " (nothing saved)"
    return "\n".join(lines)
