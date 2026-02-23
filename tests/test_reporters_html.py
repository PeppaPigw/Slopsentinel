from __future__ import annotations

from pathlib import Path

from slopsentinel.engine.types import DimensionBreakdown, Location, ScanSummary, Violation
from slopsentinel.reporters.html_reporter import render_html


def test_render_html_includes_snippet_and_escapes(tmp_path: Path) -> None:
    project_root = tmp_path
    file_path = tmp_path / "src" / "app.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text('x = "<script>alert(1)</script>"\n', encoding="utf-8")

    v = Violation(
        rule_id="A03",
        severity="warn",
        message="msg <b>bad</b>",
        suggestion="use < and >",
        dimension="fingerprint",
        location=Location(path=file_path, start_line=1, start_col=1),
    )

    summary = ScanSummary(
        files_scanned=1,
        violations=(v,),
        score=99,
        breakdown=DimensionBreakdown(
            fingerprint=35,
            quality=25,
            hallucination=20,
            maintainability=15,
            security=5,
        ),
        dominant_fingerprints=("claude",),
    )

    text = render_html(summary, project_root=project_root)
    assert "<!doctype html>" in text.lower()
    assert "src/app.py" in text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in text
    assert "msg &lt;b&gt;bad&lt;/b&gt;" in text
    assert "use &lt; and &gt;" in text
    assert "id=\"filters\"" in text
    assert "data-severity=\"warn\"" in text
