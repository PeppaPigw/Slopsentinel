from __future__ import annotations

from pathlib import Path

from slopsentinel.engine.types import Violation
from slopsentinel.utils import safe_relpath


def render_github_annotations(violations: list[Violation], *, project_root: Path) -> str:
    lines: list[str] = []
    for v in violations:
        level = _level(v.severity)
        if v.location is None or v.location.path is None or v.location.start_line is None:
            lines.append(f"::{level}::{v.rule_id} {v.message}")
            continue

        path = safe_relpath(v.location.path, project_root)
        line = v.location.start_line
        col = v.location.start_col or 1
        msg = f"{v.rule_id} {v.message}"
        lines.append(f"::{level} file={path},line={line},col={col}::{msg}")
    return "\n".join(lines)


def _level(severity: str) -> str:
    if severity == "error":
        return "error"
    if severity == "warn":
        return "warning"
    return "notice"
