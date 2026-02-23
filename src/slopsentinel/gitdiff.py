from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from slopsentinel.git import GitError, git_check_output


@dataclass(frozen=True, slots=True)
class DiffHunk:
    path: Path
    added_lines: frozenset[int]


_HUNK_RE = re.compile(r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? \+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@")


def git_root(cwd: Path) -> Path:
    out = git_check_output(["rev-parse", "--show-toplevel"], cwd=cwd).strip()
    return Path(out)


def changed_lines_since(base: str, *, cwd: Path, scope: Path | None = None) -> dict[Path, set[int]]:
    """
    Return a mapping of file path -> set of line numbers (1-based) that are added/modified
    compared to `base...HEAD`.

    Uses `--unified=0` to keep parsing stable and avoid needing context.
    """

    return changed_lines_between(base, "HEAD", cwd=cwd, scope=scope)


def changed_lines_staged(*, cwd: Path, scope: Path | None = None) -> dict[Path, set[int]]:
    """
    Return a mapping of file path -> set of line numbers (1-based) that are staged.

    Equivalent to parsing `git diff --cached --unified=0`.
    """

    root = git_root(cwd)
    pathspec: str | None = None
    if scope is not None:
        try:
            rel = scope.resolve().relative_to(root.resolve())
            if rel.as_posix() not in {"", "."}:
                pathspec = rel.as_posix()
        except (ValueError, OSError, RuntimeError):
            pathspec = None

    try:
        args = ["diff", "--cached", "--unified=0", "--no-color", "--"]
        if pathspec:
            args.append(pathspec)
        diff_text = git_check_output(args, cwd=root)
    except GitError as exc:  # pragma: no cover
        msg = str(exc).strip()
        raise GitError(msg or "git diff --cached failed") from exc

    current_path: Path | None = None
    result: dict[Path, set[int]] = {}

    for raw_line in diff_text.splitlines():
        if raw_line.startswith("+++ "):
            # "+++ b/path" or "+++ /dev/null"
            plus_path = raw_line[4:].strip()
            if plus_path == "/dev/null":
                current_path = None
                continue
            if plus_path.startswith("b/"):
                plus_path = plus_path[2:]
            current_path = (root / plus_path).resolve()
            continue

        if current_path is None:
            continue

        m = _HUNK_RE.match(raw_line)
        if not m:
            continue

        new_start = int(m.group("new_start"))
        new_count = int(m.group("new_count") or "1")
        if new_count <= 0:
            continue

        lines = result.setdefault(current_path, set())
        for line_no in range(new_start, new_start + new_count):
            lines.add(line_no)

    return result


def changed_lines_between(base: str, head: str, *, cwd: Path, scope: Path | None = None) -> dict[Path, set[int]]:
    """
    Return a mapping of file path -> set of line numbers (1-based) that are added/modified
    compared to `base...head`.

    Uses `--unified=0` to keep parsing stable and avoid needing context.
    """

    root = git_root(cwd)
    pathspec: str | None = None
    if scope is not None:
        try:
            rel = scope.resolve().relative_to(root.resolve())
            if rel.as_posix() not in {"", "."}:
                pathspec = rel.as_posix()
        except (ValueError, OSError, RuntimeError):
            pathspec = None
    try:
        args = ["diff", "--unified=0", "--no-color", f"{base}...{head}", "--"]
        if pathspec:
            args.append(pathspec)
        diff_text = git_check_output(args, cwd=root)
    except GitError as exc:  # pragma: no cover
        msg = str(exc).strip()
        raise GitError(msg or f"git diff failed for base={base!r} head={head!r}") from exc

    current_path: Path | None = None
    result: dict[Path, set[int]] = {}

    for raw_line in diff_text.splitlines():
        if raw_line.startswith("+++ "):
            # "+++ b/path" or "+++ /dev/null"
            plus_path = raw_line[4:].strip()
            if plus_path == "/dev/null":
                current_path = None
                continue
            if plus_path.startswith("b/"):
                plus_path = plus_path[2:]
            current_path = (root / plus_path).resolve()
            continue

        if current_path is None:
            continue

        m = _HUNK_RE.match(raw_line)
        if not m:
            continue

        new_start = int(m.group("new_start"))
        new_count = int(m.group("new_count") or "1")
        if new_count <= 0:
            continue

        lines = result.setdefault(current_path, set())
        for line_no in range(new_start, new_start + new_count):
            lines.add(line_no)

    return result
