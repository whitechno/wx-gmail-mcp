from __future__ import annotations

from pathlib import Path
from typing import Any

import httplib2
import pytest
from googleapiclient.errors import HttpError
from mcp.server.mcpserver import MCPServer

from wx_gmail_mcp import sendas
from wx_gmail_mcp.config import BASE_SCOPES, SCOPE_FULL, SCOPE_SETTINGS_BASIC
from wx_gmail_mcp.errors import WxGmailError
from wx_gmail_mcp.server import build_server

from .conftest import FakeRuntime, call, make_settings, tool_names
from .fake_gmail import FakeGmail

SETTINGS_SCOPES = (*BASE_SCOPES, SCOPE_SETTINGS_BASIC)
PRIMARY: dict[str, Any] = {
    "sendAsEmail": "you@example.com",
    "displayName": "You Example",
    "replyToAddress": "",
    "signature": "<div>Kind regards,<br>You</div>",
    "isPrimary": True,
    "isDefault": True,
    "verificationStatus": "verificationStatusUnspecified",
}
ALIAS: dict[str, Any] = {
    "sendAsEmail": "Alias@Example.com",
    "displayName": "",
    "replyToAddress": "team@example.com",
    "signature": "",
    "isPrimary": False,
    "isDefault": False,
    "treatAsAlias": True,
    "verificationStatus": "pending",
}


def settings_server(
    tmp_path: Path, fake: FakeGmail, scopes: tuple[str, ...] = SETTINGS_SCOPES
) -> MCPServer:
    settings = make_settings(tmp_path, settings=True)
    return build_server(FakeRuntime(settings, {"work": fake}, {"work": scopes}))


def _fake(**responses: Any) -> FakeGmail:
    base: dict[str, Any] = {"users.settings.sendAs.list": {"sendAs": [PRIMARY, ALIAS]}}
    base.update(responses)
    return FakeGmail(base)


def patched(**kwargs: Any) -> dict[str, Any]:
    """``sendAs.patch`` returns the whole identity with the change applied."""
    source = PRIMARY if kwargs["sendAsEmail"] == "you@example.com" else ALIAS
    return {**source, **kwargs["body"]}


# --- helpers ---------------------------------------------------------------------


def test_find() -> None:
    assert sendas.find([ALIAS, PRIMARY], "") is PRIMARY
    assert sendas.find([PRIMARY, ALIAS], " alias@example.com ") is ALIAS
    assert sendas.find([PRIMARY, ALIAS], "YOU@example.com") is PRIMARY
    with pytest.raises(WxGmailError, match="no primary send-as identity"):
        sendas.find([ALIAS], "")
    with pytest.raises(WxGmailError) as e:
        sendas.find([PRIMARY, ALIAS], "other@example.com")
    assert str(e.value) == (
        "'other@example.com' is not a send-as address of this account. Known: "
        "you@example.com, Alias@Example.com."
    )


def test_text() -> None:
    assert sendas.text(PRIMARY) == (
        "you@example.com (primary, default)\n"
        "  name: You Example\n"
        "  signature: <div>Kind regards,<br>You</div>"
    )
    assert sendas.text(ALIAS) == (
        "Alias@Example.com (alias)\n"
        "  reply-to: team@example.com\n"
        "  verification: pending\n"
        "  signature: (none)"
    )
    multi = {**PRIMARY, "signature": "<div>Line 1</div>\n<div>Line 2</div>"}
    assert sendas.text(multi).endswith(
        "  signature: <div>Line 1</div>\n             <div>Line 2</div>"
    )
    assert sendas.text({}) == "(no address)\n  signature: (none)"


# --- registration and scope -----------------------------------------------------


def test_send_as_tools_register_only_behind_the_settings_gate(
    tmp_path: Path,
) -> None:
    off = build_server(FakeRuntime(make_settings(tmp_path), {"work": FakeGmail()}))
    assert {"list_send_as", "set_signature"} & tool_names(off) == set()
    assert {"list_send_as", "set_signature"} <= tool_names(
        settings_server(tmp_path, FakeGmail())
    )


def test_send_as_tools_require_the_settings_scope(tmp_path: Path) -> None:
    fake = _fake()
    # The full mail scope does not cover the settings endpoints.
    mcp = settings_server(tmp_path, fake, scopes=(*BASE_SCOPES, SCOPE_FULL))
    text = call(mcp, "list_send_as", account="work")
    assert text.startswith(
        "Error: Account 'work' has not granted the settings.basic scope. "
        "Set WX_GMAIL_ALLOW_SETTINGS=true and re-authorize with: "
    )
    assert "--auth work" in text
    text = call(mcp, "set_signature", account="work", signature="<p>x</p>")
    assert text.startswith(
        "Error: Account 'work' has not granted the settings.basic scope."
    )
    assert fake.calls == []


