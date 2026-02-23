from __future__ import annotations

from pathlib import Path

from slopsentinel.engine.types import Location, Violation
from slopsentinel.reporters.github import render_github_annotations


def test_render_github_annotations_repo_level_and_file_level(tmp_path: Path) -> None:
    project_root = tmp_path
    file_path = tmp_path / "src" / "app.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("x = 1\n", encoding="utf-8")

    repo_level = Violation(
        rule_id="A01",
        severity="info",
        message="repo message",
        dimension="fingerprint",
        location=None,
    )
    file_level = Violation(
        rule_id="E03",
        severity="warn",
        message="file message",
        dimension="quality",
        location=Location(path=file_path, start_line=1, start_col=2),
    )
    error_level = Violation(
        rule_id="E01",
        severity="error",
        message="boom",
        dimension="hallucination",
        location=None,
    )

    out = render_github_annotations([repo_level, file_level, error_level], project_root=project_root)
    lines = out.splitlines()
    assert lines[0] == "::notice::A01 repo message"
    assert lines[1].startswith("::warning file=src/app.py,line=1,col=2::E03 file message")
    assert lines[2] == "::error::E01 boom"
