from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import slopsentinel.cli as cli_mod
from slopsentinel.audit import AuditResult
from slopsentinel.config import CacheConfig, ScoringConfig, SlopSentinelConfig
from slopsentinel.engine.types import DimensionBreakdown, Location, ScanSummary, Violation
from slopsentinel.reporters.json_reporter import render_json
from slopsentinel.scanner import ScanTarget


def _summary(*, project_root: Path, score: int, violations: tuple[Violation, ...]) -> ScanSummary:
    return ScanSummary(
        files_scanned=1,
        violations=violations,
        score=int(score),
        breakdown=DimensionBreakdown(
            fingerprint=0,
            quality=0,
            hallucination=0,
            maintainability=0,
            security=0,
        ),
        dominant_fingerprints=(),
    )


def _dummy_target(project_root: Path, *, cache_enabled: bool = False, baseline: str | None = None) -> ScanTarget:
    config = SlopSentinelConfig(
        threshold=60,
        fail_on_slop=False,
        cache=CacheConfig(enabled=cache_enabled),
        scoring=ScoringConfig(profile="default"),
        baseline=baseline,
    )
    return ScanTarget(project_root=project_root, scan_path=project_root, config=config)


def test_report_reads_json_from_file_and_renders_markdown(tmp_path: Path) -> None:
    src = tmp_path / "src" / "example.py"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("print('hi')\n", encoding="utf-8")

    v = Violation(
        rule_id="A03",
        severity="info",
        dimension="fingerprint",
        message="We need to ensure this is tested.",
        location=Location(path=src, start_line=1, start_col=1, end_line=1, end_col=5),
    )
    payload = render_json(_summary(project_root=tmp_path, score=90, violations=(v,)), project_root=tmp_path)
    report_path = tmp_path / "report.json"
    report_path.write_text(payload, encoding="utf-8")

    runner = CliRunner()
    res = runner.invoke(cli_mod.app, ["report", str(report_path), "--format", "markdown", "--project-root", str(tmp_path)])
    assert res.exit_code == 0, res.output
    assert "# SlopSentinel report" in res.output
    assert "| File | Line | Rule |" in res.output


def test_report_reads_json_from_stdin(tmp_path: Path) -> None:
    src = tmp_path / "src" / "example.py"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("print('hi')\n", encoding="utf-8")

    v = Violation(
        rule_id="A03",
        severity="info",
        dimension="fingerprint",
        message="We need to ensure this is tested.",
        location=Location(path=src, start_line=1, start_col=1, end_line=1, end_col=5),
    )
    payload = render_json(_summary(project_root=tmp_path, score=90, violations=(v,)), project_root=tmp_path)

    runner = CliRunner()
    res = runner.invoke(
        cli_mod.app,
        ["report", "-", "--format", "markdown", "--project-root", str(tmp_path)],
        input=payload,
    )
    assert res.exit_code == 0, res.output
    assert "# SlopSentinel report" in res.output


def test_report_invalid_json_exits_2(tmp_path: Path) -> None:
    report_path = tmp_path / "report.json"
    report_path.write_text("{", encoding="utf-8")

    runner = CliRunner()
    res = runner.invoke(cli_mod.app, ["report", str(report_path), "--format", "markdown", "--project-root", str(tmp_path)])
    assert res.exit_code == 2
    assert "invalid json report" in res.output.lower()


def test_compare_json_reports_json_output(tmp_path: Path) -> None:
    src = tmp_path / "src" / "example.py"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("print('hi')\n", encoding="utf-8")

    before_v = Violation(
        rule_id="A03",
        severity="info",
        dimension="fingerprint",
        message="before",
        location=Location(path=src, start_line=1, start_col=1, end_line=1, end_col=5),
    )
    after_v = Violation(
        rule_id="A04",
        severity="warn",
        dimension="quality",
        message="after",
        location=Location(path=src, start_line=1, start_col=1, end_line=1, end_col=5),
    )

    before_payload = render_json(_summary(project_root=tmp_path, score=90, violations=(before_v,)), project_root=tmp_path)
    after_payload = render_json(_summary(project_root=tmp_path, score=80, violations=(after_v,)), project_root=tmp_path)

    before_path = tmp_path / "before.json"
    after_path = tmp_path / "after.json"
    before_path.write_text(before_payload, encoding="utf-8")
    after_path.write_text(after_payload, encoding="utf-8")

    runner = CliRunner()
    res = runner.invoke(
        cli_mod.app,
        ["compare", str(before_path), str(after_path), "--format", "json", "--project-root", str(tmp_path)],
    )
    assert res.exit_code == 0, res.output

    payload = json.loads(res.output)
    assert payload["score_delta"] == -10
    assert len(payload["added"]) == 1
    assert len(payload["removed"]) == 1
    assert payload["added"][0]["rule_id"] == "A04"
    assert payload["removed"][0]["rule_id"] == "A03"