# --- list_send_as ---------------------------------------------------------------


def test_list_send_as(tmp_path: Path) -> None:
    fake = _fake()
    text = call(settings_server(tmp_path, fake), "list_send_as", account="work")
    assert text == (
        "2 send-as identities:\n"
        "you@example.com (primary, default)\n"
        "  name: You Example\n"
        "  signature: <div>Kind regards,<br>You</div>\n"
        "Alias@Example.com (alias)\n"
        "  reply-to: team@example.com\n"
        "  verification: pending\n"
        "  signature: (none)"
    )
    assert fake.calls == [("users.settings.sendAs.list", {"userId": "me"})]


def test_list_send_as_singular_and_empty(tmp_path: Path) -> None:
    fake = _fake(**{"users.settings.sendAs.list": {"sendAs": [PRIMARY]}})
    text = call(settings_server(tmp_path, fake), "list_send_as", account="work")
    assert text.startswith("1 send-as identity:\nyou@example.com (primary, default)\n")
    fake = _fake(**{"users.settings.sendAs.list": {}})
    text = call(settings_server(tmp_path, fake), "list_send_as", account="work")
    assert text == "No send-as identities."


# --- set_signature --------------------------------------------------------------


def test_set_signature_on_the_primary_by_default(tmp_path: Path) -> None:
    fake = _fake(**{"users.settings.sendAs.patch": patched})
    text = call(
        settings_server(tmp_path, fake),
        "set_signature",
        account="work",
        signature="<div>wx-test signature</div>",
    )
    assert fake.calls_to("users.settings.sendAs.patch") == [
        {
            "userId": "me",
            "sendAsEmail": "you@example.com",
            "body": {"signature": "<div>wx-test signature</div>"},
        }
    ]
    assert text == (
        "Set the signature of you@example.com.\n"
        "you@example.com (primary, default)\n"
        "  name: You Example\n"
        "  signature: <div>wx-test signature</div>"
    )


def test_set_signature_on_an_alias_and_clearing(tmp_path: Path) -> None:
    fake = _fake(**{"users.settings.sendAs.patch": patched})
    mcp = settings_server(tmp_path, fake)
    text = call(
        mcp,
        "set_signature",
        account="work",
        signature="<p>Team</p>",
        send_as_email="alias@example.com",
    )
    # The address is sent as Gmail lists it, not as the user typed it.
    assert fake.calls_to("users.settings.sendAs.patch")[-1]["sendAsEmail"] == (
        "Alias@Example.com"
    )
    assert text.startswith("Set the signature of Alias@Example.com.\n")
    assert text.endswith("  signature: <p>Team</p>")
    text = call(mcp, "set_signature", account="work", signature="")
    assert fake.calls_to("users.settings.sendAs.patch")[-1] == {
        "userId": "me",
        "sendAsEmail": "you@example.com",
        "body": {"signature": ""},
    }
    assert text == (
        "Cleared the signature of you@example.com.\n"
        "you@example.com (primary, default)\n"
        "  name: You Example\n"
        "  signature: (none)"
    )


def test_set_signature_unknown_address_and_api_error(tmp_path: Path) -> None:
    def refuse(**kwargs: Any) -> dict[str, Any]:
        raise HttpError(
            httplib2.Response({"status": 403}),
            b'{"error": {"message": "Forbidden"}}',
        )

    fake = _fake(**{"users.settings.sendAs.patch": refuse})
    mcp = settings_server(tmp_path, fake)
    text = call(
        mcp,
        "set_signature",
        account="work",
        signature="x",
        send_as_email="nobody@example.com",
    )
    assert text == (
        "Error: 'nobody@example.com' is not a send-as address of this account. "
        "Known: you@example.com, Alias@Example.com."
    )
    assert fake.calls_to("users.settings.sendAs.patch") == []
    assert call(mcp, "set_signature", account="work", signature="x") == (
        "Gmail API error: HTTP 403: Forbidden"
    )


def test_set_signature_whitespace_only_clears(tmp_path: Path) -> None:
    fake = _fake(**{"users.settings.sendAs.patch": patched})
    mcp = settings_server(tmp_path, fake)
    text = call(mcp, "set_signature", account="work", signature="  \n\t ")
    assert fake.calls_to("users.settings.sendAs.patch")[-1]["body"] == {"signature": ""}
    assert text.startswith("Cleared the signature of you@example.com.\n")
