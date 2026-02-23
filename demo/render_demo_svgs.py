from __future__ import annotations

import difflib
import sys
from pathlib import Path

from rich.console import Console
from rich.syntax import Syntax


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _demo_root() -> Path:
    return _repo_root() / "demo"


def _docs_dir() -> Path:
    return _repo_root() / "docs"


def _prompt(console: Console, command: str) -> None:
    console.print(f"$ {command}", style="bold green")
    console.print()


def _write_svg(console: Console, out_path: Path, *, title: str) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(console.export_svg(title=title), encoding="utf-8")


def _unified_diff(before: str, after: str, *, fromfile: str) -> str:
    if before == after:
        return ""
    diff = difflib.unified_diff(
        before.splitlines(keepends=False),
        after.splitlines(keepends=False),
        fromfile=fromfile,
        tofile=fromfile,
        lineterm="",
    )
    return "\n".join(diff)


def _ensure_importable() -> None:
    repo = _repo_root()
    sys.path.insert(0, str(repo / "src"))


def render_demo_scan_svg() -> None:
    _ensure_importable()
    from slopsentinel.audit import audit_path
    from slopsentinel.reporters.terminal import render_terminal

    console = Console(record=True, width=100)
    _prompt(console, "slop scan demo/")

    result = audit_path(_demo_root(), record_history=False)
    render_terminal(result.summary, project_root=result.target.project_root, console=console, show_details=True)
    _write_svg(console, _docs_dir() / "demo.svg", title="SlopSentinel demo: scan")


def render_demo_fix_svg() -> None:
    _ensure_importable()
    from slopsentinel.audit import audit_path
    from slopsentinel.autofix import apply_fixes

    demo_file = _demo_root() / "bad_code.py"
    original = demo_file.read_text(encoding="utf-8")

    audit = audit_path(demo_file, record_history=False)
    # Keep all violations; `apply_fixes` ignores unsupported rule ids.
    violations = list(audit.summary.violations)
    updated = apply_fixes(demo_file, original, violations)
    diff = _unified_diff(original, updated, fromfile="demo/bad_code.py")

    console = Console(record=True, width=100)
    _prompt(console, "slop fix demo/bad_code.py --dry-run")

    if diff:
        console.print(Syntax(diff, "diff", word_wrap=False))
    else:
        console.print("No changes needed.")

    _write_svg(console, _docs_dir() / "demo-fix.svg", title="SlopSentinel demo: fix")


def render_demo_trend_svg() -> None:
    _ensure_importable()
    from slopsentinel.engine.types import DimensionBreakdown
    from slopsentinel.history import HistoryEntry, render_trend_terminal

    entries = [
        HistoryEntry(
            timestamp="2026-02-19T12:00:00Z",
            score=48,
            files_scanned=12,
            violations=18,
            breakdown=DimensionBreakdown(fingerprint=12, quality=18, hallucination=8, maintainability=6, security=4),
            dominant_fingerprints=("claude", "copilot"),
            ai_confidence="high",
            git_head="deadbeef",
        ),
        HistoryEntry(
            timestamp="2026-02-20T12:00:00Z",
            score=58,
            files_scanned=12,
            violations=14,
            breakdown=DimensionBreakdown(fingerprint=10, quality=14, hallucination=6, maintainability=5, security=3),
            dominant_fingerprints=("claude",),
            ai_confidence="high",
            git_head="c0ffee00",
        ),
        HistoryEntry(
            timestamp="2026-02-21T12:00:00Z",
            score=66,
            files_scanned=12,
            violations=10,
            breakdown=DimensionBreakdown(fingerprint=8, quality=10, hallucination=4, maintainability=4, security=2),
            dominant_fingerprints=("claude",),
            ai_confidence="medium",
            git_head="f00dbabe",
        ),
        HistoryEntry(
            timestamp="2026-02-22T12:00:00Z",
            score=74,
            files_scanned=12,
            violations=7,
            breakdown=DimensionBreakdown(fingerprint=6, quality=7, hallucination=3, maintainability=3, security=1),
            dominant_fingerprints=("generic",),
            ai_confidence="medium",
            git_head="8badf00d",
        ),
        HistoryEntry(
            timestamp="2026-02-23T12:00:00Z",
            score=82,
            files_scanned=12,
            violations=4,
            breakdown=DimensionBreakdown(fingerprint=4, quality=4, hallucination=2, maintainability=2, security=0),
            dominant_fingerprints=("generic",),
            ai_confidence="low",
            git_head="1ee7c0de",
        ),
    ]

    console = Console(record=True, width=100)
    _prompt(console, "slop trend --path demo --format terminal --last 5")
    console.print(render_trend_terminal(entries, last=5))
    _write_svg(console, _docs_dir() / "demo-trend.svg", title="SlopSentinel demo: trend")


def main() -> None:
    render_demo_scan_svg()
    render_demo_fix_svg()
    render_demo_trend_svg()


if __name__ == "__main__":
    main()

