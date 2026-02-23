from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

from slopsentinel.reporters.json_reporter import parse_json_report


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: custom_markdown.py <scan.json | ->", file=sys.stderr)
        return 2

    raw = sys.stdin.read() if argv[1] == "-" else Path(argv[1]).read_text(encoding="utf-8")
    try:
        summary = parse_json_report(raw, project_root=Path.cwd())
    except Exception as exc:  # noqa: BLE001
        print(f"Invalid SlopSentinel JSON report: {exc}", file=sys.stderr)
        return 2

    by_rule = Counter(v.rule_id for v in summary.violations)
    lines: list[str] = []
    lines.append("# SlopSentinel summary")
    lines.append("")
    lines.append(f"- Score: **{summary.score}/100**")
    lines.append(f"- Files scanned: **{summary.files_scanned}**")
    lines.append(f"- Violations: **{len(summary.violations)}**")
    lines.append("")

    if not summary.violations:
        lines.append("No violations found.")
        lines.append("")
        print("\n".join(lines))
        return 0

    lines.append("## Violations by rule")
    lines.append("")
    lines.append("| Rule | Count |")
    lines.append("| --- | ---: |")
    for rule_id, count in by_rule.most_common():
        lines.append(f"| `{rule_id}` | {count} |")
    lines.append("")

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
