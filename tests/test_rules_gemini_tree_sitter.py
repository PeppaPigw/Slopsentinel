from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from slopsentinel.config import SlopSentinelConfig
from slopsentinel.engine.context import FileContext, ProjectContext
from slopsentinel.rules.gemini import D03NestedTernaryExpression, D04AsyncWithoutAwait
from slopsentinel.suppressions import parse_suppressions


@dataclass
class _Tree:
    root_node: object


class _Node:
    def __init__(
        self,
        node_type: str,
        *,
        children: list[_Node] | None = None,
        start_point: tuple[int, int] = (0, 0),
        start_byte: int = 0,
        end_byte: int = 0,
    ) -> None:
        self.type = node_type
        self.children = children or []
        self.start_point = start_point
        self.start_byte = start_byte
        self.end_byte = end_byte


def _make_ctx(tmp_path: Path, *, relpath: str, text: str, root: _Node) -> FileContext:
    project = ProjectContext(project_root=tmp_path, scan_path=tmp_path, files=(), config=SlopSentinelConfig())
    path = tmp_path / relpath
    lines = tuple(text.splitlines(keepends=True))
    suppressions = parse_suppressions(lines)
    return FileContext(
        project_root=project.project_root,
        path=path,
        relative_path=relpath,
        language="typescript",
        text=text,
        lines=lines,
        suppressions=suppressions,
        python_ast=None,
        syntax_tree=_Tree(root_node=root),
        tree_sitter_language="typescript",
    )


def test_d03_nested_ternary_tree_sitter_detects_depth_gt_2(tmp_path: Path) -> None:
    deep3 = _Node("conditional_expression", start_point=(3, 0))
    deep2 = _Node("conditional_expression", children=[deep3], start_point=(2, 0))
    deep1 = _Node("conditional_expression", children=[deep2], start_point=(1, 0))
    root = _Node("program", children=[deep1])
    ctx = _make_ctx(tmp_path, relpath="src/example.ts", text="x\n", root=root)
    violations = D03NestedTernaryExpression().check_file(ctx)
    assert any(v.rule_id == "D03" for v in violations)


def test_d03_nested_ternary_tree_sitter_depth_2_is_not_flagged(tmp_path: Path) -> None:
    depth2 = _Node("conditional_expression", children=[_Node("conditional_expression")], start_point=(1, 0))
    root = _Node("program", children=[depth2])
    ctx = _make_ctx(tmp_path, relpath="src/example.ts", text="x\n", root=root)
    assert D03NestedTernaryExpression().check_file(ctx) == []


def test_d04_async_without_await_tree_sitter_detects_async_functions(tmp_path: Path) -> None:
    text = "async function f() { return 1; }\n"
    raw = text.encode("utf-8", errors="replace")
    fn = _Node("function_declaration", start_byte=0, end_byte=len(raw), start_point=(0, 0))
    root = _Node("program", children=[fn])
    ctx = _make_ctx(tmp_path, relpath="src/example.ts", text=text, root=root)
    violations = D04AsyncWithoutAwait().check_file(ctx)
    assert any(v.rule_id == "D04" for v in violations)


def test_d04_async_without_await_tree_sitter_ignores_functions_with_await(tmp_path: Path) -> None:
    text = "async function f() { await g(); }\n"
    raw = text.encode("utf-8", errors="replace")
    await_node = _Node("await_expression", start_byte=0, end_byte=0)
    fn = _Node("function_declaration", children=[await_node], start_byte=0, end_byte=len(raw), start_point=(0, 0))
    root = _Node("program", children=[fn])
    ctx = _make_ctx(tmp_path, relpath="src/example.ts", text=text, root=root)
    assert D04AsyncWithoutAwait().check_file(ctx) == []
