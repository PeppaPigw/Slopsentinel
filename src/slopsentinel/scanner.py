from __future__ import annotations

import ast
import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from slopsentinel.config import SlopSentinelConfig, load_config, path_is_ignored
from slopsentinel.engine.context import FileContext, ProjectContext
from slopsentinel.engine.tree_sitter import parse as ts_parse
from slopsentinel.git import git_root
from slopsentinel.languages.registry import (
    allowed_extensions,
    detect_language,
    tree_sitter_language_for_path,
)
from slopsentinel.suppressions import parse_suppressions
from slopsentinel.utils import safe_relpath

DEFAULT_SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
}

SLOPSENTINEL_WORKERS_ENV = "SLOPSENTINEL_WORKERS"
DEFAULT_MAX_WORKERS = 32


@dataclass(frozen=True, slots=True)
class ScanTarget:
    project_root: Path
    scan_path: Path
    config: SlopSentinelConfig


def resolve_worker_count(
    raw_value: str | None,
    *,
    default: int | None = None,
    max_workers: int = DEFAULT_MAX_WORKERS,
) -> int:
    """
    Resolve a safe worker count from an env var-style string.

    - None/""/"auto" fall back to the default
    - Values <= 0 fall back to the default
    - Values above `max_workers` are clamped
    """

    cpu = os.cpu_count() or 1
    resolved_default = max(1, default if default is not None else (cpu * 2))
    if raw_value is None:
        return min(resolved_default, max_workers)

    normalized = raw_value.strip().lower()
    if not normalized or normalized in {"auto", "default"}:
        return min(resolved_default, max_workers)

    try:
        workers = int(normalized)
    except ValueError:
        return min(resolved_default, max_workers)

    if workers <= 0:
        return min(resolved_default, max_workers)
    return min(workers, max_workers)


def worker_count_from_env(*, default: int | None = None) -> int:
    return resolve_worker_count(os.environ.get(SLOPSENTINEL_WORKERS_ENV), default=default)


def prepare_target(scan_path: Path) -> ScanTarget:
    """
    Resolve project root and load configuration.

    Heuristic:
    - If inside a git repo, use git root.
    - Otherwise use the provided directory (or the file's parent).
    """

    scan_path = scan_path.resolve()
    project_root = _detect_project_root(scan_path)
    config = load_config(project_root)
    return ScanTarget(project_root=project_root, scan_path=scan_path, config=config)


def discover_files(target: ScanTarget) -> list[Path]:
    scan_path = target.scan_path
    root = target.project_root
    ignore_patterns = target.config.ignore.paths
    allowed_exts = allowed_extensions(target.config.languages)

    if scan_path.is_file():
        lang = detect_language(scan_path)
        if lang is None or scan_path.suffix.lower() not in allowed_exts:
            return []
        if path_is_ignored(scan_path, project_root=root, ignore_patterns=ignore_patterns):
            return []
        return [scan_path]

    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(scan_path, topdown=True):
        dirnames[:] = [d for d in dirnames if d not in DEFAULT_SKIP_DIRS]
        base = Path(dirpath)

        for filename in filenames:
            path = base / filename

            if path.suffix.lower() not in allowed_exts:
                continue

            lang = detect_language(path)
            if lang is None:
                continue

            if path_is_ignored(path, project_root=root, ignore_patterns=ignore_patterns):
                continue

            files.append(path)

    return sorted(set(files))


def build_project_context(target: ScanTarget, files: list[Path]) -> ProjectContext:
    return ProjectContext(
        project_root=target.project_root,
        scan_path=target.scan_path,
        files=tuple(files),
        config=target.config,
    )


def build_file_context(project: ProjectContext, path: Path) -> FileContext | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    return build_file_context_from_text(project, path, text)


def build_file_context_from_text(project: ProjectContext, path: Path, text: str) -> FileContext | None:
    language = detect_language(path)
    if language is None:
        return None

    lines_list = text.splitlines()
    suppressions = parse_suppressions(lines_list)
    lines = tuple(lines_list)

    python_ast: ast.AST | None = None
    syntax_tree = None
    tree_sitter_language = None
    if language == "python":
        try:
            python_ast = ast.parse(text)
        except SyntaxError:
            python_ast = None
        tree_sitter_language = "python"
    else:
        tree_sitter_language = tree_sitter_language_for_path(path, detected_language=language)

    if tree_sitter_language is not None:
        syntax_tree = ts_parse(tree_sitter_language, text)

    return FileContext(
        project_root=project.project_root,
        path=path,
        relative_path=safe_relpath(path, project.project_root),
        language=language,
        text=text,
        lines=lines,
        suppressions=suppressions,
        python_ast=python_ast,
        syntax_tree=syntax_tree,
        tree_sitter_language=tree_sitter_language,
    )


def build_file_contexts(
    project: ProjectContext,
    paths: list[Path],
    *,
    workers: int = 1,
    on_path_done: Callable[[Path], None] | None = None,
) -> list[FileContext]:
    """
    Build FileContext objects for paths, optionally in parallel.

    Ordering is deterministic: returned contexts follow the input `paths` order,
    with unreadable/unsupported files filtered out (matching serial behavior).
    """

    contexts: list[FileContext] = []
    if workers <= 1 or len(paths) <= 1:
        for path in paths:
            ctx = build_file_context(project, path)
            if on_path_done is not None:
                on_path_done(path)
            if ctx is not None:
                contexts.append(ctx)
        return contexts

    max_workers = min(max(1, workers), len(paths))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        build_ctx = partial(build_file_context, project)
        for path, ctx in zip(paths, executor.map(build_ctx, paths), strict=True):
            if on_path_done is not None:
                on_path_done(path)
            if ctx is not None:
                contexts.append(ctx)
    return contexts


def _detect_project_root(start: Path) -> Path:
    # Prefer the closest directory containing a pyproject.toml. This matches how
    # users expect per-project configuration to be discovered in monorepos.
    for candidate in [start if start.is_dir() else start.parent, *(start.parents)]:
        if (candidate / "pyproject.toml").exists():
            return candidate

    # Fall back to git root when available (works for subdirectories as well).
    root = git_root(cwd=start if start.is_dir() else start.parent)
    if root is not None:
        return root

    return start if start.is_dir() else start.parent
