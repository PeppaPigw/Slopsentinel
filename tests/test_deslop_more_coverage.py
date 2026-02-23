from __future__ import annotations

from pathlib import Path

import pytest

from slopsentinel.deslop import _comment_matches_ai_artifact, deslop_file, deslop_text


def test_deslop_text_non_python_preserves_blank_lines_and_handles_block_comments() -> None:
    before = (
        "/* start block\n"
        "We need to ensure this is safe\n"
        "*/\n"
        "\n"
        "x = 1\n"
        "// Here's a comprehensive explanation\n"
        "y = 2\n"
    )
    after = deslop_text(before, language="javascript")
    assert "We need to ensure" not in after
    assert "Here's a comprehensive" not in after
    assert "\n\n" in after  # blank line preserved
    assert "x = 1" in after
    assert "y = 2" in after


def test_deslop_text_python_falls_back_to_line_heuristic_on_tokenize_error() -> None:
    # Unterminated triple-quoted string forces tokenize.TokenError; the fallback
    # heuristic should still remove full-line AI artifacts.
    before = "# We need to ensure this is safe\n\"\"\"unterminated\n"
    after = deslop_text(before, language="python")
    assert "We need to ensure" not in after
    assert '"""unterminated' in after


def test_deslop_text_python_does_not_remove_slop_directives() -> None:
    before = "x = 1  # slop: disable=A03 We need to ensure this is safe\n"
    after = deslop_text(before, language="python")
    assert "# slop: disable=A03" in after
    assert "We need to ensure" in after


def test_deslop_text_python_keeps_non_artifact_comments() -> None:
    before = "x = 1  # explain why this is safe\n"
    after = deslop_text(before, language="python")
    assert after == before


def test_comment_matches_ai_artifact_patterns() -> None:
    assert _comment_matches_ai_artifact("# --------------------------")
    assert _comment_matches_ai_artifact("# Let's do this")
    assert _comment_matches_ai_artifact("# Here's a comprehensive explanation")
    assert _comment_matches_ai_artifact("# As of my last update, blah")
    assert _comment_matches_ai_artifact("# <thinking> nope </thinking>")
    assert _comment_matches_ai_artifact("# We need to do this")
    assert not _comment_matches_ai_artifact("# normal comment")


def test_deslop_file_backup_is_not_overwritten_if_it_exists(tmp_path: Path) -> None:
    path = tmp_path / "example.py"
    path.write_text("# We need to ensure this is safe\nx = 1\n", encoding="utf-8")
    backup = tmp_path / "example.py.slopsentinel.bak"
    backup.write_text("existing backup\n", encoding="utf-8")

    deslop_file(path, backup=True, dry_run=False)
    assert backup.read_text(encoding="utf-8") == "existing backup\n"


def test_deslop_file_raises_permission_error_on_write(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "example.py"
    path.write_text("# We need to ensure this is safe\nx = 1\n", encoding="utf-8")

    original_write_text = Path.write_text

    def guarded_write_text(self: Path, text: str, *args, **kwargs) -> int:
        if self == path:
            raise PermissionError("blocked")
        return original_write_text(self, text, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", guarded_write_text)

    with pytest.raises(PermissionError):
        deslop_file(path, backup=True, dry_run=False)

