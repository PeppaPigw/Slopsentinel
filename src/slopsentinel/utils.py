from __future__ import annotations

from pathlib import Path


def safe_relpath(path: Path, root: Path) -> str:
    """
    Return a stable, POSIX-style path for reporting output.

    Prefer a path relative to `root` when possible.
    Fall back to `path.as_posix()` when the path is not under the root, or when
    either path cannot be resolved due to OS errors.
    """

    try:
        resolved_path = path.resolve()
    except OSError:
        resolved_path = path

    try:
        resolved_root = root.resolve()
    except OSError:
        resolved_root = root

    try:
        return resolved_path.relative_to(resolved_root).as_posix()
    except ValueError:
        return path.as_posix()

