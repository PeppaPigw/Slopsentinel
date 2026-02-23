from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from slopsentinel.cli import app

pytestmark = pytest.mark.integration


def _git(cwd: Path, *args: str) -> None:
    subprocess.check_call(
        ["git", *args],
        cwd=str(cwd),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init")
    _git(repo, "config", "user.email", "slopsentinel@example.test")
    _git(repo, "config", "user.name", "SlopSentinel Tests")


def test_diff_staged_only_reports_added_lines(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)

    (repo / "pyproject.toml").write_text("[tool.slopsentinel]\n", encoding="utf-8")

    source = repo / "src" / "example.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("# We need to ensure this is safe\nx = 1\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")

    # Add a new slop comment above the old one. The old violation should not
    # show up in a staged diff scan because it is not on an added/modified line.
    source.write_text(
        "# We need to ensure this is newly added\n"
        "# We need to ensure this is safe\n"
        "x = 1\n",
        encoding="utf-8",
    )
    _git(repo, "add", str(source.relative_to(repo)))

    runner = CliRunner()
    res = runner.invoke(app, ["diff", str(repo), "--staged", "--format", "json", "--threshold", "60"])
    assert res.exit_code == 0, res.stdout

    payload = json.loads(res.stdout)
    violations = payload["violations"]
    assert len(violations) == 1
    assert violations[0]["rule_id"] == "A03"
    assert violations[0]["location"]["start_line"] == 1


def test_baseline_suppresses_existing_findings(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)

    (repo / "pyproject.toml").write_text(
        """
[tool.slopsentinel]
baseline = ".slopsentinel-baseline.json"
""".lstrip(),
        encoding="utf-8",
    )

    source = repo / "src" / "example.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("# We need to ensure this is safe\nx = 1\n", encoding="utf-8")

    runner = CliRunner()
    baseline_res = runner.invoke(app, ["baseline", str(repo)])
    assert baseline_res.exit_code == 0
    assert (repo / ".slopsentinel-baseline.json").exists()

    scan_res = runner.invoke(app, ["scan", str(repo), "--format", "json", "--threshold", "60"])
    assert scan_res.exit_code == 0
    payload = json.loads(scan_res.stdout)
    assert payload["violations"] == []

    # Add a new violation far away so the original baseline fingerprint remains stable.
    source.write_text("# We need to ensure this is safe\nx = 1\n\n# We need to ensure this is new\n", encoding="utf-8")
    scan_res2 = runner.invoke(app, ["scan", str(repo), "--format", "json", "--threshold", "60"])
    assert scan_res2.exit_code == 0
    payload2 = json.loads(scan_res2.stdout)
    assert [v["rule_id"] for v in payload2["violations"]] == ["A03"]
