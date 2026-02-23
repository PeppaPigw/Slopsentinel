from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from slopsentinel import __version__
from slopsentinel.engine.types import DimensionBreakdown, Location, ScanSummary, Violation
from slopsentinel.utils import safe_relpath

REPORT_SCHEMA_VERSION = 2
REPORT_SCHEMA_URI = "schemas/slopsentinel-report.schema.json"


def render_json(summary: ScanSummary, *, project_root: Path) -> str:
    payload = {
        "$schema": REPORT_SCHEMA_URI,
        "schema_version": REPORT_SCHEMA_VERSION,
        "tool": {"name": "SlopSentinel", "version": __version__},
        "score": summary.score,
        "ai_confidence": summary.ai_confidence,
        "files_scanned": summary.files_scanned,
        "scoring_profile": summary.scoring_profile,
        "signals": {
            "density": summary.violation_density,
            "clustering": summary.violation_clustering,
        },
        "breakdown": {
            "fingerprint": summary.breakdown.fingerprint,
            "quality": summary.breakdown.quality,
            "hallucination": summary.breakdown.hallucination,
            "maintainability": summary.breakdown.maintainability,
            "security": summary.breakdown.security,
        },
        "dominant_fingerprints": list(summary.dominant_fingerprints),
        "violations": [_violation_to_dict(v, project_root=project_root) for v in summary.violations],
    }
    return json.dumps(payload, indent=2, sort_keys=False)


def _violation_to_dict(v: Violation, *, project_root: Path) -> dict[str, Any]:
    loc = None
    if v.location is not None and v.location.path is not None:
        loc = {
            "path": safe_relpath(v.location.path, project_root),
            "start_line": v.location.start_line,
            "start_col": v.location.start_col,
            "end_line": v.location.end_line,
            "end_col": v.location.end_col,
        }

    return {
        "rule_id": v.rule_id,
        "severity": v.severity,
        "dimension": v.dimension,
        "message": v.message,
        "suggestion": v.suggestion,
        "location": loc,
    }


def parse_json_report(text: str, *, project_root: Path) -> ScanSummary:
    """
    Parse a JSON report produced by `render_json()` back into a `ScanSummary`.

    This powers `slopsentinel report` / `slopsentinel compare`, which need to
    re-render or diff existing scan results without re-scanning.
    """

    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("JSON report must be an object.")

    raw_score = data.get("score")
    raw_files = data.get("files_scanned")
    if not isinstance(raw_score, int) or not isinstance(raw_files, int):
        raise ValueError("JSON report missing required fields: score/files_scanned.")

    breakdown_raw = data.get("breakdown", {})
    if not isinstance(breakdown_raw, dict):
        breakdown_raw = {}
    breakdown = DimensionBreakdown(
        fingerprint=int(breakdown_raw.get("fingerprint", 0) or 0),
        quality=int(breakdown_raw.get("quality", 0) or 0),
        hallucination=int(breakdown_raw.get("hallucination", 0) or 0),
        maintainability=int(breakdown_raw.get("maintainability", 0) or 0),
        security=int(breakdown_raw.get("security", 0) or 0),
    )

    dominant_raw = data.get("dominant_fingerprints", [])
    dominant = tuple(str(x) for x in dominant_raw) if isinstance(dominant_raw, list) else ()

    ai_confidence_raw = data.get("ai_confidence", "low")
    ai_confidence = str(ai_confidence_raw).strip().lower()
    if ai_confidence not in {"low", "medium", "high"}:
        ai_confidence = "low"

    signals_raw = data.get("signals", {})
    density = 0.0
    clustering = 0.0
    if isinstance(signals_raw, dict):
        raw_density = signals_raw.get("density")
        raw_clustering = signals_raw.get("clustering")
        if isinstance(raw_density, int | float):
            density = float(raw_density)
        if isinstance(raw_clustering, int | float):
            clustering = float(raw_clustering)

    scoring_profile_raw = data.get("scoring_profile", "default")
    scoring_profile = str(scoring_profile_raw) if isinstance(scoring_profile_raw, str) else "default"

    violations_raw = data.get("violations", [])
    if not isinstance(violations_raw, list):
        raise ValueError("JSON report `violations` must be a list.")
    violations = tuple(_parse_violation(item, project_root=project_root) for item in violations_raw if isinstance(item, dict))

    return ScanSummary(
        files_scanned=int(raw_files),
        violations=violations,
        score=int(raw_score),
        breakdown=breakdown,
        dominant_fingerprints=dominant,
        ai_confidence=ai_confidence,  # type: ignore[arg-type]
        violation_density=float(density),
        violation_clustering=float(clustering),
        scoring_profile=scoring_profile,
    )


def _parse_violation(item: dict[str, Any], *, project_root: Path) -> Violation:
    rule_id = str(item.get("rule_id", "")).strip().upper()
    severity = str(item.get("severity", "info")).strip().lower()
    if severity == "warning":
        severity = "warn"
    if severity not in {"info", "warn", "error"}:
        severity = "info"

    dimension = str(item.get("dimension", "quality")).strip().lower()
    if dimension not in {"fingerprint", "quality", "hallucination", "maintainability", "security"}:
        dimension = "quality"

    message = str(item.get("message", ""))
    suggestion = item.get("suggestion")
    if not isinstance(suggestion, str):
        suggestion = None

    loc = None
    raw_loc = item.get("location")
    if isinstance(raw_loc, dict):
        raw_path = raw_loc.get("path")
        raw_start_line = raw_loc.get("start_line")
        raw_start_col = raw_loc.get("start_col")
        raw_end_line = raw_loc.get("end_line")
        raw_end_col = raw_loc.get("end_col")

        path: Path | None = None
        if isinstance(raw_path, str) and raw_path:
            candidate = Path(raw_path)
            path = candidate if candidate.is_absolute() else (project_root / candidate)

        start_line = int(raw_start_line) if isinstance(raw_start_line, int) and raw_start_line > 0 else None
        start_col = int(raw_start_col) if isinstance(raw_start_col, int) and raw_start_col > 0 else None
        end_line = int(raw_end_line) if isinstance(raw_end_line, int) and raw_end_line > 0 else None
        end_col = int(raw_end_col) if isinstance(raw_end_col, int) and raw_end_col > 0 else None

        if path is not None and start_line is not None:
            loc = Location(path=path, start_line=start_line, start_col=start_col, end_line=end_line, end_col=end_col)

    return Violation(
        rule_id=rule_id,
        severity=severity,  # type: ignore[arg-type]
        dimension=dimension,  # type: ignore[arg-type]
        message=message,
        suggestion=suggestion,
        location=loc,
    )
