from __future__ import annotations

from pathlib import Path

from slopsentinel.deslop import deslop_file, deslop_text


def test_deslop_text_removes_common_ai_comment_artifacts() -> None:
    before = "\n".join(
        [
            "# ====== Configuration ======",
            "# We need to ensure this is safe",
            "# Here's a comprehensive explanation",
            "# As of my last update, something something",
            "# <thinking> do not leak </thinking>",
            "# Keep this comment (it explains why)",
            "x = 1",
            "",
        ]
    )
    after = deslop_text(before)
    assert "Configuration" not in after
    assert "We need to ensure" not in after
    assert "Here's a comprehensive" not in after
    assert "As of my last update" not in after
    assert "<thinking>" not in after
    assert "Keep this comment" in after
    assert "x = 1" in after


def test_deslop_file_dry_run_does_not_write(tmp_path: Path) -> None:
    path = tmp_path / "example.py"
    path.write_text("# We need to ensure this is safe\nx = 1\n", encoding="utf-8")

    result = deslop_file(path, backup=True, dry_run=True)
    assert result.changed is True
    assert path.read_text(encoding="utf-8") == "# We need to ensure this is safe\nx = 1\n"
    assert not (tmp_path / "example.py.slopsentinel.bak").exists()


def test_deslop_file_backup_and_write(tmp_path: Path) -> None:
    path = tmp_path / "example.py"
    original = "# We need to ensure this is safe\nx = 1\n"
    path.write_text(original, encoding="utf-8")

    result = deslop_file(path, backup=True, dry_run=False)
    assert result.changed is True

    backup = tmp_path / "example.py.slopsentinel.bak"
    assert backup.exists()
    assert backup.read_text(encoding="utf-8") == original
    assert "We need to ensure" not in path.read_text(encoding="utf-8")


def test_deslop_text_removes_inline_python_comment_artifact() -> None:
    before = "x = 1  # We need to ensure this is safe\n"
    after = deslop_text(before, language="python")
    assert "We need to ensure" not in after
    assert "x = 1" in after
