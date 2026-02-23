from __future__ import annotations

import time
from pathlib import Path

from slopsentinel.engine.context import ProjectContext
from slopsentinel.rules.registry import builtin_rules
from slopsentinel.scanner import build_file_context_from_text


def _python_ctx(project: ProjectContext) -> object:
    path = project.project_root / "bench.py"
    content = (
        "# We need to ensure this is safe\n"
        "import os\n"
        "import sys\n"
        "\n"
        "def f(x):\n"
        "    # Initialize an empty list for results\n"
        "    results = []\n"
        "    if x is None:\n"
        "        return 0\n"
        "    if x == 0:\n"
        "        return 0\n"
        "    if x == 1:\n"
        "        return 1\n"
        "    if x == 2:\n"
        "        return 2\n"
        "    try:\n"
        "        return x / 1\n"
        "    except Exception:\n"
        "        pass\n"
    )
    return build_file_context_from_text(project, path, content)


def main() -> int:
    root = Path(".slopsentinel-bench-rules").resolve()
    project = ProjectContext(project_root=root, scan_path=root, files=(), config=None)  # type: ignore[arg-type]
    ctx = _python_ctx(project)
    if ctx is None:
        print("Failed to build benchmark context")
        return 2

    rules = list(builtin_rules())
    iters = 500

    print("SlopSentinel per-rule benchmark (rough)")
    print(f"Iterations per rule: {iters}")
    print()

    slow: list[tuple[float, str]] = []
    for rule in rules:
        start = time.perf_counter()
        for _ in range(iters):
            _ = rule.check_file(ctx)  # type: ignore[arg-type]
        elapsed = time.perf_counter() - start
        per = elapsed / iters
        slow.append((per, rule.meta.rule_id))

    for per, rule_id in sorted(slow, reverse=True)[:10]:
        print(f"{rule_id}: {per*1e3:>7.3f} ms/call")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
