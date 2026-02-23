from __future__ import annotations

import json
from pathlib import Path

from helpers import make_file_ctx

from slopsentinel.config import SlopSentinelConfig
from slopsentinel.engine.context import ProjectContext
from slopsentinel.engine.detection import detect
from slopsentinel.engine.scoring import summarize
from slopsentinel.reporters.json_reporter import (
    REPORT_SCHEMA_URI,
    REPORT_SCHEMA_VERSION,
    render_json,
)
from slopsentinel.reporters.sarif import render_sarif


def test_json_report_includes_schema_version(tmp_path: Path) -> None:
    project = ProjectContext(project_root=tmp_path, scan_path=tmp_path, files=(), config=SlopSentinelConfig())
    ctx = make_file_ctx(project, relpath="src/example.py", content="# We need to ensure this is closed\nx = 1\n")
    summary = summarize(files_scanned=1, violations=detect(project, [ctx]))

    payload = json.loads(render_json(summary, project_root=tmp_path))
    assert payload["$schema"] == REPORT_SCHEMA_URI
    assert payload["schema_version"] == REPORT_SCHEMA_VERSION


def test_report_schema_file_is_valid_json() -> None:
    schema_path = Path("schemas") / "slopsentinel-report.schema.json"
    assert schema_path.exists()
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema.get("$schema", "").startswith("https://json-schema.org/")
    assert schema.get("title") == "SlopSentinel scan report"


def test_sarif_includes_rule_index_and_default_configuration(tmp_path: Path) -> None:
    project = ProjectContext(project_root=tmp_path, scan_path=tmp_path, files=(), config=SlopSentinelConfig())
    ctx = make_file_ctx(project, relpath="src/example.py", content="# We need to ensure this is closed\nx = 1\n")
    summary = summarize(files_scanned=1, violations=detect(project, [ctx]))

    sarif = json.loads(render_sarif(list(summary.violations), project_root=tmp_path))
    run = sarif["runs"][0]
    driver_rules = run["tool"]["driver"]["rules"]
    rule_ids = [r["id"] for r in driver_rules]
    assert "A03" in rule_ids

    a03_index = rule_ids.index("A03")
    a03_rule = driver_rules[a03_index]
    assert a03_rule["defaultConfiguration"]["level"] in {"note", "warning", "error"}

    results = [r for r in run["results"] if r.get("ruleId") == "A03"]
    assert results
    assert results[0]["ruleIndex"] == a03_index

    loc = results[0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
    assert loc == "src/example.py"
