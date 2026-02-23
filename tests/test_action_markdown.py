from __future__ import annotations

from pathlib import Path

from slopsentinel.action_markdown import _render_comment_body, _write_step_summary
from slopsentinel.engine.types import DimensionBreakdown, Location, ScanSummary, Violation


def _v(rule_id: str, severity: str, *, msg: str = "msg", suggestion: str | None = None) -> Violation:
    return Violation(
        rule_id=rule_id,
        severity=severity,  # type: ignore[arg-type]
        message=msg,
        suggestion=suggestion,
        dimension="quality",
        location=Location(path=Path("src/app.py"), start_line=1, start_col=1),
    )


def test_render_comment_body_sorts_and_truncates() -> None:
    marker = "<!-- slopsentinel:v1 key=abc path=src/app.py line=1 -->"
    items = [
        _v("E03", "warn", suggestion="remove it"),
        _v("A06", "error"),
        _v("A03", "warn"),
        _v("C09", "info"),
        _v("D01", "warn"),
        _v("E10", "warn"),
        _v("E04", "error"),
    ]

    body = _render_comment_body(items, marker=marker)
    lines = body.splitlines()

    assert lines[0].startswith("**SlopSentinel**")
    assert lines[-1] == marker
    assert any("…and 1 more finding(s)" in line for line in lines)

    # Sorted by severity (error before warn before info), then by rule_id.
    bullet_lines = [line for line in lines if line.startswith("- ")]
    assert "`A06`" in bullet_lines[0]
    assert any("`E03`" in line and "remove it" in line for line in bullet_lines)


def test_write_step_summary_writes_markdown(tmp_path: Path, monkeypatch) -> None:
    dest = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(dest))

    summary = ScanSummary(
        files_scanned=2,
        violations=(),
        score=87,
        breakdown=DimensionBreakdown(
            fingerprint=20,
            quality=15,
            hallucination=10,
            maintainability=12,
            security=5,
        ),
        dominant_fingerprints=("claude",),
    )

    _write_step_summary(summary)

    text = dest.read_text(encoding="utf-8")
    assert "## SlopSentinel report" in text
    assert "Score: **87/100**" in text
    assert "Dominant fingerprints: claude" in text


def test_write_step_summary_noop_when_env_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    dest = tmp_path / "summary.md"
    assert not dest.exists()

    summary = ScanSummary(
        files_scanned=1,
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
    _write_step_summary(summary)
    assert not dest.exists()
