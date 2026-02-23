from __future__ import annotations

from helpers import make_file_ctx

from slopsentinel.rules.gemini import (
    D01ComprehensiveIntroComment,
    D03NestedTernaryExpression,
    D04AsyncWithoutAwait,
)


def test_d01_comprehensive_comment(project_ctx) -> None:
    ctx = make_file_ctx(project_ctx, relpath="src/example.py", content="# Here's a comprehensive solution\nx = 1\n")
    violations = D01ComprehensiveIntroComment().check_file(ctx)
    assert any(v.rule_id == "D01" for v in violations)


def test_d03_nested_ternary_expression(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content="x = 1 if a else 2 if b else 3 if c else 4\n",
    )
    violations = D03NestedTernaryExpression().check_file(ctx)
    assert any(v.rule_id == "D03" for v in violations)


def test_d03_nested_ternary_negative_depth_2(project_ctx) -> None:
    ctx = make_file_ctx(project_ctx, relpath="src/example.py", content="x = 1 if a else 2 if b else 3\n")
    assert D03NestedTernaryExpression().check_file(ctx) == []


def test_d04_async_without_await(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "async def f():\n"
            "    return 1\n"
        ),
    )
    violations = D04AsyncWithoutAwait().check_file(ctx)
    assert any(v.rule_id == "D04" for v in violations)


def test_d04_async_without_await_negative(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "async def f():\n"
            "    await g()\n"
        ),
    )
    assert D04AsyncWithoutAwait().check_file(ctx) == []

