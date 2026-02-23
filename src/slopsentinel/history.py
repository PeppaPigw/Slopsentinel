from __future__ import annotations

import html
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from slopsentinel.engine.types import DimensionBreakdown, ScanSummary
from slopsentinel.git import GitError, git_check_output

HISTORY_VERSION = 1
DEFAULT_HISTORY_PATH = ".slopsentinel/history.json"


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    timestamp: str
    score: int
    files_scanned: int
    violations: int
    breakdown: DimensionBreakdown
    dominant_fingerprints: tuple[str, ...] = ()
    ai_confidence: str | None = None
    violation_density: float | None = None
    violation_clustering: float | None = None
    git_head: str | None = None


def record_entry(summary: ScanSummary, *, project_root: Path) -> HistoryEntry:
    head = _git_head(project_root)
    return HistoryEntry(
        timestamp=datetime.now(UTC).isoformat(),
        score=int(summary.score),
        files_scanned=int(summary.files_scanned),
        violations=len(summary.violations),
        breakdown=summary.breakdown,
        dominant_fingerprints=summary.dominant_fingerprints,
        ai_confidence=str(summary.ai_confidence) if summary.ai_confidence else None,
        violation_density=float(summary.violation_density),
        violation_clustering=float(summary.violation_clustering),
        git_head=head,
    )


def load_history(path: Path) -> list[HistoryEntry]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    if not isinstance(data, dict) or data.get("version") != HISTORY_VERSION:
        return []
    items = data.get("entries", [])
    if not isinstance(items, list):
        return []

    entries: list[HistoryEntry] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            entries.append(_parse_entry(item))
        except (TypeError, ValueError):
            continue
    return entries


def append_history(path: Path, entry: HistoryEntry, *, max_entries: int = 200) -> None:
    entries = load_history(path)
    entries.append(entry)
    entries = entries[-max_entries:]
    save_history(path, entries)


def save_history(path: Path, entries: list[HistoryEntry]) -> None:
    payload = {
        "version": HISTORY_VERSION,
        "entries": [_entry_to_json(e) for e in entries],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def render_trend_terminal(entries: list[HistoryEntry], *, last: int = 10) -> str:
    recent = entries[-last:]
    if not recent:
        return "No history recorded yet."

    lines: list[str] = []
    lines.append(f"History (last {len(recent)} runs):")
    for e in recent:
        head = f" {e.git_head[:8]}" if e.git_head else ""
        confidence = f"  confidence={e.ai_confidence}" if e.ai_confidence else ""
        lines.append(
            f"- {e.timestamp}{head}  score={e.score}  violations={e.violations}  files={e.files_scanned}{confidence}"
        )

    # Simple trend: compare first and last score in window.
    delta = recent[-1].score - recent[0].score
    lines.append(f"Trend: {delta:+d} (window)")
    return "\n".join(lines)


def render_trend_json(entries: list[HistoryEntry], *, last: int = 10) -> str:
    recent = entries[-last:]
    payload = {
        "version": HISTORY_VERSION,
        "last": int(last),
        "entries": [_entry_to_json(e) for e in recent],
        "trend": (int(recent[-1].score) - int(recent[0].score)) if recent else 0,
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def render_trend_html(entries: list[HistoryEntry], *, last: int = 25) -> str:
    recent = entries[-last:]
    title = "SlopSentinel Trend"

    # Simple SVG chart: score over time.
    width = 720
    height = 180
    pad = 24
    inner_w = max(1, width - pad * 2)
    inner_h = max(1, height - pad * 2)

    points: list[tuple[float, float]] = []
    if recent:
        for i, e in enumerate(recent):
            x = pad + (inner_w * (i / max(1, len(recent) - 1)))
            y = pad + (inner_h * (1.0 - (float(e.score) / 100.0)))
            points.append((x, y))

    def svg_polyline() -> str:
        if len(points) < 2:
            return ""
        coord = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
        return f'<polyline fill="none" stroke="#06b6d4" stroke-width="2" points="{coord}" />'

    def svg_points() -> str:
        out = []
        for (x, y), e in zip(points, recent, strict=False):
            out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="#0ea5e9"><title>{e.timestamp} score={e.score}</title></circle>')
        return "\n".join(out)

    rows = []
    for e in reversed(recent):
        head = html.escape(e.git_head[:8]) if e.git_head else "-"
        confidence = html.escape(e.ai_confidence or "-")
        rows.append(
            "<tr>"
            f"<td>{html.escape(e.timestamp)}</td>"
            f"<td>{head}</td>"
            f"<td>{int(e.score)}</td>"
            f"<td>{int(e.violations)}</td>"
            f"<td>{int(e.files_scanned)}</td>"
            f"<td>{confidence}</td>"
            "</tr>"
        )

    trend = (int(recent[-1].score) - int(recent[0].score)) if recent else 0
    trend_label = f"{trend:+d}"

    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '<meta charset="utf-8" />',
            f"<title>{html.escape(title)}</title>",
            '<meta name="viewport" content="width=device-width, initial-scale=1" />',
            "<style>",
            "body{font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Arial;max-width:980px;margin:24px auto;padding:0 16px;color:#0f172a}",
            "h1{font-size:20px;margin:0 0 12px 0}",
            ".muted{color:#475569}",
            "table{border-collapse:collapse;width:100%;font-size:13px}",
            "th,td{border-bottom:1px solid #e2e8f0;padding:8px 6px;text-align:left;vertical-align:top}",
            "th{position:sticky;top:0;background:#fff}",
            ".card{border:1px solid #e2e8f0;border-radius:12px;padding:12px;margin:12px 0;background:#fff}",
            "</style>",
            "</head>",
            "<body>",
            f"<h1>{html.escape(title)}</h1>",
            f'<div class="muted">Last {len(recent)} runs · Trend (window): {html.escape(trend_label)}</div>',
            '<div class="card">',
            f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" role="img" aria-label="Score trend chart">',
            f'<rect x="0" y="0" width="{width}" height="{height}" fill="#f8fafc" />',
            svg_polyline(),
            svg_points(),
            "</svg>",
            "</div>",
            '<div class="card">',
            "<table>",
            "<thead><tr><th>Timestamp</th><th>Git</th><th>Score</th><th>Violations</th><th>Files</th><th>Confidence</th></tr></thead>",
            "<tbody>",
            *rows,
            "</tbody></table>",
            "</div>",
            "</body></html>",
        ]
    )


