from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from slopsentinel.baseline import BASELINE_VERSION
from slopsentinel.cli import app
from slopsentinel.engine.types import DimensionBreakdown
from slopsentinel.history import HistoryEntry, save_history
from slopsentinel.reporters.json_reporter import REPORT_SCHEMA_VERSION


def test_scan_json_includes_schema_and_can_fail_on_slop(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "example.py").write_text("# We need to ensure this is safe\nx = 1\n", encoding="utf-8")

    runner = CliRunner()
    res = runner.invoke(app, ["scan", str(tmp_path), "--format", "json", "--threshold", "100", "--fail-on-slop"])
    assert res.exit_code == 1

    payload = json.loads(res.stdout)
    assert payload["schema_version"] == REPORT_SCHEMA_VERSION
    assert payload["score"] < 100


def test_fix_dry_run_outputs_diff_without_modifying(tmp_path: Path) -> None:
    target = tmp_path / "dirty.py"
    target.write_text("# We need to ensure this is safe\nx = 1\n", encoding="utf-8")

    runner = CliRunner()
    res = runner.invoke(app, ["fix", str(target), "--dry-run"])
    assert res.exit_code == 0, res.stdout
    assert "---" in res.stdout
    assert "dirty.py" in res.stdout

    # Dry-run must not modify the file.
    assert "We need to ensure" in target.read_text(encoding="utf-8")


def test_baseline_command_writes_default_file(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "example.py").write_text("# We need to ensure this is safe\nx = 1\n", encoding="utf-8")

    runner = CliRunner()
    res = runner.invoke(app, ["baseline", str(tmp_path)])
    assert res.exit_code == 0, res.stdout

    baseline_path = tmp_path / ".slopsentinel-baseline.json"
    assert baseline_path.exists()
    data = json.loads(baseline_path.read_text(encoding="utf-8"))
    assert data.get("version") == BASELINE_VERSION


def test_trend_json_reads_history_and_enforces_min_score(tmp_path: Path) -> None:
    history_path = tmp_path / ".slopsentinel" / "history.json"
    entries = [
        HistoryEntry(
            timestamp="2026-01-01T00:00:00Z",
            score=90,
            files_scanned=10,
            violations=3,
            breakdown=DimensionBreakdown(fingerprint=35, quality=20, hallucination=20, maintainability=15, security=0),
        ),
        HistoryEntry(
            timestamp="2026-01-02T00:00:00Z",
            score=80,
            files_scanned=12,
            violations=6,
            breakdown=DimensionBreakdown(fingerprint=33, quality=18, hallucination=18, maintainability=11, security=0),
        ),
    ]
    save_history(history_path, entries)

    runner = CliRunner()
    ok = runner.invoke(app, ["trend", str(tmp_path), "--format", "json", "--last", "2"])
    assert ok.exit_code == 0, ok.stdout
    payload = json.loads(ok.stdout)
    assert payload["entries"]
    assert payload["trend"] == -10

    bad = runner.invoke(app, ["trend", str(tmp_path), "--format", "json", "--last", "2", "--min-score", "99"])
    assert bad.exit_code == 1
