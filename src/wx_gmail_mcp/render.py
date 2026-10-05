"""Plain-text rendering helpers shared by tool output."""

from __future__ import annotations

import unicodedata

# U+034F COMBINING GRAPHEME JOINER is a mark (Mn), not a format character,
# yet it is invisible; marketing mail pads snippets with long runs of it.
_INVISIBLE = frozenset({"͏"})


def clean_text(text: str) -> str:
    """Drop invisible characters: Unicode format characters (zero-width
    spaces and joiners, byte order marks, soft hyphens, bidi controls) and
    the grapheme joiner. Line breaks and tabs stay."""
    return "".join(
        c for c in text if c not in _INVISIBLE and unicodedata.category(c) != "Cf"
    )


def block(name: str, value: str) -> str:
    """``  name: first line`` with continuation lines aligned under it."""
    first, *rest = value.splitlines() or [""]
    pad = " " * (len(name) + 4)
    return "\n".join([f"  {name}: {first}", *(pad + line for line in rest)])