def _parse_entry(item: dict[str, Any]) -> HistoryEntry:
    ts = str(item["timestamp"])
    score = int(item["score"])
    files_scanned = int(item["files_scanned"])
    violations = int(item["violations"])

    bd = item["breakdown"]
    if not isinstance(bd, dict):
        raise TypeError("breakdown must be a dict")
    breakdown = DimensionBreakdown(
        fingerprint=int(bd["fingerprint"]),
        quality=int(bd["quality"]),
        hallucination=int(bd["hallucination"]),
        maintainability=int(bd["maintainability"]),
        security=int(bd["security"]),
    )

    dominant = item.get("dominant_fingerprints", [])
    dominant_fingerprints = tuple(dominant) if isinstance(dominant, list) else ()
    ai_confidence = item.get("ai_confidence")
    if ai_confidence is not None and not isinstance(ai_confidence, str):
        ai_confidence = None
    violation_density = item.get("violation_density")
    if violation_density is not None and not isinstance(violation_density, int | float):
        violation_density = None
    violation_clustering = item.get("violation_clustering")
    if violation_clustering is not None and not isinstance(violation_clustering, int | float):
        violation_clustering = None
    git_head = item.get("git_head")
    if git_head is not None and not isinstance(git_head, str):
        git_head = None

    return HistoryEntry(
        timestamp=ts,
        score=score,
        files_scanned=files_scanned,
        violations=violations,
        breakdown=breakdown,
        dominant_fingerprints=dominant_fingerprints,
        ai_confidence=ai_confidence,
        violation_density=float(violation_density) if violation_density is not None else None,
        violation_clustering=float(violation_clustering) if violation_clustering is not None else None,
        git_head=git_head,
    )


def _entry_to_json(e: HistoryEntry) -> dict[str, Any]:
    return {
        "timestamp": e.timestamp,
        "score": e.score,
        "files_scanned": e.files_scanned,
        "violations": e.violations,
        "breakdown": {
            "fingerprint": e.breakdown.fingerprint,
            "quality": e.breakdown.quality,
            "hallucination": e.breakdown.hallucination,
            "maintainability": e.breakdown.maintainability,
            "security": e.breakdown.security,
        },
        "dominant_fingerprints": list(e.dominant_fingerprints),
        "ai_confidence": e.ai_confidence,
        "violation_density": e.violation_density,
        "violation_clustering": e.violation_clustering,
        "git_head": e.git_head,
    }


def _git_head(project_root: Path) -> str | None:
    try:
        return git_check_output(["rev-parse", "HEAD"], cwd=project_root).strip() or None
    except GitError:
        return None
