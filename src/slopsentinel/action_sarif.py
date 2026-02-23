from __future__ import annotations

import sys
from pathlib import Path

from slopsentinel.engine.types import ScanSummary
from slopsentinel.reporters.sarif import render_sarif


def _eprint(message: str) -> None:
    print(message, file=sys.stderr)


def _maybe_write_sarif(
    *,
    enabled: bool,
    sarif_path_spec: str,
    summary: ScanSummary,
    project_root: Path,
    workspace: Path,
) -> str | None:
    if not enabled:
        return None

    if not sarif_path_spec:
        sarif_path_spec = "slopsentinel.sarif"

    raw = Path(sarif_path_spec)
    dest = raw if raw.is_absolute() else (workspace / raw)
    try:
        workspace_resolved = workspace.resolve()
        dest_resolved = dest.resolve()
        dest_resolved.relative_to(workspace_resolved)
    except (OSError, RuntimeError) as exc:
        _eprint(f"Failed to resolve SARIF path: {exc}")
        return None
    except ValueError:
        _eprint(f"Refusing to write SARIF outside of workspace: {dest}")
        return None

    try:
        dest_resolved.parent.mkdir(parents=True, exist_ok=True)
        dest_resolved.write_text(render_sarif(list(summary.violations), project_root=project_root), encoding="utf-8")
        rel = dest_resolved.relative_to(workspace_resolved).as_posix()
        return rel
    except OSError as exc:
        _eprint(f"Failed to write SARIF report: {exc}")
        return None
