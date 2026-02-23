from __future__ import annotations

from pathlib import Path

from slopsentinel.engine.types import DimensionBreakdown, Location, ScanSummary, Violation
from slopsentinel.reporters.markdown import render_markdown


def test_render_markdown_no_violations(tmp_path: Path) -> None:
    summary = ScanSummary(
        files_scanned=0,
        violations=(),
        score=100,
        breakdown=DimensionBreakdown(fingerprint=0, quality=0, hallucination=0, maintainability=0, security=0),
        dominant_fingerprints=(),
        ai_confidence="low",
        violation_density=0.0,
        violation_clustering=0.0,
        scoring_profile="default",
    )
    out = render_markdown(summary, project_root=tmp_path)
    assert "No violations found." in out


def test_render_markdown_includes_table_and_relpaths(tmp_path: Path) -> None:
    path = tmp_path / "src" / "example.py"
    v = Violation(
        rule_id="A03",
        severity="warn",
        message="We need to ensure this is safe.",
        dimension="fingerprint",
        suggestion="Delete the narration comment.",
        location=Location(path=path, start_line=3, start_col=1, end_line=3, end_col=10),
    )
    repo_level = Violation(
        rule_id="X01",
        severity="info",
        message="Duplicate code across files.",
        dimension="maintainability",
        suggestion=None,
        location=None,
    )
    summary = ScanSummary(
        files_scanned=1,
        violations=(v, repo_level),
        score=42,
        breakdown=DimensionBreakdown(fingerprint=1, quality=0, hallucination=0, maintainability=0, security=0),
        dominant_fingerprints=("copilot",),
        ai_confidence="high",
        violation_density=0.1,
        violation_clustering=0.2,
        scoring_profile="strict",
    )
    out = render_markdown(summary, project_root=tmp_path)
    assert "| File | Line | Rule | Severity | Dimension | Message |" in out
    assert "src/example.py" in out
    assert "`A03`" in out
    assert "Delete the narration comment." in out
