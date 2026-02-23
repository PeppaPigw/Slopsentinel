from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from slopsentinel.engine.context import FileContext
from slopsentinel.engine.types import Violation
from slopsentinel.patterns import COMPREHENSIVE_RE
from slopsentinel.rules.base import BaseRule, RuleMeta, loc_from_line
from slopsentinel.rules.utils import iter_comment_lines


def _is_python_test_file(ctx: FileContext) -> bool:
    rel = ctx.relative_path.replace("\\", "/").lower()
    name = Path(rel).name
    if rel.startswith("tests/") or "/tests/" in rel:
        return True
    if name.startswith("test_") or name.endswith("_test.py"):
        return True
    return False


@dataclass(frozen=True, slots=True)
class D01ComprehensiveIntroComment(BaseRule):
    meta = RuleMeta(
        rule_id="D01",
        title="Comprehensive intro comment",
        description="Gemini-style 'Here's a comprehensive...' preambles are often AI artifacts.",
        default_severity="warn",
        score_dimension="fingerprint",
        fingerprint_model="gemini",
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        for line_no, line in iter_comment_lines(ctx):
            if COMPREHENSIVE_RE.search(line):
                return [
                    self._violation(
                        message="Found 'Here's a comprehensive...' style comment.",
                        suggestion="Remove marketing-style preambles; keep comments precise and task-focused.",
                        location=loc_from_line(ctx, line=line_no),
                    )
                ]
        return []


@dataclass(frozen=True, slots=True)
class D02DebugPrintSpray(BaseRule):
    meta = RuleMeta(
        rule_id="D02",
        title="Overuse of print()",
        description="Many print() calls left in non-test code are often debugging artifacts.",
        default_severity="warn",
        score_dimension="quality",
        fingerprint_model="gemini",
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "python" or ctx.python_ast is None:
            return []
        if _is_python_test_file(ctx):
            return []

        import ast

        count = 0
        first_line: int | None = None
        for node in ast.walk(ctx.python_ast):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name) or node.func.id != "print":
                continue
            count += 1
            if first_line is None and hasattr(node, "lineno"):
                first_line = int(getattr(node, "lineno", 0) or 0) or None

        if count < 5:
            return []

        return [
            self._violation(
                message=f"Found {count} print() calls in one file.",
                suggestion="Remove debug prints or replace them with structured logging behind a debug flag.",
                location=loc_from_line(ctx, line=first_line or 1),
            )
        ]


@dataclass(frozen=True, slots=True)
class D03NestedTernaryExpression(BaseRule):
    meta = RuleMeta(
        rule_id="D03",
        title="Nested ternary expression",
        description="Nested ternaries (>2 levels) harm readability and often appear in AI output.",
        default_severity="warn",
        score_dimension="fingerprint",
        fingerprint_model="gemini",
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language == "python" and ctx.python_ast is not None:
            return _check_python_nested_ternary(self, ctx)
        if ctx.syntax_tree is not None and (ctx.tree_sitter_language in {"javascript", "typescript", "tsx"}):
            return _check_tree_sitter_nested_ternary(self, ctx)
        return []


@dataclass(frozen=True, slots=True)
class D04AsyncWithoutAwait(BaseRule):
    meta = RuleMeta(
        rule_id="D04",
        title="Async function without await",
        description="Async functions without await indicate cargo-cult async usage.",
        default_severity="warn",
        score_dimension="fingerprint",
        fingerprint_model="gemini",
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language == "python" and ctx.python_ast is not None:
            return _check_python_async_without_await(self, ctx)
        if ctx.syntax_tree is not None and (ctx.tree_sitter_language in {"javascript", "typescript", "tsx"}):
            return _check_tree_sitter_async_without_await(self, ctx)
        return []


@dataclass(frozen=True, slots=True)
class D05GlobalKeywordUsed(BaseRule):
    meta = RuleMeta(
        rule_id="D05",
        title="Use of global keyword",
        description="Using `global` inside functions is fragile and commonly appears in AI-generated code.",
        default_severity="warn",
        score_dimension="maintainability",
        fingerprint_model="gemini",
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "python" or ctx.python_ast is None:
            return []

        import ast

        violations: list[Violation] = []
        for node in ast.walk(ctx.python_ast):
            if not isinstance(node, ast.Global):
                continue
            line_no = int(getattr(node, "lineno", 0) or 0) or 1
            violations.append(
                self._violation(
                    message="Found `global` declaration inside a function.",
                    suggestion="Avoid global state; pass values explicitly or encapsulate state in objects.",
                    location=loc_from_line(ctx, line=line_no),
                )
            )
            if len(violations) >= 10:
                break
        return violations


@dataclass(frozen=True, slots=True)
class D06ExecEvalUsed(BaseRule):
    meta = RuleMeta(
        rule_id="D06",
        title="exec/eval used",
        description="Use of exec/eval is a security risk and frequently unsafe in AI-generated code.",
        default_severity="error",
        score_dimension="security",
        fingerprint_model="gemini",
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "python" or ctx.python_ast is None:
            return []

        import ast

        violations: list[Violation] = []
        for node in ast.walk(ctx.python_ast):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name) or node.func.id not in {"exec", "eval"}:
                continue
            func_name = node.func.id
            line_no = int(getattr(node, "lineno", 0) or 0) or 1
            violations.append(
                self._violation(
                    message=f"Found `{func_name}(...)` usage.",
                    suggestion="Avoid exec/eval; use safe parsing, explicit dispatch, or well-typed APIs instead.",
                    location=loc_from_line(ctx, line=line_no),
                )
            )
            if len(violations) >= 10:
                break
        return violations


def builtin_gemini_rules() -> list[BaseRule]:
    return [
        D01ComprehensiveIntroComment(),
        D02DebugPrintSpray(),
        D03NestedTernaryExpression(),
        D04AsyncWithoutAwait(),
        D05GlobalKeywordUsed(),
        D06ExecEvalUsed(),
    ]


def _check_python_nested_ternary(rule: BaseRule, ctx: FileContext) -> list[Violation]:
    import ast

    def depth(node: ast.AST) -> int:
        if isinstance(node, ast.IfExp):
            return 1 + max(depth(node.body), depth(node.orelse))
        # Recurse into children
        max_child = 0
        for child in ast.iter_child_nodes(node):
            max_child = max(max_child, depth(child))
        return max_child

    for node in ast.walk(ctx.python_ast):  # type: ignore[arg-type]
        if isinstance(node, ast.IfExp):
            d = depth(node)
            if d > 2 and hasattr(node, "lineno"):
                return [
                    rule._violation(
                        message=f"Nested ternary expression depth is {d}.",
                        suggestion="Replace nested ternaries with clear if/elif blocks.",
                        location=loc_from_line(ctx, line=int(node.lineno)),
                    )
                ]
    return []


def _check_python_async_without_await(rule: BaseRule, ctx: FileContext) -> list[Violation]:
    import ast

    for node in ast.walk(ctx.python_ast):  # type: ignore[arg-type]
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        has_await = any(isinstance(child, ast.Await) for child in ast.walk(node))
        if not has_await and hasattr(node, "lineno"):
            return [
                rule._violation(
                    message=f"Async function `{node.name}` contains no await.",
                    suggestion="Remove `async` or add awaited I/O; avoid unnecessary async wrappers.",
                    location=loc_from_line(ctx, line=int(node.lineno)),
                )
            ]
    return []


def _check_tree_sitter_nested_ternary(rule: BaseRule, ctx: FileContext) -> list[Violation]:
    root = ctx.syntax_tree.root_node  # type: ignore[union-attr]

    depth, node = _max_conditional_depth(root)
    if depth > 2 and node is not None:
        row, col = node.start_point
        return [
            rule._violation(
                message=f"Nested ternary expression depth is {depth}.",
                suggestion="Replace nested ternaries with clearer control flow.",
                location=loc_from_line(ctx, line=row + 1, col=col + 1),
            )
        ]
    return []


def _max_conditional_depth(node: Any) -> tuple[int, Any | None]:
    """
    Return (max_depth, node_at_max_depth) for nested conditional_expression nodes.
    """

    max_depth = 0
    max_node = None

    for child in getattr(node, "children", []):
        child_depth, child_node = _max_conditional_depth(child)
        if child_depth > max_depth:
            max_depth, max_node = child_depth, child_node

    if getattr(node, "type", None) == "conditional_expression":
        depth_here = 1
        for child in getattr(node, "children", []):
            if getattr(child, "type", None) == "conditional_expression":
                d, _ = _max_conditional_depth(child)
                depth_here = max(depth_here, 1 + d)
        if depth_here > max_depth:
            return depth_here, node

    return max_depth, max_node


def _check_tree_sitter_async_without_await(rule: BaseRule, ctx: FileContext) -> list[Violation]:
    root = ctx.syntax_tree.root_node  # type: ignore[union-attr]
    source = ctx.text.encode("utf-8", errors="replace")

    for node in _iter_nodes(root):
        if getattr(node, "type", None) not in {"function_declaration", "function", "method_definition", "arrow_function"}:
            continue

        node_text = source[node.start_byte : node.end_byte].decode("utf-8", errors="replace").lstrip()
        if not node_text.startswith("async"):
            continue

        if _has_descendant_type(node, "await_expression"):
            continue

        row, col = node.start_point
        return [
            rule._violation(
                message="Async function contains no await.",
                suggestion="Remove `async` or use awaited operations; avoid cargo-cult async.",
                location=loc_from_line(ctx, line=row + 1, col=col + 1),
            )
        ]

    return []


def _iter_nodes(node: Any) -> Iterator[Any]:
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(reversed(getattr(n, "children", [])))


def _has_descendant_type(node: Any, node_type: str) -> bool:
    for child in _iter_nodes(node):
        if getattr(child, "type", None) == node_type:
            return True
    return False
