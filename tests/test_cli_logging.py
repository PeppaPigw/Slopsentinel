from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from slopsentinel.audit import AuditResult
from slopsentinel.cli import app
from slopsentinel.engine.types import DimensionBreakdown, ScanSummary


def _dummy_audit_result(target, files) -> AuditResult:
    summary = ScanSummary(
        files_scanned=len(files),
        violations=(),
        score=100,
        breakdown=DimensionBreakdown(
            fingerprint=0,
            quality=0,
            hallucination=0,
            maintainability=0,
            security=0,
        ),
    )
    return AuditResult(target=target, files=tuple(files), summary=summary)


def test_cli_verbose_enables_debug_logging(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "example.py").write_text("x = 1\n", encoding="utf-8")

    def fake_audit_files(target, *, files, **_kwargs):  # type: ignore[no-untyped-def]
        return _dummy_audit_result(target, files)

    monkeypatch.setattr("slopsentinel.cli.audit_files", fake_audit_files)

    runner = CliRunner()
    res = runner.invoke(app, ["--verbose", "scan", str(tmp_path), "--format", "json"])
    assert res.exit_code == 0
    assert "discovered" in res.output.lower()


def test_cli_quiet_suppresses_debug_logging(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "example.py").write_text("x = 1\n", encoding="utf-8")

    def fake_audit_files(target, *, files, **_kwargs):  # type: ignore[no-untyped-def]
        return _dummy_audit_result(target, files)

    monkeypatch.setattr("slopsentinel.cli.audit_files", fake_audit_files)

    runner = CliRunner()
    res = runner.invoke(app, ["--quiet", "scan", str(tmp_path), "--format", "json"])
    assert res.exit_code == 0
    assert "discovered" not in res.output.lower()


def test_cli_verbose_logs_cache_stats_when_cache_enabled(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.slopsentinel]

[tool.slopsentinel.cache]
enabled = true
path = ".slopsentinel/cache.json"
""".lstrip(),
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "example.py").write_text("x = 1\n", encoding="utf-8")

    runner = CliRunner()
    res = runner.invoke(app, ["--verbose", "scan", str(tmp_path), "--format", "json"])
    assert res.exit_code == 0
    assert "cache:" in res.output.lower()
