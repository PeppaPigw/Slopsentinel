from __future__ import annotations

import json
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from slopsentinel.cli import app
from slopsentinel.reporters.json_reporter import REPORT_SCHEMA_VERSION


def test_cli_rejects_verbose_and_quiet_together(tmp_path: Path) -> None:
    runner = CliRunner()
    res = runner.invoke(app, ["--verbose", "--quiet", "scan", str(tmp_path), "--format", "json"])
    assert res.exit_code != 0


def test_init_command_generates_files_non_interactive(tmp_path: Path) -> None:
    runner = CliRunner()
    res = runner.invoke(
        app,
        [
            "init",
            str(tmp_path),
            "--ci",
            "github",
            "--pre-commit",
            "--languages",
            "python,typescript",
            "--scoring-profile",
            "strict",
        ],
    )
    assert res.exit_code == 0, res.stdout
    assert (tmp_path / "pyproject.toml").exists()
    assert (tmp_path / ".pre-commit-config.yaml").exists()
    assert (tmp_path / ".github" / "workflows" / "slopsentinel.yml").exists()


def test_diff_staged_json_reports_changed_line_violations(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)

    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)
    path = src / "example.py"
    path.write_text("x = 1\n", encoding="utf-8")

    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, check=True, stdout=subprocess.DEVNULL)

    # Introduce an A03-style comment on a changed line.
    path.write_text("# We need to ensure this is safe\nx = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", str(path)], cwd=tmp_path, check=True, stdout=subprocess.DEVNULL)

    runner = CliRunner()
    res = runner.invoke(
        app,
        ["diff", str(tmp_path), "--staged", "--format", "json", "--threshold", "100", "--fail-on-slop"],
    )
    assert res.exit_code == 1, res.stdout

    payload = json.loads(res.stdout)
    assert payload["schema_version"] == REPORT_SCHEMA_VERSION
    assert any(v["rule_id"] == "A03" for v in payload["violations"])

