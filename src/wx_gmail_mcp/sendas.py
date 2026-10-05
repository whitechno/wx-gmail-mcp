"""Send-as identities: lookup by address and plain-text rendering.

A Gmail account has one primary identity and may have aliases. Each
carries a display name, an optional reply-to address, flags and an HTML
signature. Only the signature is written here, and only through
``sendAs.patch``; creating or verifying an alias needs the sharing scope,
which this server never requests.
"""

from __future__ import annotations

from typing import Any

from wx_gmail_mcp.errors import WxGmailError
from wx_gmail_mcp.render import block

SendAs = dict[str, Any]


def address(identity: SendAs) -> str:
    return str(identity.get("sendAsEmail", "") or "")


def find(identities: list[SendAs], send_as_email: str) -> SendAs:
    """The identity for ``send_as_email``, or the primary one when it is
    blank. Address comparison ignores case."""
    wanted = send_as_email.strip().lower()
    if not wanted:
        for identity in identities:
            if identity.get("isPrimary"):
                return identity
        raise WxGmailError("The account reports no primary send-as identity.")
    for identity in identities:
        if address(identity).lower() == wanted:
            return identity
    known = ", ".join(address(i) for i in identities) or "(none)"
    raise WxGmailError(
        f"'{send_as_email.strip()}' is not a send-as address of this account. "
        f"Known: {known}."
    )


def _flags(identity: SendAs) -> str:
    flags = [
        label
        for key, label in (
            ("isPrimary", "primary"),
            ("isDefault", "default"),
            ("treatAsAlias", "alias"),
        )
        if identity.get(key)
    ]
    return f" ({', '.join(flags)})" if flags else ""


def text(identity: SendAs) -> str:
    """One identity: address and flags, then name, reply-to, verification
    (aliases only) and the signature as stored, HTML included."""
    lines = [f"{address(identity) or '(no address)'}{_flags(identity)}"]
    if name := str(identity.get("displayName", "") or ""):
        lines.append(f"  name: {name}")
    if reply_to := str(identity.get("replyToAddress", "") or ""):
        lines.append(f"  reply-to: {reply_to}")
    status = str(identity.get("verificationStatus", "") or "")
    if status and status != "verificationStatusUnspecified":
        lines.append(f"  verification: {status}")
    signature = str(identity.get("signature", "") or "")
    lines.append(block("signature", signature) if signature else "  signature: (none)")
    return "\n".join(lines)
