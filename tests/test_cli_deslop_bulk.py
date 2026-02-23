from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from slopsentinel.cli import app


def test_deslop_directory_check_exits_non_zero_when_changes_needed(tmp_path: Path) -> None:
    dirty = tmp_path / "dirty.py"
    dirty.write_text("# We need to ensure this is safe\nx = 1\n", encoding="utf-8")
    clean = tmp_path / "clean.py"
    clean.write_text("x = 1\n", encoding="utf-8")

    runner = CliRunner()
    res = runner.invoke(app, ["deslop", str(tmp_path), "--check"])
    assert res.exit_code == 1
    assert "dirty.py" in res.output

    # --check must not modify files.
    assert "We need to ensure" in dirty.read_text(encoding="utf-8")
    assert clean.read_text(encoding="utf-8") == "x = 1\n"


def test_deslop_directory_dry_run_prints_diff(tmp_path: Path) -> None:
    dirty = tmp_path / "dirty.py"
    dirty.write_text("# We need to ensure this is safe\nx = 1\n", encoding="utf-8")

    runner = CliRunner()
    res = runner.invoke(app, ["deslop", str(tmp_path), "--dry-run"])
    assert res.exit_code == 0
    assert "---" in res.output
    assert "dirty.py" in res.output
    assert "We need to ensure" in res.output


def test_deslop_file_mode_echoes_diff_for_dry_run_and_write(tmp_path: Path) -> None:
    dirty = tmp_path / "dirty.py"
    dirty.write_text("# We need to ensure this is safe\nx = 1\n", encoding="utf-8")

    runner = CliRunner()
    dry = runner.invoke(app, ["deslop", str(dirty), "--dry-run"])
    assert dry.exit_code == 0
    assert "---" in dry.output
    assert "dirty.py" in dry.output
    assert "We need to ensure" in dirty.read_text(encoding="utf-8")

    write = runner.invoke(app, ["deslop", str(dirty)])
    assert write.exit_code == 0
    assert "---" in write.output
    assert "dirty.py" in write.output
    assert "We need to ensure" not in dirty.read_text(encoding="utf-8")


def test_deslop_file_mode_check_exits_non_zero_without_echoing_diff(tmp_path: Path) -> None:
    dirty = tmp_path / "dirty.py"
    dirty.write_text("# We need to ensure this is safe\nx = 1\n", encoding="utf-8")

    runner = CliRunner()
    res = runner.invoke(app, ["deslop", str(dirty), "--check"])
    assert res.exit_code == 1
    # --check is a dry-run and should not print a diff in file mode.
    assert "---" not in res.output
    assert "We need to ensure" in dirty.read_text(encoding="utf-8")
