from __future__ import annotations

from pathlib import Path

from slopsentinel.baseline import build_baseline, filter_violations, load_baseline, save_baseline
from slopsentinel.config import SlopSentinelConfig
from slopsentinel.engine.types import Location, Violation
from slopsentinel.scanner import ScanTarget


def _v(rule_id: str, *, path: Path | None, line: int | None, message: str = "msg") -> Violation:
    loc = None
    if path is not None and line is not None:
        loc = Location(path=path, start_line=line, start_col=1)
    return Violation(
        rule_id=rule_id,
        severity="warn",
        message=message,
        dimension="quality",
        location=loc,
    )


def test_baseline_roundtrip_and_filter(tmp_path: Path) -> None:
    project_root = tmp_path
    file_path = tmp_path / "src" / "app.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("x = 1\nx = 2\n", encoding="utf-8")

    violations = [
        _v("A03", path=file_path, line=1, message="polite"),
        _v("A01", path=None, line=None, message="repo"),
        _v("E03", path=file_path, line=2, message="unused"),
    ]

    baseline = build_baseline(violations, project_root=project_root)
    out = tmp_path / ".slopsentinel-baseline.json"
    save_baseline(baseline, out)

    loaded = load_baseline(out)
    remaining = filter_violations(violations, loaded, project_root=project_root)
    assert remaining == []


def test_audit_applies_baseline_for_full_scan(monkeypatch, tmp_path: Path) -> None:
    from slopsentinel import audit as audit_mod

    project_root = tmp_path
    baseline_path = tmp_path / "baseline.json"

    file_path = tmp_path / "src" / "a.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("x = 1\n", encoding="utf-8")

    v = _v("A03", path=file_path, line=1, message="polite")
    baseline = build_baseline([v], project_root=project_root)
    save_baseline(baseline, baseline_path)

    target = ScanTarget(project_root=project_root, scan_path=project_root, config=SlopSentinelConfig(baseline="baseline.json"))

    monkeypatch.setattr(audit_mod, "build_file_contexts", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(audit_mod, "detect", lambda *_args, **_kwargs: [v])

    result = audit_mod.audit_files(target, files=[], changed_lines=None)
    assert result.summary.violations == ()


def test_audit_does_not_apply_baseline_for_diff_scan(monkeypatch, tmp_path: Path) -> None:
    from slopsentinel import audit as audit_mod

    project_root = tmp_path
    baseline_path = tmp_path / "baseline.json"

    file_path = tmp_path / "src" / "a.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("x = 1\n", encoding="utf-8")

    v = _v("A03", path=file_path, line=1, message="polite")
    baseline = build_baseline([v], project_root=project_root)
    save_baseline(baseline, baseline_path)

    target = ScanTarget(project_root=project_root, scan_path=project_root, config=SlopSentinelConfig(baseline="baseline.json"))

    monkeypatch.setattr(audit_mod, "build_file_contexts", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(audit_mod, "detect", lambda *_args, **_kwargs: [v])

    result = audit_mod.audit_files(target, files=[], changed_lines={file_path: {1}})
    assert list(result.summary.violations) == [v]


def test_baseline_cli_refuses_output_outside_root(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from slopsentinel.cli import app

    runner = CliRunner()
    # Use an empty directory for scan and request output outside the root.
    result = runner.invoke(app, ["baseline", str(tmp_path), "--output", "../baseline.json"])
    assert result.exit_code != 0


def test_baseline_cli_writes_default_file(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from slopsentinel.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["baseline", str(tmp_path)])
    assert result.exit_code == 0
    out = tmp_path / ".slopsentinel-baseline.json"
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert '"version": 2' in text


def test_baseline_fingerprint_survives_line_number_drift(tmp_path: Path) -> None:
    project_root = tmp_path
    file_path = tmp_path / "src" / "app.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("def f():\n    x = 1\n    return x\n", encoding="utf-8")

    baseline = build_baseline([_v("A03", path=file_path, line=2, message="polite")], project_root=project_root)

    # Insert a new line at the top of the file (common refactor), shifting line numbers.
    file_path.write_text("# header\n" + file_path.read_text(encoding="utf-8"), encoding="utf-8")

    moved = _v("A03", path=file_path, line=3, message="polite")
    remaining = filter_violations([moved], baseline, project_root=project_root)
    assert remaining == []
