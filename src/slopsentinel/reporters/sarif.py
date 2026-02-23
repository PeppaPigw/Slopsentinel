from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from slopsentinel import __version__
from slopsentinel.engine.types import Violation
from slopsentinel.rules.registry import rule_meta_by_id
from slopsentinel.utils import safe_relpath

SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"


def render_sarif(violations: list[Violation], *, project_root: Path) -> str:
    meta = rule_meta_by_id()

    driver_rules: list[dict[str, Any]] = []
    rule_index: dict[str, int] = {}
    for idx, (rule_id, m) in enumerate(sorted(meta.items())):
        rule_index[rule_id] = idx
        driver_rules.append(
            {
                "id": rule_id,
                "name": m.title,
                "shortDescription": {"text": m.title},
                "fullDescription": {"text": m.description},
                "help": {"text": m.description},
                "defaultConfiguration": {"level": _sarif_level(m.default_severity)},
                "properties": {
                    "defaultSeverity": m.default_severity,
                    "dimension": m.score_dimension,
                    "fingerprintModel": m.fingerprint_model,
                },
            }
        )

    results: list[dict[str, Any]] = []
    for v in violations:
        res = _result(v, project_root=project_root, rule_index=rule_index)
        # GitHub Code Scanning requires at least one physical location.
        # Some project-level checks (or coarse heuristics) may not have a stable
        # file/line mapping; omit them from SARIF to keep uploads valid.
        if "locations" not in res:
            continue
        results.append(res)

    sarif = {
        "$schema": SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {"driver": {"name": "SlopSentinel", "version": __version__, "rules": driver_rules}},
                "results": results,
            }
        ],
    }
    return json.dumps(sarif, indent=2, sort_keys=False)


def _result(v: Violation, *, project_root: Path, rule_index: dict[str, int]) -> dict[str, Any]:
    res: dict[str, Any] = {
        "ruleId": v.rule_id,
        "level": _sarif_level(v.severity),
        "message": {"text": v.message},
    }

    idx = rule_index.get(v.rule_id)
    if idx is not None:
        res["ruleIndex"] = idx

    properties: dict[str, Any] = {"dimension": v.dimension}
    if v.suggestion:
        properties["suggestion"] = v.suggestion
    res["properties"] = properties

    if v.location is not None and v.location.path is not None and v.location.start_line is not None:
        region: dict[str, Any] = {
            "startLine": v.location.start_line,
            "startColumn": v.location.start_col or 1,
        }
        if v.location.end_line is not None:
            region["endLine"] = v.location.end_line
        if v.location.end_col is not None:
            region["endColumn"] = v.location.end_col

        res["locations"] = [
            {
                "physicalLocation": {
                    "artifactLocation": {"uri": safe_relpath(v.location.path, project_root)},
                    "region": region,
                }
            }
        ]

    return res


def _sarif_level(severity: str) -> str:
    if severity == "error":
        return "error"
    if severity == "warn":
        return "warning"
    return "note"
