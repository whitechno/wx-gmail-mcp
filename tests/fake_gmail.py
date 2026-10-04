"""A fake Gmail discovery service: records calls, returns canned data.

Call chains look like the real client:
``svc.users().messages().list(userId="me").execute()``. The fake keys
responses by the dotted path (``users.messages.list``). A response may be
a dict (returned every time), a list of dicts (returned in order), or a
callable taking the call's kwargs.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

Response = dict[str, Any] | list[dict[str, Any]] | Callable[..., dict[str, Any]]


class FakeGmail:
    def __init__(self, responses: dict[str, Response] | None = None) -> None:
        self.responses: dict[str, Response] = dict(responses or {})
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def users(self) -> _Node:
        return _Node(self, "users", {})

    def calls_to(self, path: str) -> list[dict[str, Any]]:
        return [kw for p, kw in self.calls if p == path]

    def respond(self, path: str, kwargs: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((path, kwargs))
        canned = self.responses.get(path)
        if canned is None:
            return {}
        if callable(canned):
            return canned(**kwargs)
        if isinstance(canned, list):
            if not canned:
                raise AssertionError(f"no canned responses left for {path}")
            return canned.pop(0)
        return canned


class _Node:
    def __init__(self, fake: FakeGmail, path: str, kwargs: dict[str, Any]) -> None:
        self._fake = fake
        self._path = path
        self._kwargs = kwargs

    def __getattr__(self, name: str) -> Callable[..., _Node]:
        if name.startswith("_"):
            raise AttributeError(name)

        def call(**kwargs: Any) -> _Node:
            return _Node(self._fake, f"{self._path}.{name}", kwargs)

        return call

    def execute(self) -> dict[str, Any]:
        return self._fake.respond(self._path, self._kwargs)
