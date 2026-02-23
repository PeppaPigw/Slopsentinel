from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from slopsentinel.cli import app


def test_explain_json_includes_rule_metadata(tmp_path: Path) -> None:
    runner = CliRunner()
    res = runner.invoke(app, ["explain", "A03", "--format", "json", "--path", str(tmp_path)])
    assert res.exit_code == 0
    payload = json.loads(res.output)
    assert payload["rule_id"] == "A03"
    assert payload["default_severity"] in {"info", "warn", "error"}
    assert payload["dimension"] in {"fingerprint", "quality", "hallucination", "maintainability", "security"}


def test_explain_unknown_rule_exits_non_zero(tmp_path: Path) -> None:
    runner = CliRunner()
    res = runner.invoke(app, ["explain", "ZZ99", "--path", str(tmp_path)])
    assert res.exit_code != 0

