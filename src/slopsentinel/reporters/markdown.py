from __future__ import annotations

from pathlib import Path

from slopsentinel.engine.scoring import format_breakdown_markdown
from slopsentinel.engine.types import ScanSummary, Violation
from slopsentinel.utils import safe_relpath


def render_markdown(summary: ScanSummary, *, project_root: Path) -> str:
    lines: list[str] = []
    lines.append("# SlopSentinel report")
    lines.append("")
    lines.append(f"- Score: **{summary.score}/100**")
    lines.append(f"- AI confidence: **{summary.ai_confidence.upper()}**")
    lines.append(f"- Scoring profile: `{summary.scoring_profile}`")
    lines.append(f"- Files scanned: {summary.files_scanned}")
    lines.append(f"- Findings: {len(summary.violations)}")
    lines.append(f"- Signals: density={summary.violation_density:.3f}, clustering={summary.violation_clustering:.3f}")
    lines.append(f"- Breakdown: {format_breakdown_markdown(summary.breakdown)}")
    if summary.dominant_fingerprints:
        lines.append(f"- Dominant fingerprints: {', '.join(summary.dominant_fingerprints)}")
    lines.append("")

    lines.append("## Violations")
    lines.append("")
    if not summary.violations:
        lines.append("No violations found.")
        lines.append("")
        return "\n".join(lines)

    lines.append("| File | Line | Rule | Severity | Dimension | Message |")
    lines.append("| --- | ---: | --- | --- | --- | --- |")

    for v in summary.violations:
        file_cell, line_cell = _format_location(v, project_root=project_root)
        rule_cell = f"`{v.rule_id}`"
        severity_cell = v.severity
        dimension_cell = v.dimension
        message_cell = _md_escape_cell(v.message)
        if v.suggestion:
            message_cell = f"{message_cell}<br/><span style=\"opacity:0.75\">{_md_escape_cell(v.suggestion)}</span>"
        lines.append(f"| {file_cell} | {line_cell} | {rule_cell} | {severity_cell} | {dimension_cell} | {message_cell} |")

    lines.append("")
    return "\n".join(lines)


def _format_location(v: Violation, *, project_root: Path) -> tuple[str, str]:
    if v.location is None or v.location.path is None or v.location.start_line is None:
        return "-", "-"
    return _md_escape_cell(safe_relpath(v.location.path, project_root)), str(int(v.location.start_line))


def _md_escape_cell(text: str) -> str:
    # Keep this conservative; Markdown tables break on pipes/newlines.
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ").strip()

