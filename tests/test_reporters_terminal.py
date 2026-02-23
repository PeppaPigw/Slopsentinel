from __future__ import annotations

from pathlib import Path

from rich.console import Console

from slopsentinel.engine.types import DimensionBreakdown, Location, ScanSummary, Violation
from slopsentinel.reporters.terminal import render_terminal


def test_render_terminal_includes_file_snippet_and_summary(tmp_path: Path) -> None:
    project_root = tmp_path
    file_path = tmp_path / "src" / "app.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("# comment\nx = 1\n", encoding="utf-8")

    v_repo = Violation(
        rule_id="A01",
        severity="info",
        message="repo signal",
        dimension="fingerprint",
        location=None,
    )
    v_file = Violation(
        rule_id="A03",
        severity="warn",
        message="overly polite",
        suggestion="remove it",
        dimension="fingerprint",
        location=Location(path=file_path, start_line=2, start_col=1),
    )
    summary = ScanSummary(
        files_scanned=1,
        violations=(v_repo, v_file),
        score=50,
        breakdown=DimensionBreakdown(
            fingerprint=10,
            quality=0,
            hallucination=0,
            maintainability=0,
            security=0,
        ),
        dominant_fingerprints=("claude",),
    )

    console = Console(record=True, width=120)
    render_terminal(summary, project_root=project_root, console=console)
    text = console.export_text()

    assert "Repository signals" in text
    assert "src/app.py" in text
    assert "x = 1" in text
    assert "Score: 50/100" in text
    assert "Dominant: claude" in text


def test_render_terminal_handles_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "missing.py"
    v = Violation(
        rule_id="E03",
        severity="warn",
        message="unused import",
        dimension="quality",
        location=Location(path=missing, start_line=1, start_col=1),
    )
    summary = ScanSummary(
        files_scanned=1,
        violations=(v,),
        score=90,
        breakdown=DimensionBreakdown(
            fingerprint=0,
            quality=10,
            hallucination=0,
            maintainability=0,
            security=0,
        ),
    )

    console = Console(record=True, width=120)
    render_terminal(summary, project_root=tmp_path, console=console)
    text = console.export_text()
    assert "missing.py" in text

