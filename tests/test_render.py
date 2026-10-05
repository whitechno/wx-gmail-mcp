from wx_gmail_mcp import render


def test_clean_text_drops_invisible_characters() -> None:
    padded = "Big​ sale͏͏͏ ⁠now﻿ ­to‍day"
    assert render.clean_text(padded) == "Big sale now today"
    # Line breaks, tabs, accents and symbols are not format characters.
    assert render.clean_text("é\tń\n€ ok") == "é\tń\n€ ok"
    assert render.clean_text("") == ""


def test_block_aligns_continuation_lines() -> None:
    assert render.block("body", "one") == "  body: one"
    assert render.block("html", "<p>a</p>\n<p>b</p>") == (
        "  html: <p>a</p>\n        <p>b</p>"
    )
    assert render.block("sig", "") == "  sig: "
