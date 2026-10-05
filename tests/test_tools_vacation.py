from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httplib2
from googleapiclient.errors import HttpError
from mcp.server.mcpserver import MCPServer

from wx_gmail_mcp.config import BASE_SCOPES, SCOPE_FULL, SCOPE_SETTINGS_BASIC
from wx_gmail_mcp.server import build_server

from .conftest import FakeRuntime, call, make_settings, tool_names
from .fake_gmail import FakeGmail

SETTINGS_SCOPES = (*BASE_SCOPES, SCOPE_SETTINGS_BASIC)
# 2026-10-05 00:00 and 2026-10-08 00:00 in America/Los_Angeles (PDT, UTC-7).
OCT_5 = str(int(datetime(2026, 10, 5, 7, 0, tzinfo=UTC).timestamp() * 1000))
OCT_8 = str(int(datetime(2026, 10, 8, 7, 0, tzinfo=UTC).timestamp() * 1000))
CURRENT: dict[str, Any] = {
    "enableAutoReply": False,
    "responseSubject": "Old subject",
    "responseBodyHtml": "<div>Old message</div>",
    "restrictToContacts": False,
    "restrictToDomain": False,
}


def settings_server(
    tmp_path: Path, fake: FakeGmail, scopes: tuple[str, ...] = SETTINGS_SCOPES
) -> MCPServer:
    settings = make_settings(tmp_path, settings=True)
    return build_server(FakeRuntime(settings, {"work": fake}, {"work": scopes}))


def echo(**kwargs: Any) -> dict[str, Any]:
    """``updateVacation`` returns the resource as stored."""
    return dict(kwargs["body"])


# --- registration and scope -----------------------------------------------------


def test_vacation_tools_register_only_behind_the_settings_gate(
    tmp_path: Path,
) -> None:
    off = build_server(FakeRuntime(make_settings(tmp_path), {"work": FakeGmail()}))
    assert {"get_vacation", "set_vacation"} & tool_names(off) == set()
    assert {"get_vacation", "set_vacation"} <= tool_names(
        settings_server(tmp_path, FakeGmail())
    )


def test_vacation_tools_require_the_settings_scope(tmp_path: Path) -> None:
    fake = FakeGmail({"users.settings.getVacation": CURRENT})
    # The full mail scope does not cover the settings endpoints.
    mcp = settings_server(tmp_path, fake, scopes=(*BASE_SCOPES, SCOPE_FULL))
    text = call(mcp, "get_vacation", account="work")
    assert text.startswith(
        "Error: Account 'work' has not granted the settings.basic scope. "
        "Set WX_GMAIL_ALLOW_SETTINGS=true and re-authorize with: "
    )
    assert "--auth work" in text
    text = call(mcp, "set_vacation", account="work", enabled=True, body="Away")
    assert text.startswith(
        "Error: Account 'work' has not granted the settings.basic scope."
    )
    assert fake.calls == []


# --- get_vacation ---------------------------------------------------------------


def test_get_vacation(tmp_path: Path) -> None:
    fake = FakeGmail({"users.settings.getVacation": CURRENT})
    text = call(settings_server(tmp_path, fake), "get_vacation", account="work")
    assert text == (
        "Vacation responder: off\n"
        "  subject: Old subject\n"
        "  html: <div>Old message</div>"
    )
    assert fake.calls == [("users.settings.getVacation", {"userId": "me"})]


def test_get_vacation_with_period_in_a_named_zone(tmp_path: Path) -> None:
    on = {
        **CURRENT,
        "enableAutoReply": True,
        "startTime": OCT_5,
        "endTime": OCT_8,
        "restrictToContacts": True,
    }
    fake = FakeGmail({"users.settings.getVacation": on})
    mcp = settings_server(tmp_path, fake)
    text = call(mcp, "get_vacation", account="work", timezone="America/Los_Angeles")
    assert text == (
        "Vacation responder: on\n"
        "  subject: Old subject\n"
        "  html: <div>Old message</div>\n"
        "  first day: 2026-10-05\n"
        "  last day: 2026-10-07\n"
        "  time zone: America/Los_Angeles\n"
        "  only to: contacts"
    )
    # The same instants read differently one zone east: no longer midnights.
    text = call(mcp, "get_vacation", account="work", timezone="America/Denver")
    assert "  starts: 2026-10-05 01:00 MDT\n  ends: 2026-10-08 01:00 MDT\n" in text
    assert call(mcp, "get_vacation", account="work", timezone="Nowhere/City") == (
        "Error: timezone: 'Nowhere/City' is not a known IANA zone (like Europe/Paris)."
    )
    assert len(fake.calls) == 2  # the bad zone is refused before any call