def test_compare_invalid_json_exits_2(tmp_path: Path) -> None:
    before_path = tmp_path / "before.json"
    after_path = tmp_path / "after.json"
    before_path.write_text("{", encoding="utf-8")
    after_path.write_text("{", encoding="utf-8")

    runner = CliRunner()
    res = runner.invoke(cli_mod.app, ["compare", str(before_path), str(after_path)])
    assert res.exit_code == 2
    assert "invalid json report" in res.output.lower()


def test_ci_auto_format_and_exit_codes(tmp_path: Path, monkeypatch) -> None:
    src = tmp_path / "src" / "example.py"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("print('hi')\n", encoding="utf-8")

    target = _dummy_target(tmp_path, cache_enabled=True)

    monkeypatch.setattr("slopsentinel.scanner.prepare_target", lambda _p: target)
    monkeypatch.setattr("slopsentinel.scanner.discover_files", lambda _t: [src])

    v = Violation(
        rule_id="A03",
        severity="error",
        dimension="fingerprint",
        message="We need to ensure this is tested.",
        location=Location(path=src, start_line=1, start_col=1, end_line=1, end_col=5),
    )
    low_score = _summary(project_root=tmp_path, score=10, violations=(v,))
    ok_score = _summary(project_root=tmp_path, score=99, violations=(v,))

    calls: list[dict[str, object]] = []

    def fake_audit_files(target_arg, *, files, changed_lines=None, apply_baseline=True, record_history=False, **_kwargs):  # noqa: ANN001
        calls.append(
            {
                "target": target_arg,
                "files": tuple(files),
                "apply_baseline": apply_baseline,
                "record_history": record_history,
            }
        )
        summary = ok_score if len(calls) == 1 else low_score
        return AuditResult(target=target_arg, files=tuple(files), summary=summary)

    monkeypatch.setattr("slopsentinel.audit.audit_files", fake_audit_files)

    captured_formats: list[str] = []

    def fake_emit_output(fmt: str, *, summary, project_root, console, allow_github, show_details=True):  # noqa: ANN001
        captured_formats.append(fmt)

    monkeypatch.setattr("slopsentinel.cli._emit_output", fake_emit_output)

    runner = CliRunner()

    # Auto-format should select GitHub output inside GitHub Actions.
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    ok = runner.invoke(cli_mod.app, ["ci", str(tmp_path), "--fail-under", "0", "--no-cache"])
    assert ok.exit_code == 0, ok.output
    assert captured_formats[-1] == "github"
    assert calls[-1]["record_history"] is False
    assert isinstance(calls[-1]["target"], ScanTarget)
    assert calls[-1]["target"].config.cache.enabled is False

    # Fail-under should return exit code 1 (stable CI semantics).
    fail = runner.invoke(cli_mod.app, ["ci", str(tmp_path), "--fail-under", "75", "--format", "terminal"])
    assert fail.exit_code == 1, fail.output


def test_ci_update_baseline_writes_file(tmp_path: Path, monkeypatch) -> None:
    src = tmp_path / "src" / "example.py"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("print('hi')\n", encoding="utf-8")

    target = _dummy_target(tmp_path)
    monkeypatch.setattr("slopsentinel.scanner.prepare_target", lambda _p: target)
    monkeypatch.setattr("slopsentinel.scanner.discover_files", lambda _t: [src])

    v = Violation(
        rule_id="A03",
        severity="info",
        dimension="fingerprint",
        message="We need to ensure this is tested.",
        location=Location(path=src, start_line=1, start_col=1, end_line=1, end_col=5),
    )
    summary = _summary(project_root=tmp_path, score=90, violations=(v,))

    seen_apply_baseline: list[bool] = []

    def fake_audit_files(target_arg, *, files, changed_lines=None, apply_baseline=True, record_history=False, **_kwargs):  # noqa: ANN001
        seen_apply_baseline.append(apply_baseline)
        return AuditResult(target=target_arg, files=tuple(files), summary=summary)

    monkeypatch.setattr("slopsentinel.audit.audit_files", fake_audit_files)
    monkeypatch.setattr("slopsentinel.cli._emit_output", lambda *_a, **_k: None)

    runner = CliRunner()
    res = runner.invoke(cli_mod.app, ["ci", str(tmp_path), "--update-baseline", "--format", "terminal"])
    assert res.exit_code == 0, res.output
    assert seen_apply_baseline == [True, False]

    baseline_path = tmp_path / ".slopsentinel-baseline.json"
    assert baseline_path.exists()


@pytest.mark.parametrize("fmt", ["nope", "markdown"])
def test_ci_rejects_unsupported_format(tmp_path: Path, fmt: str) -> None:
    runner = CliRunner()
    res = runner.invoke(cli_mod.app, ["ci", str(tmp_path), "--format", fmt])
    assert res.exit_code != 0
