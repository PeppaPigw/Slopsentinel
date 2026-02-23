from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from slopsentinel.cli import app


def test_rules_command_json_lists_builtins(tmp_path: Path) -> None:
    runner = CliRunner()
    res = runner.invoke(app, ["rules", str(tmp_path), "--format", "json"])
    assert res.exit_code == 0, res.stdout

    data = json.loads(res.stdout)
    ids = {row["rule_id"] for row in data}
    assert "A01" in ids
    assert "E01" in ids


def test_rules_command_enabled_only_respects_config(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.slopsentinel]

[tool.slopsentinel.rules]
enable = ["claude"]
""".lstrip(),
        encoding="utf-8",
    )

    runner = CliRunner()
    res = runner.invoke(app, ["rules", str(tmp_path), "--enabled-only", "--format", "json"])
    assert res.exit_code == 0, res.stdout

    data = json.loads(res.stdout)
    ids = {row["rule_id"] for row in data}
    assert "A01" in ids
    assert "E01" not in ids

