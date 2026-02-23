from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from slopsentinel.config import SlopSentinelConfig
from slopsentinel.suppressions import Suppressions


class SyntaxTree(Protocol):
    # tree-sitter Tree exposes `root_node`; we treat nodes structurally.
    root_node: Any


@dataclass(frozen=True, slots=True)
class ProjectContext:
    project_root: Path
    scan_path: Path
    files: tuple[Path, ...]
    config: SlopSentinelConfig


@dataclass(frozen=True, slots=True)
class FileContext:
    project_root: Path
    path: Path
    relative_path: str
    language: str
    text: str
    lines: tuple[str, ...]
    suppressions: Suppressions
    python_ast: ast.AST | None = None
    syntax_tree: SyntaxTree | None = None
    tree_sitter_language: str | None = None
