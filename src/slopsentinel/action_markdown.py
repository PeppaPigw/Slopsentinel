from __future__ import annotations

import os
from pathlib import Path

from slopsentinel.engine.scoring import format_breakdown_markdown
from slopsentinel.engine.types import ScanSummary, Violation


def _render_comment_body(items: list[Violation], *, marker: str) -> str:
    items = sorted(items, key=lambda v: ({"error": 0, "warn": 1, "info": 2}.get(v.severity, 3), v.rule_id))
    lines: list[str] = []
    lines.append("**SlopSentinel** found the following issue(s):")
    for v in items[:6]:
        icon = {"error": "✖", "warn": "⚠", "info": "ℹ"}.get(v.severity, "•")
        suggestion = f" — {v.suggestion}" if v.suggestion else ""
        lines.append(f"- {icon} `{v.rule_id}` {v.message}{suggestion}")

    if len(items) > 6:
        lines.append(f"- …and {len(items) - 6} more finding(s) on this line.")

    lines.append("")
    lines.append(marker)
    return "\n".join(lines)


def _write_step_summary(summary: ScanSummary) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    p = Path(path)

    md: list[str] = []
    md.append("## SlopSentinel report")
    md.append("")
    md.append(f"- Score: **{summary.score}/100**")
    md.append(f"- AI confidence: **{summary.ai_confidence.upper()}**")
    md.append(f"- Signals: density={summary.violation_density:.3f}, clustering={summary.violation_clustering:.3f}")
    md.append(f"- Breakdown: {format_breakdown_markdown(summary.breakdown)}")
    if summary.dominant_fingerprints:
        md.append(f"- Dominant fingerprints: {', '.join(summary.dominant_fingerprints)}")
    md.append("")
    md.append(f"- Findings: {len(summary.violations)}")
    md.append("")

    p.write_text("\n".join(md) + "\n", encoding="utf-8")
