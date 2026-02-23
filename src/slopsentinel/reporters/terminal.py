from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from slopsentinel import __version__
from slopsentinel.engine.scoring import format_breakdown_terminal
from slopsentinel.engine.types import ScanSummary, Violation
from slopsentinel.utils import safe_relpath

_SEVERITY_ICON = {"error": "✖", "warn": "⚠", "info": "ℹ"}
_SEVERITY_STYLE = {"error": "bold red", "warn": "yellow", "info": "dim"}


def render_terminal(summary: ScanSummary, *, project_root: Path, console: Console, show_details: bool = True) -> None:
    header = Text()
    header.append("SlopSentinel ", style="bold")
    header.append(f"v{__version__}", style="dim")
    header.append(" — AI slop audit", style="dim")

    console.print(
        Panel(
            header,
            subtitle=f"Scanned {summary.files_scanned} files",
            border_style="cyan",
        )
    )

    if not show_details:
        _print_summary(summary, console=console)
        return

    by_file: dict[str, list[Violation]] = defaultdict(list)
    repo_level: list[Violation] = []

    for v in summary.violations:
        if v.location is None or v.location.path is None:
            repo_level.append(v)
            continue
        by_file[safe_relpath(v.location.path, project_root)].append(v)

    if repo_level:
        console.print(Text("Repository signals", style="bold"))
        for v in repo_level:
            _print_violation(console, v, file_lines=None)
        console.print()

    for file_path in sorted(by_file):
        console.print(Text(file_path, style="bold"))
        file_lines = _read_lines(project_root / file_path)
        for v in sorted(by_file[file_path], key=_sort_key):
            _print_violation(console, v, file_lines=file_lines)
        console.print()

    _print_summary(summary, console=console)


def _print_violation(console: Console, v: Violation, *, file_lines: list[str] | None) -> None:
    icon = _SEVERITY_ICON.get(v.severity, "•")
    style = _SEVERITY_STYLE.get(v.severity, "")

    loc = ""
    if v.location is not None and v.location.start_line is not None:
        loc = f"{v.location.start_line}"
        if v.location.start_col is not None:
            loc += f":{v.location.start_col}"

    line = Text()
    line.append(f"  {icon} ", style=style)
    line.append(v.rule_id, style="bold")
    if loc:
        line.append(f"  ({loc})", style="dim")
    line.append(f"  {v.message}")
    console.print(line)

    if file_lines is not None and v.location is not None and v.location.start_line is not None:
        idx = v.location.start_line - 1
        if 0 <= idx < len(file_lines):
            snippet = file_lines[idx].rstrip("\n")
            console.print(f"     {v.location.start_line:>4} │ {snippet}", style="dim")

    if v.suggestion:
        console.print(f"     → {v.suggestion}", style="dim")


def _print_summary(summary: ScanSummary, *, console: Console) -> None:
    console.print(Text("─" * 60, style="dim"))
    confidence = summary.ai_confidence.upper() if summary.ai_confidence else "UNKNOWN"
    console.print(
        Text(
            f"Score: {summary.score}/100 (AI confidence: {confidence})",
            style="bold",
        )
    )
    console.print(
        Text(
            f"Breakdown: {format_breakdown_terminal(summary.breakdown)}",
            style="dim",
        )
    )
    console.print(
        Text(
            f"Signals: density={summary.violation_density:.3f} clustering={summary.violation_clustering:.3f}",
            style="dim",
        )
    )
    if summary.dominant_fingerprints:
        console.print(Text(f"Dominant: {', '.join(summary.dominant_fingerprints)}", style="dim"))
    console.print(Text("─" * 60, style="dim"))


def _sort_key(v: Violation) -> tuple[int, int, str]:
    severity_rank = {"error": 0, "warn": 1, "info": 2}.get(v.severity, 3)
    line = v.location.start_line if v.location and v.location.start_line else 10**9
    return severity_rank, line, v.rule_id


def _read_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
