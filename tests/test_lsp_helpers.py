from __future__ import annotations

from pathlib import Path

from slopsentinel.engine.types import Location, Violation
from slopsentinel.lsp import uri_to_path, violations_to_diagnostics


def test_uri_to_path_file_uri() -> None:
    path = uri_to_path("file:///tmp/example.py")
    assert path == Path("/tmp/example.py")


def test_violations_to_diagnostics_maps_severity_and_range() -> None:
    text = "a = 1\nb = 2\n"
    v = Violation(
        rule_id="E03",
        severity="warn",
        message="msg",
        suggestion="do it",
        dimension="quality",
        location=Location(path=None, start_line=2, start_col=2),
    )
    diags = violations_to_diagnostics([v], text=text)
    assert len(diags) == 1
    d = diags[0]
    assert d["severity"] == 2
    assert d["code"] == "E03"
    assert d["range"]["start"]["line"] == 1
    assert d["range"]["start"]["character"] == 1
    assert "Suggestion:" in d["message"]

