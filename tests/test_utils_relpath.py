from __future__ import annotations

import json
from pathlib import Path

from helpers import make_file_ctx

from slopsentinel.config import SlopSentinelConfig
from slopsentinel.engine.context import ProjectContext
from slopsentinel.engine.detection import detect
from slopsentinel.engine.scoring import summarize
from slopsentinel.reporters.json_reporter import render_json
from slopsentinel.reporters.sarif import render_sarif
from slopsentinel.utils import safe_relpath


def test_safe_relpath_returns_relative_path_when_under_root(tmp_path: Path) -> None:
    root = tmp_path
    path = tmp_path / "src" / "example.py"
    assert safe_relpath(path, root) == "src/example.py"


def test_safe_relpath_falls_back_when_not_under_root(tmp_path: Path) -> None:
    root = tmp_path
    path = Path("foo/bar.py")
    assert safe_relpath(path, root) == "foo/bar.py"


def test_safe_relpath_handles_resolve_oserror(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path
    path = tmp_path / "src" / "example.py"

    def _boom(self: Path, strict: bool = False) -> Path:
        raise OSError("boom")

    monkeypatch.setattr(type(root), "resolve", _boom)
    assert safe_relpath(path, root) == "src/example.py"


def test_json_and_sarif_paths_are_relative_to_project_root(tmp_path: Path) -> None:
    project = ProjectContext(project_root=tmp_path, scan_path=tmp_path, files=(), config=SlopSentinelConfig())
    ctx = make_file_ctx(project, relpath="src/example.py", content="# We need to ensure this is closed\nx = 1\n")
    violations = detect(project, [ctx])
    summary = summarize(files_scanned=1, violations=violations)

    payload = json.loads(render_json(summary, project_root=tmp_path))
    json_paths = [
        v["location"]["path"]
        for v in payload["violations"]
        if v.get("location") is not None and v["location"].get("path") is not None
    ]
    assert json_paths and all(p == "src/example.py" for p in json_paths)

    sarif = json.loads(render_sarif(list(summary.violations), project_root=tmp_path))
    sarif_paths: list[str] = []
    for res in sarif["runs"][0]["results"]:
        for loc in res.get("locations", []):
            uri = loc["physicalLocation"]["artifactLocation"]["uri"]
            sarif_paths.append(uri)
    assert sarif_paths and all(p == "src/example.py" for p in sarif_paths)