# --- set_vacation ---------------------------------------------------------------


def test_set_vacation_replaces_the_whole_resource(tmp_path: Path) -> None:
    fake = FakeGmail({"users.settings.updateVacation": echo})
    text = call(
        settings_server(tmp_path, fake),
        "set_vacation",
        account="work",
        enabled=True,
        subject="wx-test away",
        body="Back on the 8th.",
        html="<p>Back on the 8th.</p>",
        start_date="2026-10-05",
        end_date="2026-10-07",
        contacts_only=True,
        timezone="America/Los_Angeles",
    )
    assert fake.calls == [
        (
            "users.settings.updateVacation",
            {
                "userId": "me",
                "body": {
                    "enableAutoReply": True,
                    "responseSubject": "wx-test away",
                    "responseBodyPlainText": "Back on the 8th.",
                    "responseBodyHtml": "<p>Back on the 8th.</p>",
                    "restrictToContacts": True,
                    "restrictToDomain": False,
                    "startTime": OCT_5,
                    "endTime": OCT_8,
                },
            },
        )
    ]
    assert text == (
        "Updated the vacation responder.\n"
        "Vacation responder: on\n"
        "  subject: wx-test away\n"
        "  body: Back on the 8th.\n"
        "  html: <p>Back on the 8th.</p>\n"
        "  first day: 2026-10-05\n"
        "  last day: 2026-10-07\n"
        "  time zone: America/Los_Angeles\n"
        "  only to: contacts"
    )


def test_set_vacation_off_keeps_only_what_is_passed(tmp_path: Path) -> None:
    fake = FakeGmail({"users.settings.updateVacation": echo})
    text = call(
        settings_server(tmp_path, fake),
        "set_vacation",
        account="work",
        enabled=False,
        subject="Old subject",
        html="<div>Old message</div>",
    )
    body = fake.calls_to("users.settings.updateVacation")[0]["body"]
    assert body == {
        "enableAutoReply": False,
        "responseSubject": "Old subject",
        "responseBodyPlainText": "",
        "responseBodyHtml": "<div>Old message</div>",
        "restrictToContacts": False,
        "restrictToDomain": False,
    }
    assert "startTime" not in body and "endTime" not in body
    assert text == (
        "Updated the vacation responder.\n"
        "Vacation responder: off\n"
        "  subject: Old subject\n"
        "  html: <div>Old message</div>"
    )
    # Turning it off with nothing else clears the saved message.
    text = call(
        settings_server(tmp_path, fake), "set_vacation", account="work", enabled=False
    )
    assert text == (
        "Updated the vacation responder.\nVacation responder: off (nothing saved)"
    )


def test_set_vacation_validation_happens_before_any_call(tmp_path: Path) -> None:
    fake = FakeGmail({"users.settings.updateVacation": echo})
    mcp = settings_server(tmp_path, fake)
    assert call(mcp, "set_vacation", account="work", enabled=True) == (
        "Error: An enabled responder needs a message: body or html."
    )
    assert call(mcp, "set_vacation", account="work", enabled=True, body="  ") == (
        "Error: An enabled responder needs a message: body or html."
    )
    assert (
        call(
            mcp,
            "set_vacation",
            account="work",
            enabled=True,
            body="x",
            start_date="soon",
        )
        == "Error: start_date: 'soon' is not a date (YYYY-MM-DD)."
    )
    assert (
        call(
            mcp,
            "set_vacation",
            account="work",
            enabled=True,
            body="x",
            start_date="2026-10-07",
            end_date="2026-10-05",
        )
        == "Error: end_date 2026-10-05 is before start_date 2026-10-07."
    )
    assert (
        call(
            mcp, "set_vacation", account="work", enabled=False, timezone="Mars/Olympus"
        )
        == "Error: timezone: 'Mars/Olympus' is not a known IANA zone (like "
        "Europe/Paris)."
    )
    assert fake.calls == []
    # A disabled responder may store a message without one.
    assert call(mcp, "set_vacation", account="work", enabled=False, subject="s") == (
        "Updated the vacation responder.\nVacation responder: off\n  subject: s"
    )


def test_set_vacation_api_error(tmp_path: Path) -> None:
    def refuse(**kwargs: Any) -> dict[str, Any]:
        raise HttpError(
            httplib2.Response({"status": 400}),
            b'{"error": {"message": "Invalid vacation settings"}}',
        )

    fake = FakeGmail({"users.settings.updateVacation": refuse})
    text = call(
        settings_server(tmp_path, fake),
        "set_vacation",
        account="work",
        enabled=True,
        body="x",
    )
    assert text == "Gmail API error: HTTP 400: Invalid vacation settings"
