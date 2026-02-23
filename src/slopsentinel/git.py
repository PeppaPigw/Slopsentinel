from __future__ import annotations

import subprocess
from pathlib import Path
from typing import IO, Any


class GitError(RuntimeError):
    """Raised when a required git operation fails or git is unavailable."""


def git_check_output(
    args: list[str],
    *,
    cwd: Path,
    stderr: int | IO[Any] | None = subprocess.STDOUT,
) -> str:
    """
    Run a git command and return its stdout.

    Args are passed without the leading `git` (e.g., `['status']`).
    """

    try:
        return subprocess.check_output(
            ["git", *args],
            cwd=str(cwd),
            stderr=stderr,
            text=True,
        )
    except subprocess.CalledProcessError as exc:  # pragma: no cover
        msg = (exc.output or "").strip()
        raise GitError(msg or f"git command failed: {' '.join(args)}") from exc
    except FileNotFoundError as exc:  # pragma: no cover
        raise GitError("git is unavailable") from exc


def git_check_call(
    args: list[str],
    *,
    cwd: Path,
    stdout: int | IO[Any] | None = subprocess.DEVNULL,
    stderr: int | IO[Any] | None = subprocess.DEVNULL,
) -> None:
    """
    Run a git command, raising GitError on failure.

    Args are passed without the leading `git` (e.g., `['fetch', ...]`).
    """

    try:
        subprocess.check_call(
            ["git", *args],
            cwd=str(cwd),
            stdout=stdout,
            stderr=stderr,
        )
    except subprocess.CalledProcessError as exc:  # pragma: no cover
        raise GitError(f"git command failed: {' '.join(args)}") from exc
    except FileNotFoundError as exc:  # pragma: no cover
        raise GitError("git is unavailable") from exc


def git_root(*, cwd: Path) -> Path | None:
    """
    Return the git repository root for `cwd`, or None when unavailable.

    This is a best-effort helper for UX features like project root detection,
    where missing git should not be treated as a hard error.
    """

    try:
        out = git_check_output(["rev-parse", "--show-toplevel"], cwd=cwd, stderr=subprocess.DEVNULL).strip()
    except (GitError, NotADirectoryError, PermissionError):
        return None
    if not out:
        return None
    return Path(out)
