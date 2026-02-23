from __future__ import annotations

import json
from pathlib import Path

from helpers import make_file_ctx

from slopsentinel.config import RuleOverride, RulesConfig, SlopSentinelConfig
from slopsentinel.engine.context import ProjectContext
from slopsentinel.engine.detection import detect
from slopsentinel.engine.scoring import summarize
from slopsentinel.reporters.json_reporter import render_json
from slopsentinel.reporters.sarif import render_sarif


def test_engine_respects_line_suppression(tmp_path: Path) -> None:
    config = SlopSentinelConfig()
    project = ProjectContext(project_root=tmp_path, scan_path=tmp_path, files=(), config=config)
    ctx = make_file_ctx(
        project,
        relpath="src/example.py",
        content="# We need to ensure this is closed  # slop: disable=A03\nx = 1\n",
    )
    violations = detect(project, [ctx])
    assert all(v.rule_id != "A03" for v in violations)


def test_engine_applies_severity_override(tmp_path: Path) -> None:
    config = SlopSentinelConfig(
        rules=RulesConfig(
            enable="all",
            disable=(),
            overrides={"A03": RuleOverride(severity="info")},
        )
    )
    project = ProjectContext(project_root=tmp_path, scan_path=tmp_path, files=(), config=config)
    ctx = make_file_ctx(project, relpath="src/example.py", content="# We need to ensure this is closed\nx = 1\n")
    violations = detect(project, [ctx])
    a03 = [v for v in violations if v.rule_id == "A03"]
    assert a03 and all(v.severity == "info" for v in a03)


def test_engine_filters_by_changed_lines(tmp_path: Path) -> None:
    config = SlopSentinelConfig()
    project = ProjectContext(project_root=tmp_path, scan_path=tmp_path, files=(), config=config)
    ctx = make_file_ctx(project, relpath="src/example.py", content="# We need to ensure this is closed\nx = 1\n")
    changed_lines = {ctx.path.resolve(): {2}}  # violation is on line 1
    violations = detect(project, [ctx], changed_lines=changed_lines)
    assert all(v.rule_id != "A03" for v in violations)


def test_json_and_sarif_reporters_produce_valid_json(tmp_path: Path) -> None:
    config = SlopSentinelConfig()
    project = ProjectContext(project_root=tmp_path, scan_path=tmp_path, files=(), config=config)
    ctx = make_file_ctx(project, relpath="src/example.py", content="# We need to ensure this is closed\nx = 1\n")
    violations = detect(project, [ctx])
    summary = summarize(files_scanned=1, violations=violations)

    payload = json.loads(render_json(summary, project_root=tmp_path))
    assert payload["tool"]["name"] == "SlopSentinel"
    assert "violations" in payload

    sarif = json.loads(render_sarif(list(summary.violations), project_root=tmp_path))
    assert sarif["version"] == "2.1.0"
    assert sarif["runs"][0]["tool"]["driver"]["name"] == "SlopSentinel"
