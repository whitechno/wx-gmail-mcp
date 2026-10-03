import pytest

from wx_gmail_mcp import __version__
from wx_gmail_mcp.cli import main


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"wx-gmail-mcp {__version__}"


def test_serve_is_not_implemented_yet(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main([]) == 2
    assert "not implemented" in capsys.readouterr().out
