from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from slopsentinel.audit import AuditResult
from slopsentinel.cli import app
from slopsentinel.config import SlopSentinelConfig
from slopsentinel.engine.types import DimensionBreakdown, ScanSummary
from slopsentinel.scanner import ScanTarget


def _dummy_audit_result(
    project_root: Path,
    *,
    score: int,
    threshold: int = 60,
    fail_on_slop: bool = False,
) -> AuditResult:
    config = SlopSentinelConfig(
        threshold=threshold,
        fail_on_slop=fail_on_slop,
    )
    target = ScanTarget(project_root=project_root, scan_path=project_root, config=config)
    summary = ScanSummary(
        files_scanned=0,
        violations=(),
        score=score,
        breakdown=DimensionBreakdown(
            fingerprint=0,
            quality=0,
            hallucination=0,
            maintainability=0,
            security=0,
        ),
        dominant_fingerprints=(),
    )
    return AuditResult(target=target, files=(), summary=summary)


def test_scan_exit_code_is_controlled_by_fail_on_slop_config(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    dummy = _dummy_audit_result(tmp_path, score=0, threshold=60, fail_on_slop=False)
    monkeypatch.setattr("slopsentinel.cli._audit_with_optional_progress", lambda *_args, **_kwargs: dummy)

    res = runner.invoke(app, ["scan", str(tmp_path), "--format", "json", "--threshold", "60"])
    assert res.exit_code == 0


def test_scan_exits_non_zero_when_fail_on_slop_config_true(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    dummy = _dummy_audit_result(tmp_path, score=0, threshold=60, fail_on_slop=True)
    monkeypatch.setattr("slopsentinel.cli._audit_with_optional_progress", lambda *_args, **_kwargs: dummy)

    res = runner.invoke(app, ["scan", str(tmp_path), "--format", "json", "--threshold", "60"])
    assert res.exit_code == 1


def test_scan_no_fail_on_slop_overrides_config(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    dummy = _dummy_audit_result(tmp_path, score=0, threshold=60, fail_on_slop=True)
    monkeypatch.setattr("slopsentinel.cli._audit_with_optional_progress", lambda *_args, **_kwargs: dummy)

    res = runner.invoke(app, ["scan", str(tmp_path), "--format", "json", "--threshold", "60", "--no-fail-on-slop"])
    assert res.exit_code == 0


def test_scan_fail_on_slop_overrides_config(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    dummy = _dummy_audit_result(tmp_path, score=0, threshold=60, fail_on_slop=False)
    monkeypatch.setattr("slopsentinel.cli._audit_with_optional_progress", lambda *_args, **_kwargs: dummy)

    res = runner.invoke(app, ["scan", str(tmp_path), "--format", "json", "--threshold", "60", "--fail-on-slop"])
    assert res.exit_code == 1


def test_diff_passes_base_and_head_and_defaults_to_non_blocking(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    dummy = _dummy_audit_result(tmp_path, score=0, threshold=60, fail_on_slop=False)

    captured: dict[str, object] = {}

    def fake_changed_lines_between(base: str, head: str, *, cwd: Path, scope: Path | None = None) -> dict[Path, set[int]]:
        captured["base"] = base
        captured["head"] = head
        captured["cwd"] = cwd
        captured["scope"] = scope
        return {}

    monkeypatch.setattr("slopsentinel.gitdiff.changed_lines_between", fake_changed_lines_between)
    monkeypatch.setattr("slopsentinel.cli._audit_with_optional_progress", lambda *_args, **_kwargs: dummy)

    res = runner.invoke(
        app,
        [
            "diff",
            str(tmp_path),
            "--base",
            "BASE_SHA",
            "--head",
            "HEAD_SHA",
            "--format",
            "json",
            "--threshold",
            "60",
        ],
    )
    assert res.exit_code == 0
    assert captured["base"] == "BASE_SHA"
    assert captured["head"] == "HEAD_SHA"
    assert captured["cwd"] == tmp_path.resolve()
    assert captured["scope"] == tmp_path.resolve()


def test_diff_fail_on_slop_exits_non_zero(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    dummy = _dummy_audit_result(tmp_path, score=0, threshold=60, fail_on_slop=False)

    monkeypatch.setattr("slopsentinel.gitdiff.changed_lines_between", lambda *_args, **_kwargs: {})
    monkeypatch.setattr("slopsentinel.cli._audit_with_optional_progress", lambda *_args, **_kwargs: dummy)

    res = runner.invoke(
        app,
        ["diff", str(tmp_path), "--base", "BASE_SHA", "--head", "HEAD_SHA", "--format", "json", "--threshold", "60", "--fail-on-slop"],
    )
    assert res.exit_code == 1
